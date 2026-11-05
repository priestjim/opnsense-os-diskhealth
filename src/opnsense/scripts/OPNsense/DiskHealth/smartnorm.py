#!/usr/local/bin/python3

# Copyright (C) 2026 Panagiotis Papadomitsos
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
Turn the JSON printed by `smartctl -x --json=c` into one flat, vendor neutral
record per disk, including a health verdict (ok / warning / critical /
unknown) and the human readable reasons behind it.

This is the single source of truth for disk health: the system status alert
and the dashboard widget both consume its output. Temperature is reported but
deliberately does NOT influence the verdict; the widget colours it separately
using user configurable limits.

Missing values are None, never 0.
"""

import math
import re

STATUS_OK = 'ok'
STATUS_WARNING = 'warning'
STATUS_CRITICAL = 'critical'
STATUS_UNKNOWN = 'unknown'

# ATA attributes whose normalized value is "life remaining" (100 = new)
WEAR_REMAINING_ATTRS = (
    'Media_Wearout_Indicator', 'Wear_Leveling_Count', 'SSD_Life_Left', 'Percent_Lifetime_Remain'
)

# ATA attributes holding host writes: name -> bytes per raw unit
WRITTEN_ATTRS = {
    'Host_Writes_32MiB': 32 * 1024 * 1024,
    'Host_Writes_MiB': 1024 * 1024,
    'Lifetime_Writes_GiB': 1024 * 1024 * 1024,
}

# NVMe "data units" are thousands of 512 byte blocks
NVME_DATA_UNIT_BYTES = 512000

_LEADING_INT = re.compile(r'^\s*(\d+)(?!\w)')


def _num(value):
    """Return value if it is a finite number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _get(obj, *path):
    """Safe nested dict lookup, None when any step is missing."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _sum(values):
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _attr_count(attr):
    """
    smartctl pre-formats raw values; prefer its leading integer over raw.value,
    which many vendors pack with extra fields.
    """
    if not attr:
        return None
    match = _LEADING_INT.match(_get(attr, 'raw', 'string') or '')
    if match:
        return int(match.group(1))
    return _num(_get(attr, 'raw', 'value'))


def _devstat(info, name):
    for page in _get(info, 'ata_device_statistics', 'pages') or []:
        for entry in page.get('table') or []:
            flags = entry.get('flags') or {}
            if entry.get('name') == name and flags.get('valid') is not False and flags.get('normalized') is not True:
                return _num(entry.get('value'))
    return None


def new_record(device):
    return {
        'device': device,
        'model': None, 'serial': None, 'firmware': None, 'capacity_bytes': None,
        'protocol': None, 'media': 'unknown',
        'smart_passed': None, 'status': STATUS_UNKNOWN, 'issues': [],
        'temperature_c': None,
        'power_on_hours': None, 'power_cycles': None,
        'bytes_written': None, 'percent_used': None,
        'spare_percent': None, 'spare_threshold': None,
        'reallocated': None, 'pending': None, 'uncorrectable': None,
        'media_errors': None, 'grown_defects': None, 'bad_blocks': None,
        'crc_errors': None, 'error_log_entries': None, 'unsafe_shutdowns': None,
        'critical_warning': None,
        'standby': False,
        'error': None,
    }


def normalize(device, info):
    rec = new_record(device)

    if not isinstance(info, dict):
        rec['error'] = 'No data returned by smartctl'
        rec['issues'].append(rec['error'])
        return rec

    rec['model'] = info.get('model_name') or info.get('scsi_model_name')
    rec['serial'] = info.get('serial_number')
    rec['firmware'] = info.get('firmware_version') or info.get('scsi_revision')
    rec['capacity_bytes'] = _num(_get(info, 'user_capacity', 'bytes'))
    rec['protocol'] = _get(info, 'device', 'protocol')
    passed = _get(info, 'smart_status', 'passed')
    rec['smart_passed'] = passed if isinstance(passed, bool) else None

    nvme = info.get('nvme_smart_health_information_log')
    attrs = _get(info, 'ata_smart_attributes', 'table') or []

    def by_id(attr_id):
        return next((a for a in attrs if a.get('id') == attr_id), None)

    def by_name(name):
        return next((a for a in attrs if a.get('name') == name), None)

    rotation = _num(info.get('rotation_rate'))
    if rec['protocol'] == 'NVMe' or nvme:
        rec['media'] = 'nvme'
    elif rotation is not None and rotation > 0:
        rec['media'] = 'hdd'
    elif rotation == 0:
        rec['media'] = 'ssd'

    # what smartctl itself complained about (device open failures, ...)
    messages = _get(info, 'smartctl', 'messages') or []
    fatal = next((m for m in messages if m.get('severity') == 'error'), None)
    has_data = rec['smart_passed'] is not None or bool(nvme) or bool(attrs)
    if _get(info, 'smart_support', 'available') is False or (not has_data and fatal):
        rec['error'] = (fatal or {}).get('string') or 'SMART not available on this device'
        rec['issues'].append(rec['error'])
        return rec

    nvme = nvme or {}

    # temperature, power
    rec['temperature_c'] = _num(_get(info, 'temperature', 'current'))
    if rec['temperature_c'] is None:
        rec['temperature_c'] = _num(nvme.get('temperature'))
    rec['power_on_hours'] = _num(_get(info, 'power_on_time', 'hours'))
    if rec['power_on_hours'] is None:
        rec['power_on_hours'] = _num(nvme.get('power_on_hours'))
    if rec['power_on_hours'] is None:
        rec['power_on_hours'] = _devstat(info, 'Power-on Hours')
    rec['power_cycles'] = _num(info.get('power_cycle_count'))
    if rec['power_cycles'] is None:
        rec['power_cycles'] = _num(nvme.get('power_cycles'))

    # total data written
    block = _num(info.get('logical_block_size')) or 512
    sectors = _devstat(info, 'Logical Sectors Written')
    lba_attr = by_name('Total_LBAs_Written')
    if _num(nvme.get('data_units_written')) is not None:
        rec['bytes_written'] = nvme['data_units_written'] * NVME_DATA_UNIT_BYTES
    elif sectors is not None:
        rec['bytes_written'] = sectors * block
    elif _attr_count(lba_attr) is not None:
        rec['bytes_written'] = _attr_count(lba_attr) * block
    else:
        for name, multiplier in WRITTEN_ATTRS.items():
            raw = _attr_count(by_name(name))
            if raw is not None:
                rec['bytes_written'] = raw * multiplier
                break

    # wear / endurance
    endurance = _devstat(info, 'Percentage Used Endurance Indicator')
    if _num(nvme.get('percentage_used')) is not None:
        rec['percent_used'] = nvme['percentage_used']
    elif endurance is not None:
        rec['percent_used'] = endurance
    else:
        for name in WEAR_REMAINING_ATTRS:
            attr = by_name(name)
            if attr and _num(attr.get('value')) is not None:
                rec['percent_used'] = 100 - min(100, max(0, attr['value']))
                break
    if nvme:
        rec['spare_percent'] = _num(nvme.get('available_spare'))
        rec['spare_threshold'] = _num(nvme.get('available_spare_threshold'))
        rec['critical_warning'] = _num(nvme.get('critical_warning'))

    # bad blocks
    rec['reallocated'] = _attr_count(by_id(5))
    rec['pending'] = _attr_count(by_id(197))
    rec['uncorrectable'] = _attr_count(by_id(198))
    rec['media_errors'] = _num(nvme.get('media_errors'))
    rec['grown_defects'] = _num(info.get('scsi_grown_defect_list'))
    rec['bad_blocks'] = _sum([rec['reallocated'], rec['pending'], rec['uncorrectable'],
                              rec['media_errors'], rec['grown_defects']])

    # error counters
    rec['crc_errors'] = _attr_count(by_id(199))
    # smartctl nests the ATA error log under "summary" or (7.4+, GP logging) "extended"
    for layout in ('summary', 'extended'):
        count = _num(_get(info, 'ata_smart_error_log', layout, 'count'))
        if count is not None:
            rec['error_log_entries'] = count
            break
    if rec['error_log_entries'] is None:
        rec['error_log_entries'] = _num(nvme.get('num_err_log_entries'))
    rec['unsafe_shutdowns'] = _num(nvme.get('unsafe_shutdowns'))

    _verdict(rec, info, attrs)
    if not has_data:
        rec['status'] = STATUS_UNKNOWN
        rec['error'] = 'No SMART data reported'
        rec['issues'].append(rec['error'])
    return rec


def _verdict(rec, info, attrs):
    """Fill rec['status'] and rec['issues']. Temperature is intentionally not considered."""
    level = 0  # 0 ok, 1 warning, 2 critical
    issues = rec['issues']

    def raise_(lvl, message):
        nonlocal level
        level = max(level, lvl)
        issues.append(message)

    if rec['smart_passed'] is False:
        raise_(2, 'SMART overall health check FAILED')
    if rec['critical_warning']:
        raise_(2, 'NVMe critical warning flags: 0x%x' % rec['critical_warning'])
    for attr in attrs:
        if attr.get('when_failed') == 'now':
            raise_(2, 'Attribute %s is failing now' % attr.get('name'))
        elif attr.get('when_failed') == 'past':
            raise_(1, 'Attribute %s failed in the past' % attr.get('name'))

    used = rec['percent_used']
    if used is not None and used >= 100:
        raise_(2, 'Rated endurance consumed')
    elif used is not None and used >= 90:
        raise_(1, '%d%% of rated endurance used' % used)
    if (rec['spare_percent'] is not None and rec['spare_threshold'] is not None
            and rec['spare_percent'] <= rec['spare_threshold']):
        raise_(2, 'Available spare at or below threshold')

    for key, text in (('reallocated', 'reallocated sectors'), ('pending', 'pending sectors'),
                      ('uncorrectable', 'offline uncorrectable sectors'), ('media_errors', 'media errors'),
                      ('grown_defects', 'grown defects')):
        if rec[key]:
            raise_(1, '%d %s' % (rec[key], text))
    if rec['crc_errors']:
        raise_(1, '%d interface CRC errors (check cable)' % rec['crc_errors'])

    selftests = _get(info, 'ata_smart_self_test_log', 'standard') or _get(info, 'ata_smart_self_test_log', 'extended')
    table = (selftests or {}).get('table') or []
    if table and _get(table[0], 'status', 'passed') is False:
        raise_(1, 'Last self-test failed')

    rec['status'] = (STATUS_OK, STATUS_WARNING, STATUS_CRITICAL)[level]
