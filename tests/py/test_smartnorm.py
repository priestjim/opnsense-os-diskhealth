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

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'src', 'opnsense', 'scripts', 'OPNsense', 'DiskHealth'))
import smartnorm  # noqa: E402


def fx(name):
    with open(os.path.join(HERE, '..', 'fixtures', name + '.json')) as handle:
        return json.load(handle)


class NormalizeTest(unittest.TestCase):
    def test_real_nvme_capture(self):
        r = smartnorm.normalize('nvme0', fx('nvme_team_tm8fpw001t'))
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['issues'], [])
        self.assertEqual(r['media'], 'nvme')
        self.assertEqual(r['model'], 'TEAM TM8FPW001T')
        self.assertEqual(r['temperature_c'], 40)
        self.assertEqual(r['bytes_written'], 12820885 * 512000)
        self.assertEqual(r['percent_used'], 1)
        self.assertEqual(r['spare_percent'], 100)
        self.assertEqual(r['bad_blocks'], 0)
        self.assertEqual(r['unsafe_shutdowns'], 35)
        self.assertEqual(r['power_on_hours'], 15986)
        self.assertEqual(r['power_cycles'], 254)

    def test_real_sata_hdd_capture(self):
        r = smartnorm.normalize('sda', fx('ata_hdd_seagate_st16000nt001'))
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['issues'], [])
        self.assertEqual(r['media'], 'hdd')
        # device statistics beat the vendor attribute (which is slightly ahead)
        self.assertEqual(r['bytes_written'], 10570366328 * 512)
        self.assertEqual(r['power_on_hours'], 14315)
        self.assertEqual(r['bad_blocks'], 0)
        self.assertIsNone(r['percent_used'])  # spinning disks report no wear
        self.assertEqual(r['error_log_entries'], 0)  # smartctl 7.4 nests it under "extended"

    def test_temperature_never_changes_the_verdict(self):
        for fixture, temps in (('nvme_team_tm8fpw001t', (40, 95, 200)), ('ata_hdd', (30, 70, 120))):
            for temp in temps:
                info = fx(fixture)
                info['temperature']['current'] = temp
                r = smartnorm.normalize('d', info)
                self.assertEqual(r['temperature_c'], temp)
                self.assertFalse([i for i in r['issues'] if 'emperature' in i], r['issues'])
        self.assertEqual(smartnorm.normalize('d', fx('ata_hdd'))['status'], 'ok')

    def test_ata_ssd_attributes(self):
        r = smartnorm.normalize('ada1', fx('ata_ssd'))
        self.assertEqual(r['media'], 'ssd')
        self.assertEqual(r['bytes_written'], 2000000000 * 512)
        self.assertEqual(r['percent_used'], 12)
        self.assertEqual(r['status'], 'ok')

    def test_device_statistics_win_over_attributes(self):
        r = smartnorm.normalize('ada2', fx('ata_ssd_devstat'))
        self.assertEqual(r['bytes_written'], 1000 * 4096)
        self.assertEqual(r['percent_used'], 5)
        self.assertEqual(r['power_on_hours'], 777)

    def test_failing_disk_is_critical(self):
        r = smartnorm.normalize('ada3', fx('failing'))
        self.assertEqual(r['status'], 'critical')
        self.assertIs(r['smart_passed'], False)
        self.assertEqual(r['reallocated'], 1500)
        self.assertEqual(r['pending'], 8)
        self.assertEqual(r['uncorrectable'], 3)  # "3 (0 0 0)" -> leading integer
        self.assertEqual(r['bad_blocks'], 1511)
        self.assertEqual(r['crc_errors'], 2)

    def test_warning_levels(self):
        info = fx('ata_hdd')
        info['ata_smart_attributes']['table'][0]['raw'] = {'value': 4, 'string': '4'}  # reallocated
        r = smartnorm.normalize('ada0', info)
        self.assertEqual(r['status'], 'warning')
        self.assertEqual(r['bad_blocks'], 4)

    def test_nvme_critical_conditions(self):
        info = fx('nvme_team_tm8fpw001t')
        info['nvme_smart_health_information_log']['critical_warning'] = 4
        self.assertEqual(smartnorm.normalize('n', info)['status'], 'critical')
        info = fx('nvme_team_tm8fpw001t')
        info['nvme_smart_health_information_log']['available_spare'] = 10
        self.assertEqual(smartnorm.normalize('n', info)['status'], 'critical')
        info = fx('nvme_team_tm8fpw001t')
        info['nvme_smart_health_information_log']['percentage_used'] = 95
        self.assertEqual(smartnorm.normalize('n', info)['status'], 'warning')
        info['nvme_smart_health_information_log']['percentage_used'] = 100
        self.assertEqual(smartnorm.normalize('n', info)['status'], 'critical')

    def test_failed_self_test_in_extended_layout(self):
        info = fx('ata_hdd_seagate_st16000nt001')
        info['ata_smart_self_test_log']['extended']['table'][0]['status']['passed'] = False
        r = smartnorm.normalize('sda', info)
        self.assertEqual(r['status'], 'warning')
        self.assertTrue(any('self-test' in i for i in r['issues']))

    def test_error_log_layouts(self):
        info = fx('ata_hdd_seagate_st16000nt001')
        info['ata_smart_error_log']['extended']['count'] = 4
        self.assertEqual(smartnorm.normalize('sda', info)['error_log_entries'], 4)
        self.assertEqual(smartnorm.normalize('ada0', fx('ata_hdd'))['error_log_entries'], 0)  # "summary"

    def test_unavailable_smart_is_unknown_not_an_error(self):
        for name in ('no_smart', 'permission_denied'):
            r = smartnorm.normalize('x', fx(name))
            self.assertEqual(r['status'], 'unknown')
            self.assertTrue(r['error'])
        self.assertIn('Permission denied', smartnorm.normalize('x', fx('permission_denied'))['error'])
        self.assertEqual(smartnorm.normalize('x', None)['status'], 'unknown')

    def test_missing_values_are_none_not_zero(self):
        r = smartnorm.normalize('ada0', fx('ata_hdd'))
        self.assertIsNone(r['bytes_written'])
        self.assertIsNone(r['percent_used'])
        self.assertIsNone(r['media_errors'])

    def test_input_is_not_mutated(self):
        info = fx('failing')
        before = copy.deepcopy(info)
        smartnorm.normalize('ada3', info)
        self.assertEqual(info, before)


if __name__ == '__main__':
    unittest.main()
