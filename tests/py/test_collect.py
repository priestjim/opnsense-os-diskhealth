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

import json
import os
import stat
import sys
import syslog
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'src', 'opnsense', 'scripts', 'OPNsense', 'DiskHealth'))
import collect  # noqa: E402


def fx_text(name):
    with open(os.path.join(HERE, '..', 'fixtures', name + '.json')) as handle:
        return handle.read()


def fake_runner(scan, outputs, kern_disks=''):
    """Pretend to be smartctl: `outputs` maps device path -> JSON text."""
    calls = []

    def runner(cmd, timeout=None):
        calls.append(cmd)
        if cmd[1:3] == ['--scan', '--json=c']:
            return json.dumps({'devices': scan})
        if cmd[0].endswith('sysctl'):
            return kern_disks
        return outputs.get(cmd[-1], '')
    runner.calls = calls
    return runner


class ListDevicesTest(unittest.TestCase):
    def test_uses_smartctl_scan_with_its_device_type(self):
        runner = fake_runner([{'name': '/dev/nvme0', 'type': 'nvme'}, {'name': '/dev/ada0', 'type': 'atacam'}], {})
        self.assertEqual(collect.list_devices(runner),
                         [('nvme0', '/dev/nvme0', 'nvme'), ('ada0', '/dev/ada0', 'atacam')])

    def test_falls_back_to_kern_disks(self):
        runner = fake_runner([], {}, kern_disks='nda0 ada0 cd0 md0\n')
        self.assertEqual(collect.list_devices(runner), [('nvme0', '/dev/nvme0', None), ('ada0', '/dev/ada0', None)])

    def test_garbage_scan_output_does_not_crash(self):
        garbage_scan = lambda cmd, timeout=None: 'not json' if '--scan' in cmd else ''  # noqa: E731
        self.assertEqual(collect.list_devices(garbage_scan), [])


class ReadDeviceTest(unittest.TestCase):
    def test_standby_flag_only_for_non_nvme(self):
        runner = fake_runner([], {})
        collect.read_device('nvme0', '/dev/nvme0', 'nvme', runner)
        collect.read_device('ada0', '/dev/ada0', 'atacam', runner)
        nvme_cmd, ata_cmd = runner.calls
        self.assertNotIn('-n', nvme_cmd)
        self.assertEqual(ata_cmd[ata_cmd.index('-n') + 1], 'standby')
        self.assertEqual(ata_cmd[ata_cmd.index('-d') + 1], 'atacam')

    def test_non_json_output_gives_unknown_record(self):
        rec, _ = collect.read_device('ada0', '/dev/ada0', None, fake_runner([], {'/dev/ada0': 'boom'}))
        self.assertEqual(rec['status'], 'unknown')


