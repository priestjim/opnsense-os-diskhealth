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

use OPNsense\Base\ApiMutableModelControllerBase;

class GeneralController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'general';
    protected static $internalModelClass = 'OPNsense\DiskHealth\General';

    private static function convertTemperature($value, $unit)
    {
        return (int)round($unit === 'F' ? (float)$value * 9 / 5 + 32 : ((float)$value - 32) * 5 / 9);
    }

    /**
     * Per-disk limits are stored in the selected unit just like the global ones: when the unit changes,
     * convert them too, otherwise a stored 60 would silently turn from 60 °C into 60 °F.
     * The converted limits are validated first; if one would leave the allowed range or lose its order
     * (rounding), nothing is saved and the unit field names the disks to fix.
     */
    public function setAction()
    {
        if ($this->request->isPost()) {
            $model = $this->getModel();
            $posted = $this->request->getPost(static::$internalModelName);
            $old = (string)$model->temp_unit;
            $new = is_array($posted) ? ($posted['temp_unit'] ?? $old) : $old;
            if ($new !== $old && in_array($new, ['C', 'F'], true)) {
                $converted = [];
                $invalid = [];
                foreach ($model->disks->disk->iterateItems() as $uuid => $disk) {
                    $limits = [];
                    foreach (['warning_temp', 'critical_temp'] as $field) {
                        $value = (string)$disk->$field;
                        $limits[$field] = $value === '' ? '' : self::convertTemperature($value, $new);
                    }
                    $inRange = fn($v) => $v === '' || ($v >= 1 && $v <= 400);
                    $ordered = $limits['warning_temp'] === '' || $limits['critical_temp'] === ''
                        || $limits['critical_temp'] > $limits['warning_temp'];
                    if (!$inRange($limits['warning_temp']) || !$inRange($limits['critical_temp']) || !$ordered) {
                        $invalid[] = (string)$disk->device;
                    }
                    $converted[$uuid] = $limits;
                }
                if (!empty($invalid)) {
                    return [
                        'result' => 'failed',
                        'validations' => [
                            static::$internalModelName . '.temp_unit' => sprintf(
                                gettext('The limits of %s cannot be converted to the new unit. Adjust them first.'),
                                implode(', ', $invalid)
                            ),
                        ],
                    ];
                }
                foreach ($model->disks->disk->iterateItems() as $uuid => $disk) {
                    foreach ($converted[$uuid] as $field => $value) {
                        $disk->$field = (string)$value;
                    }
                }
            }
        }

        return parent::setAction();
    }

    public function searchDiskAction()
    {
        return $this->searchBase('disks.disk', ['enabled', 'device', 'warning_temp', 'critical_temp'], 'device');
    }

    public function getDiskAction($uuid = null)
    {
        return $this->getBase('disk', 'disks.disk', $uuid);
    }

    public function addDiskAction()
    {
        return $this->addBase('disk', 'disks.disk');
    }

    public function setDiskAction($uuid)
    {
        return $this->setBase('disk', 'disks.disk', $uuid);
    }

    public function delDiskAction($uuid)
    {
        return $this->delBase('disks.disk', $uuid);
    }

    public function toggleDiskAction($uuid, $enabled = null)
    {
        return $this->toggleBase('disks.disk', $uuid, $enabled);
    }
}
