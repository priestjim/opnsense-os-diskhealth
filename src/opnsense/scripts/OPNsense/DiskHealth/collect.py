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
Collect SMART health for every disk and publish it as a JSON cache.

Run as root through configd (`configctl diskhealth collect`), normally from
cron. The dashboard widget (via the API) and the system status alert only ever
read the cache, so the page load never waits for smartctl.

Spun-down ATA/SCSI disks are not woken (smartctl -n standby); their previous
record is kept and flagged `standby`.
"""

import argparse
import concurrent.futures
import configparser
import fcntl
import json
import os
import subprocess
import sys
import syslog
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smartnorm  # noqa: E402

SMARTCTL = '/usr/local/sbin/smartctl'
CONFIG_FILE = '/usr/local/etc/diskhealth.conf'  # rendered by configd from the settings model
DEFAULT_WARNING_C = 60
DEFAULT_CRITICAL_C = 80
CACHE_FILE = '/var/run/diskhealth/status.json'
LOCK_NAME = 'collect.lock'  # next to the cache file
CACHE_VERSION = 1
SMARTCTL_TIMEOUT = 60
MAX_PARALLEL = 4  # smartctl calls are subprocess bound; one slow disk must not delay the others

# kern.disks names that smartctl cannot meaningfully read
SKIP_PREFIXES = ('cd', 'md', 'zvol')


def run(cmd, timeout=SMARTCTL_TIMEOUT):
    """Run a command, return stdout text ('' on any failure). Replaceable in tests."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ''
    return proc.stdout


def list_devices(runner=run):
    """Return [(name, path, smartctl_type_or_None)], e.g. ('nvme0', '/dev/nvme0', 'nvme')."""
    devices = []
    try:
        scan = json.loads(runner([SMARTCTL, '--scan', '--json=c']) or '{}')
    except ValueError:
        scan = {}
    for entry in scan.get('devices') or []:
        path = entry.get('name')
        if path:
            devices.append((os.path.basename(path), path, entry.get('type')))
    if devices:
        return devices

    # scan found nothing (e.g. unusual controller): fall back to the kernel's disk list
    for name in (runner(['/sbin/sysctl', '-n', 'kern.disks']) or '').split():
        if name.startswith(SKIP_PREFIXES):
            continue
        if name.startswith('nda'):
            name = 'nvme' + name[len('nda'):]  # the namespace device ndaX is controller nvmeX
        devices.append((name, '/dev/' + name, None))
    return devices


def scan(runner=run):
    """Names of every detected disk, monitored or not (for the settings page)."""
    return [name for name, _path, _type in list_devices(runner)]


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_celsius(value, unit):
    if value is None:
        return None
    return round((value - 32) * 5 / 9, 1) if unit == 'F' else value


def default_config():
    return {'warning_c': DEFAULT_WARNING_C, 'critical_c': DEFAULT_CRITICAL_C, 'limits': {},
            'temp_alerts': True, 'monitored': set()}


def load_config(path=CONFIG_FILE):
    """Read the rendered settings. Missing or unreadable means defaults (60/80 °C, no disk monitored).

    `monitored` is the set of enabled disks: a disk that is not listed is not monitored.
    Limits are stored in the unit chosen on the settings page; they are converted to °C here.
    """
    config = default_config()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(path) as handle:
            parser.read_file(handle)
    except (OSError, UnicodeDecodeError, configparser.Error):
        return config

    general = parser['general'] if parser.has_section('general') else {}
    unit = 'F' if str(general.get('unit', 'C')).strip().upper() == 'F' else 'C'
    warning = _to_celsius(_number(general.get('warning_temp')), unit)
    critical = _to_celsius(_number(general.get('critical_temp')), unit)
    if warning is not None and critical is not None and 0 < warning < critical:
        config['warning_c'], config['critical_c'] = warning, critical
    config['temp_alerts'] = str(general.get('temp_alerts', '1')).strip() != '0'

    for name in parser.sections():
        if name == 'general':
            continue
        section = parser[name]
        if str(section.get('enabled', '1')).strip() == '1':
            config['monitored'].add(name)
        config['limits'][name] = (_to_celsius(_number(section.get('warning_temp')), unit),
                                  _to_celsius(_number(section.get('critical_temp')), unit))
    return config


def effective_limits(config, device):
    """(warning, critical) in °C for one disk: its own value or else the global one.

    An inverted pair (e.g. a disk warning above the global critical) falls back to the globals.
    """
    own_warning, own_critical = config['limits'].get(device, (None, None))
    warning = own_warning if own_warning is not None else config['warning_c']
    critical = own_critical if own_critical is not None else config['critical_c']
    if not 0 < warning < critical:
        return config['warning_c'], config['critical_c']
    return warning, critical


def temperature_status(rec, config):
    """ok/warning/critical from the disk's temperature, None when there is no current reading.

    A sleeping disk's record is the previous one, its temperature is outdated and gives no verdict.
    """
    temperature = rec.get('temperature_c')
    if temperature is None or rec.get('standby'):
        return None
    warning, critical = effective_limits(config, rec['device'])
    if temperature >= critical:
        return 'critical'
    return 'warning' if temperature >= warning else 'ok'


def read_device(name, path, dev_type, runner=run):
    """Run smartctl for one disk, return the normalized record."""
    cmd = [SMARTCTL, '-x', '--json=c']
    if dev_type and dev_type != 'auto':
        cmd += ['-d', dev_type]
    if not (dev_type == 'nvme' or name.startswith('nvme')):
        cmd += ['-n', 'standby']  # do not wake sleeping ATA/SCSI disks
    cmd.append(path)

    output = runner(cmd)
    try:
        info = json.loads(output)
    except ValueError:
        info = None
    return smartnorm.normalize(name, info), info