ALL_DISKS = dict(collect.default_config(), monitored={'nvme0', 'ada0'})


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.scan = [{'name': '/dev/nvme0', 'type': 'nvme'}, {'name': '/dev/ada0', 'type': 'atacam'}]

    def test_collects_all_disks(self):
        runner = fake_runner(self.scan, {'/dev/nvme0': fx_text('nvme'), '/dev/ada0': fx_text('failing')})
        doc = collect.collect({}, runner, now=1700000000, config=ALL_DISKS)
        self.assertEqual(doc['generated'], 1700000000)
        self.assertEqual([d['device'] for d in doc['disks']], ['nvme0', 'ada0'])
        self.assertEqual([d['status'] for d in doc['disks']], ['ok', 'critical'])

    def test_sleeping_disk_keeps_previous_record(self):
        standby = json.dumps({'smartctl': {'messages': [
            {'string': 'Device is in STANDBY mode, exit(2)', 'severity': 'information'}], 'exit_status': 2}})
        first = collect.collect({}, fake_runner(self.scan, {'/dev/nvme0': fx_text('nvme'),
                                                            '/dev/ada0': fx_text('ata_hdd')}), config=ALL_DISKS)
        second = collect.collect(first, fake_runner(self.scan, {'/dev/nvme0': fx_text('nvme'), '/dev/ada0': standby}), config=ALL_DISKS)
        sleeping = second['disks'][1]
        self.assertTrue(sleeping['standby'])
        self.assertEqual(sleeping['model'], 'WDC WD40EFRX')
        self.assertEqual(sleeping['temperature_c'], first['disks'][1]['temperature_c'])

    def test_transitions_are_logged_once(self):
        lines = []
        log = lambda level, msg: lines.append((level, msg))  # noqa: E731
        healthy = collect.collect({}, fake_runner(self.scan, {'/dev/nvme0': fx_text('nvme'),
                                                              '/dev/ada0': fx_text('ata_hdd')}), config=ALL_DISKS)
        failing = collect.collect(healthy, fake_runner(self.scan, {'/dev/nvme0': fx_text('nvme'),
                                                                   '/dev/ada0': fx_text('failing')}), config=ALL_DISKS)
        collect.log_transitions({}, healthy, log, temp_alerts=False)  # health only, not the 63 C of the failing disk
        self.assertEqual(lines, [])
        collect.log_transitions(healthy, failing, log, temp_alerts=False)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][0], syslog.LOG_CRIT)
        self.assertIn('ada0', lines[0][1])
        collect.log_transitions(failing, failing, log, temp_alerts=False)  # no change, no spam
        self.assertEqual(len(lines), 1)
        collect.log_transitions(failing, healthy, log, temp_alerts=False)
        self.assertEqual(lines[-1][0], syslog.LOG_NOTICE)


    def test_a_failed_read_neither_recovers_nor_repeats_a_critical_disk(self):
        lines = []
        log = lambda level, msg: lines.append((level, msg))  # noqa: E731
        nvme = {'/dev/nvme0': fx_text('nvme')}
        failing = collect.collect({}, fake_runner(self.scan, dict(nvme, **{'/dev/ada0': fx_text('failing')})),
                                  config=ALL_DISKS)
        unreadable = collect.collect(failing, fake_runner(self.scan, dict(nvme, **{'/dev/ada0': 'not json'})),
                                     config=ALL_DISKS)
        self.assertEqual(unreadable['disks'][1]['status'], 'unknown')
        collect.log_transitions(failing, unreadable, log, temp_alerts=False)
        self.assertEqual(lines, [])  # not 'recovered, now unknown'

        back = collect.collect(unreadable, fake_runner(self.scan, dict(nvme, **{'/dev/ada0': fx_text('failing')})),
                               config=ALL_DISKS)
        collect.log_transitions(unreadable, back, log, temp_alerts=False)
        self.assertEqual(lines, [])  # still the same critical disk: no second alert

        healthy = collect.collect(unreadable, fake_runner(self.scan, dict(nvme, **{'/dev/ada0': fx_text('ata_hdd')})),
                                  config=ALL_DISKS)
        collect.log_transitions(unreadable, healthy, log, temp_alerts=False)
        self.assertEqual([level for level, _ in lines], [syslog.LOG_NOTICE])  # recovery is still announced


class CacheFileTest(unittest.TestCase):
    def test_atomic_write_is_world_readable_and_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'sub', 'status.json')
            collect.write_cache({'disks': []}, path)
            collect.write_cache({'disks': [], 'generated': 1}, path)
            self.assertEqual(collect.load_cache(path)['generated'], 1)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)
            self.assertEqual(os.listdir(os.path.dirname(path)), ['status.json'])

    def test_cache_directory_stays_readable_under_a_strict_umask(self):
        old = os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, 'run', 'status.json')
                collect.write_cache({'disks': []}, path)
                self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o755)
        finally:
            os.umask(old)

    def test_load_cache_tolerates_missing_and_corrupt_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(collect.load_cache(os.path.join(tmp, 'nope.json')), {})
            bad = os.path.join(tmp, 'bad.json')
            with open(bad, 'w') as handle:
                handle.write('{truncated')
            self.assertEqual(collect.load_cache(bad), {})


if __name__ == '__main__':
    unittest.main()


CONFIG = """\
[general]
unit = C
warning_temp = 45
critical_temp = 60
temp_alerts = 1

[ada0]
enabled = 1
warning_temp =
critical_temp = 70

[nvme0]
enabled = 0
"""


