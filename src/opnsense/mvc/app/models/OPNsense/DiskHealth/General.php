<?php

/*
 * Copyright (C) 2026 Panagiotis Papadomitsos
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
 * INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
 * AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
 * OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

namespace OPNsense\DiskHealth;

use OPNsense\Base\BaseModel;

class General extends BaseModel
{
    /* written atomically by collect.py, world-readable */
    public const CACHE = '/var/run/diskhealth/status.json';

    /**
     * @return array|null the collected data, null when there is none yet
     */
    public function readCache()
    {
        $data = json_decode((string)@file_get_contents(self::CACHE), true);

        return is_array($data) ? $data : null;
    }

    /**
     * @param array|null $data result of readCache()
     * @return bool true when the collector delivered it recently enough, see getMaxAge()
     */
    public function isFresh($data)
    {
        return is_array($data) && !empty($data['generated']) && (time() - $data['generated']) <= $this->getMaxAge();
    }

    /**
     * @return array the devices the saved settings monitor: the enabled entries, none when nothing is listed
     */
    public function getMonitoredDevices()
    {
        $devices = [];
        foreach ($this->disks->disk->iterateItems() as $disk) {
            if ((string)$disk->enabled === '1') {
                $devices[] = (string)$disk->device;
            }
        }

        return $devices;
    }

    /**
     * Settings apply before the next collection: leave out what they no longer monitor, so data of a removed or
     * disabled disk neither shows up in the widget nor raises an alert.
     *
     * @param array|null $data result of readCache()
     * @param array|null $devices result of getMonitoredDevices() when the caller already has it
     * @return array|null
     */
    public function onlyMonitored($data, $devices = null)
    {
        if (!is_array($data)) {
            return $data;
        }
        $devices ??= $this->getMonitoredDevices();
        $data['disks'] = array_values(array_filter(
            $data['disks'] ?? [],
            fn($disk) => is_array($disk) && in_array($disk['device'] ?? null, $devices, true)
        ));

        return $data;
    }

    public function isEnabled()
    {
        return (string)$this->enabled === '1';
    }

    public function alertsOnWarnings()
    {
        return (string)$this->alert_warnings === '1';
    }

    public function alertsOnTemperature()
    {
        return (string)$this->temp_alerts === '1';
    }

    /**
     * @return int minutes between two collections
     */
    public function getInterval()
    {
        return max(1, (int)(string)$this->interval);
    }

    /**
     * @return int seconds after which collected data is considered stale: three missed runs, at least 15 minutes
     */
    public function getMaxAge()
    {
        return max(15, 3 * $this->getInterval()) * 60;
    }

    public function getUnit()
    {
        return (string)$this->temp_unit === 'F' ? 'F' : 'C';
    }

    /**
     * @return array display settings for the dashboard widget; limits are in the displayed unit
     */
    public function getDisplaySettings()
    {
        return [
            'unit' => $this->getUnit(),
            'warning_temp' => (int)(string)$this->warning_temp,
            'critical_temp' => (int)(string)$this->critical_temp,
        ];
    }
}
