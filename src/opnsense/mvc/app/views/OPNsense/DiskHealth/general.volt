{#

Copyright (C) 2026 Panagiotis Papadomitsos
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

1.  Redistributions of source code must retain the above copyright notice,
    this list of conditions and the following disclaimer.

2.  Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

#}
<script>
    $(document).ready(function() {
        let currentUnit = null;
        let savedUnit = null;

        /*
         * Disk limits are stored in the saved unit and converted by the server when the unit is saved.
         * Editing them while the unit dropdown shows an unsaved unit would convert them twice.
         */
        function lockDisksOnUnitChange() {
            const locked = savedUnit !== null && $('#general\\.temp_unit').val() !== savedUnit;
            $('#diskGridBox').css({'pointer-events': locked ? 'none' : '', 'opacity': locked ? '0.5' : ''});
            $('#diskUnitNotice').toggle(locked);
        }

        mapDataToFormUI({'frm_general_settings': "/api/diskhealth/general/get"}).done(function() {
            $('.selectpicker').selectpicker('refresh');
            currentUnit = $('#general\\.temp_unit').val();
            savedUnit = currentUnit;
            lockDisksOnUnitChange();
        });

        /*
         * Convert the two limits when the user switches the unit (60/80 °C becomes 140/176 °F).
         * The baseline unit is only taken from the loaded settings, never from an event fired
         * while the form is being filled, otherwise saved Fahrenheit limits would be converted again.
         */
        $('#general\\.temp_unit').on('change', function() {
            const unit = $(this).val();
            if (currentUnit === null || unit === currentUnit) {
                return;
            }
            const convert = (v) => unit === 'F' ? Math.round(v * 9 / 5 + 32) : Math.round((v - 32) * 5 / 9);
            ['warning_temp', 'critical_temp'].forEach(function(name) {
                const $field = $('#general\\.' + name);
                const value = parseFloat($field.val());
                if (!isNaN(value)) {
                    $field.val(convert(value));
                }
            });
            currentUnit = unit;
            lockDisksOnUnitChange();
        });

        /* UIBootgrid replaces the table element: look the grid up when it is used, never keep a reference */
        const grid = () => $("#{{ formGridDisk['table_id'] }}");

        /* names of the detected disks; the dialog reuses the last scan, the add button always scans again */
        let detected = null;
        let waiting = null;
        function detectedDisks(callback, rescan) {
            if (detected !== null && !rescan) {
                callback(detected);
                return;
            }
            if (waiting !== null) {
                waiting.push(callback);  /* a scan is under way, share its result */
                return;
            }
            waiting = [callback];
            ajaxGet("/api/diskhealth/service/scan", {}, function(scan, status) {
                const disks = (scan || {}).disks || [];
                if (status === 'success') {
                    detected = disks;  /* a failed scan must not be remembered as "no disks" */
                }
                const callbacks = waiting;
                waiting = null;
                callbacks.forEach((fn) => fn(disks));
            });
        }

        /*
         * List every detected disk that is not listed yet, one add request after the other.
         * UIBootgrid detaches the footer commands when it starts, so label and bind the button first.
         */
        $("#addDetected").append($("<span>").text(" {{ lang._('Add detected disks') }}")).click(function() {
            detectedDisks(function(disks) {
                ajaxGet("/api/diskhealth/general/search_disk", {rowCount: -1}, function(listed) {
                    const known = (listed.rows || []).map((row) => row.device);
                    const missing = disks.filter((name) => !known.includes(name));
                    const next = function() {
                        if (missing.length === 0) {
                            grid().bootgrid('reload');
                            return;
                        }
                        ajaxCall("/api/diskhealth/general/add_disk/", {disk: {enabled: '1', device: missing.shift()}}, next);
                    };
                    next();
                });
            }, true);
        });

        grid().UIBootgrid({
            search: '/api/diskhealth/general/search_disk',
            get: '/api/diskhealth/general/get_disk/',
            set: '/api/diskhealth/general/set_disk/',
            add: '/api/diskhealth/general/add_disk/',
            del: '/api/diskhealth/general/del_disk/',
            toggle: '/api/diskhealth/general/toggle_disk/'
        });

        /*
         * The disk dialog offers the detected disks in a dropdown that fills the device field. The field stays
         * editable for a disk that is not attached right now. Core fills the field after the dialog opens, so the
         * dropdown is built on every "shown" event and only sets the value when the user picks something.
         */
        $(document).on('shown.bs.modal', '.modal', function() {
            const $device = $('#disk\\.device', this);
            if ($device.length === 0) {
                return;
            }
            $('#detectedDisksBox', this).remove();
            const $picker = $('<select id="detectedDisks" class="selectpicker" data-width="346px" data-live-search="true"></select>');
            $device.after($('<div id="detectedDisksBox" style="margin-top: 5px;"></div>').append($picker));
            detectedDisks(function(disks) {
                $picker.append($('<option value=""></option>').text("{{ lang._('Select a detected disk') }}"));
                disks.forEach(function(name) {
                    $picker.append($('<option></option>').val(name).text(name));
                });
                $picker.val(disks.includes($device.val()) ? $device.val() : '');
                $picker.selectpicker('refresh');
                $picker.on('changed.bs.select', function() {
                    if ($picker.val() !== '') {
                        $device.val($picker.val());
                    }
                });
            });
        });

        $("#reconfigureAct").SimpleActionButton();

        $("#saveAct").click(function() {
            saveFormToEndpoint("/api/diskhealth/general/set", 'frm_general_settings', function() {
                /* a changed unit converts the per-disk limits on the server */
                savedUnit = $('#general\\.temp_unit').val();
                lockDisksOnUnitChange();
                grid().bootgrid('reload');
                $("#saveAct_progress").addClass("fa fa-spinner fa-pulse");
                ajaxCall("/api/diskhealth/service/reconfigure", {}, function() {
                    $("#saveAct_progress").removeClass("fa fa-spinner fa-pulse");
                });
            });
        });
    });
</script>

<div class="content-box" style="padding-bottom: 1.5em;">
    {{ partial("layout_partials/base_form", ['fields': generalForm, 'id': 'frm_general_settings']) }}
    <div class="col-md-12">
        <hr />
        <button class="btn btn-primary" id="saveAct" type="button"><b>{{ lang._('Save') }}</b> <i id="saveAct_progress"></i></button>
    </div>
</div>

<div class="content-box" style="padding-bottom: 1.5em;">
    <div class="col-md-12">
        <h2>{{ lang._('Monitored disks') }}</h2>
        <p>{{ lang._('Only the listed and enabled disks are monitored, collected and shown on the dashboard widget; with none listed nothing is monitored. Use the search button below the table to add all detected disks. A disk may have its own temperature limits, otherwise the global ones apply.') }}</p>
    </div>
    <div class="col-md-12">
        <div id="diskUnitNotice" class="alert alert-warning" style="display: none;">{{ lang._('Save the temperature unit change before editing the disks.') }}</div>
    </div>
    <div id="diskGridBox">
        {{ partial('layout_partials/base_bootgrid_table', formGridDisk) }}
    </div>
</div>

{{ partial('layout_partials/base_apply_button', {'data_endpoint': '/api/diskhealth/service/reconfigure'}) }}

{{ partial('layout_partials/base_dialog', ['fields': formDialogDisk, 'id': formGridDisk['edit_dialog_id'], 'label': lang._('Edit disk')]) }}