def write_config(text):
    handle, path = tempfile.mkstemp(suffix='.conf')
    with os.fdopen(handle, 'w') as out:
        out.write(text)
    return path


class ConfigTest(unittest.TestCase):
    def test_missing_or_garbled_file_means_defaults(self):
        for path in ('/nonexistent/diskhealth.conf', write_config('\x00 not [ini')):
            cfg = collect.load_config(path)
            self.assertEqual(cfg['monitored'], set())
            self.assertEqual((cfg['warning_c'], cfg['critical_c']), (60, 80))
            self.assertTrue(cfg['temp_alerts'])

    def test_reads_globals_and_disks(self):
        cfg = collect.load_config(write_config(CONFIG))
        self.assertEqual((cfg['warning_c'], cfg['critical_c']), (45, 60))
        self.assertEqual(cfg['monitored'], {'ada0'})
        self.assertEqual(collect.effective_limits(cfg, 'ada0'), (45, 70))  # warning inherited, critical overridden
        self.assertEqual(collect.effective_limits(cfg, 'ada9'), (45, 60))

    def test_fahrenheit_limits_are_converted_to_celsius(self):
        cfg = collect.load_config(write_config(
            '[general]\nunit = F\nwarning_temp = 140\ncritical_temp = 176\n[ada0]\nenabled = 1\ncritical_temp = 194\n'))
        self.assertEqual((cfg['warning_c'], cfg['critical_c']), (60, 80))
        self.assertEqual(collect.effective_limits(cfg, 'ada0'), (60, 90))

    def test_no_disk_entries_or_only_disabled_entries_monitor_nothing(self):
        self.assertEqual(collect.load_config(write_config('[general]\nunit = C\n'))['monitored'], set())
        self.assertEqual(collect.load_config(write_config('[ada0]\nenabled = 0\n'))['monitored'], set())

    def test_inverted_limits_fall_back_to_the_globals(self):
        cfg = collect.load_config(write_config(
            '[general]\nwarning_temp = 45\ncritical_temp = 60\n[ada0]\nenabled = 1\nwarning_temp = 85\n'))
        self.assertEqual(collect.effective_limits(cfg, 'ada0'), (45, 60))
        bad = collect.load_config(write_config('[general]\nwarning_temp = 90\ncritical_temp = 70\n'))
        self.assertEqual((bad['warning_c'], bad['critical_c']), (60, 80))


class TemperatureStatusTest(unittest.TestCase):
    cfg = {'warning_c': 45, 'critical_c': 60, 'limits': {}, 'temp_alerts': True, 'monitored': set()}

    def status(self, **rec):
        return collect.temperature_status(dict({'device': 'ada0', 'temperature_c': None, 'standby': False}, **rec),
                                          self.cfg)

    def test_levels(self):
        self.assertEqual(self.status(temperature_c=44), 'ok')
        self.assertEqual(self.status(temperature_c=45), 'warning')
        self.assertEqual(self.status(temperature_c=60), 'critical')

    def test_unknown_temperature_is_not_a_verdict(self):
        self.assertIsNone(self.status(temperature_c=None))

    def test_a_sleeping_disk_has_no_current_temperature(self):
        self.assertIsNone(self.status(temperature_c=90, standby=True))


