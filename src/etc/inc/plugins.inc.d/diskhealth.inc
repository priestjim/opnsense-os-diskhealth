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

/**
 * Run the SMART collector regularly; the widget and the system status read
 * its cache. Registered as an automatic cron job, interval from Services > Disk Health.
 */
function diskhealth_cron()
{
    $jobs = [];

    try {
        $general = new \OPNsense\DiskHealth\General();
        $enabled = $general->isEnabled();
        $interval = $general->getInterval();
    } catch (\Throwable $e) {
        /* an exception here would stop cron generation for every plugin, fall back to the defaults */
        error_log($e);
        $enabled = true;
        $interval = 5;
    }

    if ($enabled) {
        $jobs[]['autocron'] = [
            '/usr/local/sbin/configctl -d diskhealth collect',
            $interval > 1 ? '*/' . $interval : '*'
        ];
    }

    return $jobs;
}