def _is_standby(info):
    for message in ((info or {}).get('smartctl') or {}).get('messages') or []:
        if 'STANDBY' in (message.get('string') or '').upper():
            return True
    return False


def load_cache(path=CACHE_FILE):
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cache(data, path=CACHE_FILE):
    """Atomically replace the cache; readers never see a partial file."""
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    os.chmod(directory, 0o755)  # makedirs honours the umask; the unprivileged web UI must reach the cache
    handle, tmp = tempfile.mkstemp(dir=directory, prefix='.status-')
    try:
        with os.fdopen(handle, 'w') as out:
            json.dump(data, out, separators=(',', ':'))
        os.chmod(tmp, 0o644)  # the web UI runs unprivileged
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def collect(previous, runner=run, now=None, config=None):
    """Build the cache document. `previous` is the old document (for standby reuse).

    Disks that are not monitored are skipped entirely, smartctl is never run on them.
    """
    config = config or default_config()
    if not config['monitored']:
        return {'version': CACHE_VERSION, 'generated': int(now if now is not None else time.time()), 'disks': []}
    old = {d['device']: d for d in previous.get('disks') or [] if isinstance(d, dict) and 'device' in d}
    targets = [d for d in list_devices(runner) if d[0] in config['monitored']]
    disks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(MAX_PARALLEL, len(targets)))) as pool:
        probed = list(pool.map(lambda target: read_device(*target, runner), targets))  # keeps device order
    for (name, _path, _type), (rec, info) in zip(targets, probed):
        if _is_standby(info) and name in old:
            rec = dict(old[name], standby=True)
            # remember the last real temperature verdict across the sleep, so a hot disk that wakes up
            # hot is not announced again (and one that wakes up cool is announced as recovered)
            rec['last_temperature_status'] = old[name].get('temperature_status') or old[name].get('last_temperature_status')
        # a failed read says nothing about the disk: keep the last real verdict for the syslog transitions
        rec['last_known_status'] = (rec['status'] if rec['status'] != smartnorm.STATUS_UNKNOWN
                                    else _last_known(old.get(name)))
        rec['temperature_status'] = temperature_status(rec, config)
        rec['temp_warning_c'], rec['temp_critical_c'] = effective_limits(config, name)
        disks.append(rec)
    return {'version': CACHE_VERSION, 'generated': int(now if now is not None else time.time()), 'disks': disks}


RANK = {smartnorm.STATUS_UNKNOWN: 0, smartnorm.STATUS_OK: 0, smartnorm.STATUS_WARNING: 1,
        smartnorm.STATUS_CRITICAL: 2}


def _last_known(record):
    """Last health status of an earlier record that was not 'unknown' (None when there is none)."""
    record = record or {}
    status = record.get('last_known_status') or record.get('status')
    return None if status == smartnorm.STATUS_UNKNOWN else status


def _log_change(log, before, after, worse, better):
    """Log `worse` (critical or warning) when the status rose, `better` when it fell."""
    was, now = RANK.get(before, 0), RANK.get(after, 0)
    if now > was:
        log(syslog.LOG_CRIT if now == 2 else syslog.LOG_WARNING, worse)
    elif now < was:
        log(syslog.LOG_NOTICE, better)


def log_transitions(previous, current, log=syslog.syslog, temp_alerts=True):
    """Write one syslog line whenever a disk (or, if enabled, its temperature) gets worse or recovers."""
    old = {d.get('device'): d for d in previous.get('disks') or [] if isinstance(d, dict)}
    for rec in current['disks']:
        prev = old.get(rec['device']) or {}
        model = rec.get('model') or 'unknown model'

        name = '%s (%s)' % (rec['device'], model)
        if rec['status'] != smartnorm.STATUS_UNKNOWN:  # an unreadable disk is neither worse nor recovered
            _log_change(log, _last_known(prev), rec['status'],
                        'disk %s is %s: %s' % (name, rec['status'], '; '.join(rec['issues'])),
                        'disk %s recovered, now %s' % (name, rec['status']))

        if not temp_alerts or rec.get('standby'):
            continue  # a sleeping disk has no current temperature: neither a recovery nor a new alert
        _log_change(log, prev.get('temperature_status') or prev.get('last_temperature_status'),
                    rec.get('temperature_status'),
                    'disk %s temperature is %s: %s C' % (name, rec.get('temperature_status'), rec.get('temperature_c')),
                    'disk %s temperature recovered, now %s' % (name, rec.get('temperature_status') or 'ok'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--cache', default=CACHE_FILE, help='cache file to write')
    parser.add_argument('--config', default=CONFIG_FILE, help='settings file rendered from the GUI')
    parser.add_argument('--scan', action='store_true', help='print the detected disk names as JSON and exit')
    parser.add_argument('--print', action='store_true', dest='show', help='print the cache instead of "OK"')
    args = parser.parse_args(argv)

    if args.scan:
        print(json.dumps(scan()))
        return 0

    os.makedirs(os.path.dirname(args.cache), mode=0o755, exist_ok=True)
    lock = open(os.path.join(os.path.dirname(args.cache), LOCK_NAME), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('already running')
        return 0

    syslog.openlog('diskhealth', 0, syslog.LOG_DAEMON)
    previous = load_cache(args.cache)
    config = load_config(args.config)
    current = collect(previous, config=config)
    log_transitions(previous, current, temp_alerts=config['temp_alerts'])
    write_cache(current, args.cache)
    print(json.dumps(current, indent=2) if args.show else 'OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
