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

namespace OPNsense\System\Status;

use OPNsense\System\AbstractStatus;
use OPNsense\System\SystemStatusCode;
use OPNsense\DiskHealth\General;

/**
 * Raises a system status (the bell in the page header) when a disk is failing or too hot.
 * Only reads the cache written by collect.py; it must never run smartctl
 * because this class is probed on every page load.
 */
class DiskHealthStatus extends AbstractStatus
{
    public function __construct()
    {
        $this->internalPriority = 4;
        $this->internalPersistent = true;
        $this->internalTitle = gettext('Disk Health');
        $this->internalLocation = '/ui/diskhealth/general';
    }

    private function clean($text)
    {
        /* values originate from the drive firmware, keep them plain */
        return preg_replace('/[^A-Za-z0-9 ._:%()\/+,\x27=-]/', '', (string)$text);
    }

    public function collectStatus()
    {
        try {
            $general = new General();
            $enabled = $general->isEnabled();
            $alertWarnings = $general->alertsOnWarnings();
            $alertTemperature = $general->alertsOnTemperature();
            $fahrenheit = $general->getUnit() === 'F';
            /* ignore an outdated cache, a dead cron job must not leave a stale alert behind */
            $data = $enabled ? $general->readCache() : null;
            $fresh = $general->isFresh($data);
            if ($enabled && $fresh) {
                $data = $general->onlyMonitored($data);
            }
        } catch (\Throwable $e) {
            /* an unreadable configuration must not break the status of every page */
            error_log($e);
            return;
        }
        if (!$enabled || !$fresh) {
            return;
        }

        $errors = [];
        $warnings = [];
        /* critical always alerts, warning only when asked to */
        $wanted = fn($severity) => $severity === 'critical' || ($severity === 'warning' && $alertWarnings);
        $add = function ($severity, $line) use (&$errors, &$warnings) {
            if ($severity === 'critical') {
                $errors[] = $line;
            } else {
                $warnings[] = $line;
            }
        };
        foreach ($data['disks'] ?? [] as $disk) {
            /* the collector decides (per disk limits, sleeping disks): the bell and the widget cannot disagree */
            $label = sprintf(
                '%s (%s)',
                $this->clean($disk['device'] ?? '?'),
                $this->clean($disk['model'] ?? gettext('unknown model'))
            );
            $heat = $disk['temperature_status'] ?? '';
            if ($alertTemperature && $wanted($heat) && is_numeric($disk['temperature_c'] ?? null)) {
                $celsius = (float)$disk['temperature_c'];
                $line = sprintf(
                    '%s: %s %d %s',
                    $label,
                    $heat === 'critical' ? gettext('critical temperature') : gettext('high temperature'),
                    round($fahrenheit ? $celsius * 9 / 5 + 32 : $celsius),
                    $fahrenheit ? '°F' : '°C'
                );
                $add($heat, $line);
            }

            $status = $disk['status'] ?? '';
            if (!$wanted($status)) {
                continue;
            }
            $add($status, sprintf('%s: %s', $label, $this->clean(implode('; ', $disk['issues'] ?? []))));
        }

        if (!empty($errors)) {
            $this->internalStatus = SystemStatusCode::ERROR;
        } elseif (!empty($warnings)) {
            $this->internalStatus = SystemStatusCode::WARNING;
        } else {
            return;
        }
        $this->internalTimestamp = (int)$data['generated'];
        $this->internalMessage = gettext('A disk needs attention: ') . implode(' | ', array_merge($errors, $warnings));
    }
}