class MonitoringTest(unittest.TestCase):
    def setUp(self):
        self.scan = [{'name': '/dev/nvme0', 'type': 'nvme'}, {'name': '/dev/ada0', 'type': 'atacam'}]
        self.outputs = {'/dev/nvme0': fx_text('nvme'), '/dev/ada0': fx_text('failing')}

    def cfg(self, **kw):
        return dict({'warning_c': 45, 'critical_c': 60, 'limits': {}, 'temp_alerts': True,
                     'monitored': {'nvme0', 'ada0'}}, **kw)

    def test_every_listed_disk_is_probed(self):
        doc = collect.collect({}, fake_runner(self.scan, self.outputs), config=self.cfg())
        self.assertEqual([d['device'] for d in doc['disks']], ['nvme0', 'ada0'])
        self.assertEqual([d['temperature_status'] for d in doc['disks']], ['ok', 'critical'])
        self.assertEqual([(d['temp_warning_c'], d['temp_critical_c']) for d in doc['disks']], [(45, 60)] * 2)

    def test_nothing_is_monitored_without_a_list(self):
        runner = fake_runner(self.scan, self.outputs)
        doc = collect.collect({}, runner, config=self.cfg(monitored=set()))
        self.assertEqual(doc['disks'], [])
        self.assertEqual(runner.calls, [])  # not even a device scan

    def test_unmonitored_disks_are_never_probed(self):
        runner = fake_runner(self.scan, self.outputs)
        doc = collect.collect({}, runner, config=self.cfg(monitored={'nvme0'}))
        self.assertEqual([d['device'] for d in doc['disks']], ['nvme0'])
        self.assertFalse([c for c in runner.calls if c[-1] == '/dev/ada0'])

    def test_a_standby_disk_reuses_the_record_without_a_temperature_verdict(self):
        standby = json.dumps({'smartctl': {'messages': [{'string': 'Device is in STANDBY mode'}], 'exit_status': 2}})
        first = collect.collect({}, fake_runner(self.scan, self.outputs), config=self.cfg())
        second = collect.collect(first, fake_runner(self.scan, dict(self.outputs, **{'/dev/ada0': standby})),
                                 config=self.cfg())
        self.assertTrue(second['disks'][1]['standby'])
        self.assertIsNone(second['disks'][1]['temperature_status'])

    def test_a_disk_going_to_sleep_is_not_logged_as_recovered(self):
        lines = []
        log = lambda level, msg: lines.append((level, msg))  # noqa: E731
        hot = {'disks': [{'device': 'ada0', 'status': 'ok', 'issues': [], 'temperature_c': 65,
                          'temperature_status': 'critical'}]}
        asleep = {'disks': [dict(hot['disks'][0], standby=True, temperature_status=None)]}
        collect.log_transitions(hot, asleep, log, temp_alerts=True)
        self.assertEqual(lines, [])

    def test_a_hot_disk_waking_up_hot_is_not_announced_twice(self):
        lines = []
        log = lambda level, msg: lines.append((level, msg))  # noqa: E731
        standby = json.dumps({'smartctl': {'messages': [{'string': 'Device is in STANDBY mode'}], 'exit_status': 2}})
        hot = {'disks': [{'device': 'ada0', 'model': 'X', 'status': 'ok', 'issues': [], 'temperature_c': 65,
                          'temperature_status': 'critical'}]}
        asleep = collect.collect(hot, fake_runner(self.scan, {'/dev/ada0': standby, '/dev/nvme0': '{}'}),
                                 config=self.cfg())
        rec = [d for d in asleep['disks'] if d['device'] == 'ada0'][0]
        self.assertIsNone(rec['temperature_status'])
        collect.log_transitions(hot, asleep, log, temp_alerts=True)
        collect.log_transitions(asleep, hot, log, temp_alerts=True)
        self.assertEqual(lines, [])

    def test_scan_lists_every_detected_disk(self):
        self.assertEqual(collect.scan(fake_runner(self.scan, {})), ['nvme0', 'ada0'])

    def test_temperature_transitions_are_logged_when_alerts_are_on(self):
        lines = []
        log = lambda level, msg: lines.append((level, msg))  # noqa: E731
        cool = {'disks': [{'device': 'ada0', 'status': 'ok', 'issues': [], 'temperature_c': 40,
                           'temperature_status': 'ok'}]}
        hot = {'disks': [{'device': 'ada0', 'status': 'ok', 'issues': [], 'temperature_c': 65,
                          'temperature_status': 'critical'}]}
        collect.log_transitions(cool, hot, log, temp_alerts=True)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][0], syslog.LOG_CRIT)
        self.assertIn('65', lines[0][1])
        collect.log_transitions(hot, hot, log, temp_alerts=True)
        self.assertEqual(len(lines), 1)
        collect.log_transitions(hot, cool, log, temp_alerts=True)
        self.assertEqual(lines[-1][0], syslog.LOG_NOTICE)
        n = len(lines)
        collect.log_transitions(cool, hot, log, temp_alerts=False)
        self.assertEqual(len(lines), n)
