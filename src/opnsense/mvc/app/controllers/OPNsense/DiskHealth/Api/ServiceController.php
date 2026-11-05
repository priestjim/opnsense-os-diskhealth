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

namespace OPNsense\DiskHealth\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;
use OPNsense\DiskHealth\General;

/**
 * Serves the disk health cache to the dashboard widget and applies the settings.
 */
class ServiceController extends ApiControllerBase
{
    public function statusAction()
    {
        $general = new General();
        $settings = $general->getDisplaySettings();

        if (!$general->isEnabled()) {
            return ['enabled' => false, 'settings' => $settings, 'generated' => null, 'disks' => []];
        }

        $monitored = $general->getMonitoredDevices();
        if ($monitored === []) {
            /* nothing is listed, or every listed disk is switched off: nothing to collect, and old data must not linger */
            return ['enabled' => true, 'monitored' => false, 'settings' => $settings, 'generated' => null, 'disks' => []];
        }

        $data = $general->readCache();
        $fresh = $general->isFresh($data);

        if (!$fresh) {
            /* detached: collect.py holds a lock, so repeated polls cannot pile up */
            (new Backend())->configdRun('diskhealth collect', true);
        }
        if ($data === null) {
            $data = ['generated' => null, 'disks' => [], 'pending' => true];
        }
        $data = $general->onlyMonitored($data, $monitored);
        $data['enabled'] = true;
        $data['settings'] = $settings;
        $data['stale'] = !$fresh;

        return $data;
    }

    /**
     * Names of the disks the system detects, for the settings page. Monitored or not.
     */
    public function scanAction()
    {
        $disks = json_decode(trim((new Backend())->configdRun('diskhealth scan')), true);

        return ['disks' => is_array($disks) ? array_values(array_filter($disks, 'is_string')) : []];
    }

    /**
     * Apply saved settings: render the collector configuration, re-register the cron job (interval, enabled) and refresh the data right away.
     */
    public function reconfigureAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed'];
        }
        $backend = new Backend();
        $backend->configdRun('template reload OPNsense/DiskHealth');
        $backend->configdRun('cron restart');
        if ((new General())->isEnabled()) {
            $backend->configdRun('diskhealth collect', true);
        }

        return ['status' => 'ok'];
    }
}
