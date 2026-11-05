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

import {test} from 'node:test';
import assert from 'node:assert/strict';

/* The dashboard provides BaseWidget and jQuery as globals; stub the bits we use. */
const dom = {html: null, css: []};
globalThis.$ = () => ({
    html: (h) => { dom.html = h; },
    closest: () => ({css: (c) => { dom.css.push(c); }}),
});
globalThis.BaseWidget = class {
    constructor(config) { this.config = config; this.translations = {}; this.id = 'w1'; }
    /* same merge semantics as core BaseWidget.getWidgetConfig (empty/missing -> default) */
    async getWidgetConfig() {
        const options = await this.getWidgetOptions();
        const saved = this.config?.widget ?? {};
        return Object.fromEntries(Object.entries(options).map(([k, o]) => {
            const v = saved[k];
            const usable = v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0) &&
                !(o.type === 'select_multiple' && !v.some((x) => o.options.map((p) => p.value).includes(x)));
            return [k, usable ? v : o.default];
        }));
    }
};

const mod = await import('../src/opnsense/www/js/widgets/DiskHealth.js');
const {
    formatTemp, formatBytes, formatHours, parseLimits, diskLimits, tempLevel, worstStatus, temperatureBar,
    renderDisk, esc, DEFAULT_FIELDS, FIELD_KEYS,
} = mod;
const Widget = mod.default;

/* shape produced by scripts/OPNsense/DiskHealth/smartnorm.py */
const rec = (over = {}) => ({
    device: 'nvme0', model: 'TEAM TM8FPW001T', serial: 'S1', firmware: 'F1', capacity_bytes: 1024209543168,
    protocol: 'NVMe', media: 'nvme', smart_passed: true, status: 'ok', issues: [],
    temperature_c: 40, power_on_hours: 15986, power_cycles: 254, bytes_written: 12820885 * 512000,
    percent_used: 1, spare_percent: 100, spare_threshold: 10,
    reallocated: null, pending: null, uncorrectable: null, media_errors: 0, grown_defects: null, bad_blocks: 0,
    crc_errors: null, error_log_entries: 0, unsafe_shutdowns: 35, critical_warning: 0, standby: false, error: null,
    ...over,
});
const LIMITS = {warning: 60, critical: 80};

test('formatters', () => {
    assert.equal(formatTemp(40, 'C'), '40 °C');
    assert.equal(formatTemp(40, 'F'), '104 °F');
    assert.equal(formatTemp(null, 'F'), '—');
    assert.equal(formatBytes(null), '—');
    assert.equal(formatBytes(12820885 * 512000), '6.6 TB');
    assert.equal(formatHours(30), '30 h');
    assert.equal(formatHours(15986), '15,986 h (1.8 y)');
});

test('temperature limits default to 60/80 C and reject unusable input', () => {
    assert.deepEqual(parseLimits('60', '80'), LIMITS);
    assert.deepEqual(parseLimits('45', '55.5'), {warning: 45, critical: 55.5});
    for (const unit of ['C', 'F']) {
        for (const [w, c] of [['', ''], ['abc', '80'], ['80', '60'], ['60', '60'], ['-5', '80'], [undefined, undefined]]) {
            // 80/60 etc. are only "unusable" in C; in F they are below freezing or inverted too
            assert.deepEqual(parseLimits(w, c, unit), LIMITS, `${unit} ${w}/${c}`);
        }
    }
});

test('limits entered in Fahrenheit are converted to Celsius', () => {
    assert.deepEqual(parseLimits('140', '176', 'F'), LIMITS);
    const { warning, critical } = parseLimits('113', '131', 'F');
    assert.equal(Math.round(warning), 45);
    assert.equal(Math.round(critical), 55);
    assert.deepEqual(parseLimits('176', '140', 'F'), LIMITS); /* inverted */
    assert.deepEqual(parseLimits('20', '140', 'F'), LIMITS); /* 20 F is below zero C */
});

test('temperature level is colour coded independent of disk health', () => {
    assert.equal(tempLevel(59, LIMITS), 'ok');
    assert.equal(tempLevel(60, LIMITS), 'warning');
    assert.equal(tempLevel(79, LIMITS), 'warning');
    assert.equal(tempLevel(80, LIMITS), 'critical');
    assert.equal(tempLevel(null, LIMITS), 'none');
});

test('temperature bar: Thermal-Sensors palette, unit in label, 0-100 C fill', () => {
    const ok = temperatureBar(40, 'C', LIMITS);
    assert.match(ok, /progress-bar/);
    assert.match(ok, /#28a745/);
    assert.match(ok, /width: 40%/);
    assert.match(temperatureBar(65, 'F', LIMITS), /#ffc107[\s\S]*149 °F/);
    assert.match(temperatureBar(85, 'C', LIMITS), /#dc3545/);
    assert.match(temperatureBar(250, 'C', LIMITS), /width: 100%/);
    assert.equal(temperatureBar(null, 'C', LIMITS), '—');
});

test('worst status ignores unknown disks', () => {
    assert.equal(worstStatus([rec(), rec({status: 'unknown'})]), 'ok');
    assert.equal(worstStatus([rec(), rec({status: 'warning'})]), 'warning');
    assert.equal(worstStatus([rec({status: 'warning'}), rec({status: 'critical'})]), 'critical');
    assert.equal(worstStatus([]), 'ok');
});

test('renderDisk honours selected fields', () => {
    const html = renderDisk(rec(), ['temperature', 'written'], {unit: 'F', limits: LIMITS});
    assert.match(html, /104 °F/);
    assert.match(html, /6\.6 TB/);
    assert.doesNotMatch(html, /Bad blocks/);
    assert.doesNotMatch(html, /Healthy/); /* health not selected -> no badge */
    const all = renderDisk(rec(), FIELD_KEYS, {unit: 'C', limits: LIMITS});
    for (const label of ['Healthy', 'Bad blocks', 'Error counters', 'Serial', 'S1', 'Power-on time']) {
        assert.ok(all.includes(label), label);
    }
});

test('renderDisk shows issues and errors; escapes device supplied strings', () => {
    const bad = renderDisk(rec({status: 'critical', issues: ['SMART overall health check FAILED']}), DEFAULT_FIELDS, {limits: LIMITS});
    assert.match(bad, /Critical/);
    assert.match(bad, /text-danger[^>]*>SMART overall health check FAILED/);
    const unavailable = renderDisk(rec({status: 'unknown', error: 'SMART not available on this device'}), DEFAULT_FIELDS, {limits: LIMITS});
    assert.match(unavailable, /SMART not available/);
    const evil = renderDisk(rec({model: '<img src=x onerror=alert(1)>'}), DEFAULT_FIELDS, {limits: LIMITS});
    assert.ok(!evil.includes('<img'));
    assert.equal(esc('<&>"\''), '&lt;&amp;&gt;&quot;&#39;');
});

test('standby disks are labelled as showing last known values', () => {
    assert.match(renderDisk(rec({standby: true}), DEFAULT_FIELDS, {limits: LIMITS}), /standby/);
});

function makeWidget(saved, payload) {
    const w = new Widget({widget: saved});
    w.calls = 0;
    w.ajaxCall = async () => { w.calls++; if (payload instanceof Error) throw payload; return payload; };
    dom.html = null;
    dom.css = [];
    return w;
}

const SETTINGS = {unit: 'C', warning_temp: 60, critical_temp: 80};
const PAYLOAD = (settings = SETTINGS) => ({
    enabled: true, settings,
    generated: Math.floor(Date.now() / 1000), stale: false,
    disks: [rec(), rec({device: 'ada0', model: 'WDC WD40EFRX', temperature_c: 52, media: 'hdd'})],
});

test('widget: defaults show all disks in Celsius with default limits', async () => {
    const w = makeWidget({}, PAYLOAD());
    await w.onWidgetTick();
    assert.match(dom.html, /nvme0/);
    assert.match(dom.html, /ada0/);
    assert.match(dom.html, /40 °C/);
    assert.match(dom.html, /Updated/);
    assert.deepEqual(dom.css.at(-1), {'background-color': '', 'box-shadow': ''}); /* healthy: tint cleared */
});

test('widget: only the selected disks are shown', async () => {
    const w = makeWidget({disks: ['ada0']}, PAYLOAD());
    await w.onWidgetTick();
    assert.match(dom.html, /ada0/);
    assert.doesNotMatch(dom.html, /nvme0/);
});

test('widget: firewall-wide unit and limits come from the API settings', async () => {
    /* 95 F = 35 C, 122 F = 50 C */
    const w = makeWidget({}, PAYLOAD({unit: 'F', warning_temp: 95, critical_temp: 122}));
    await w.onWidgetTick();
    assert.match(dom.html, /#ffc107[\s\S]*104 °F/); /* nvme0 at 40 C is now "warning" */
    assert.match(dom.html, /#dc3545[\s\S]*126 °F/); /* ada0 at 52 C is now "critical" */

    /* a settings change arrives with the next poll and is applied from the response */
    w.ajaxCall = async () => PAYLOAD({unit: 'C', warning_temp: 60, critical_temp: 80});
    await w.onWidgetTick();
    assert.match(dom.html, /40 °C/);
    assert.match(dom.html, /#28a745/);
});

test('widget: old per-widget unit/limit options are ignored', async () => {
    const w = makeWidget({unit: 'F', warning_temp: '1', critical_temp: '2'}, PAYLOAD());
    await w.onWidgetTick();
    assert.match(dom.html, /40 °C/);
    assert.match(dom.html, /#28a745[\s\S]*40 °C/);
});

test('widget: monitoring disabled in the settings', async () => {
    const w = makeWidget({}, {enabled: false, settings: SETTINGS, generated: null, disks: []});
    await w.onWidgetTick();
    assert.match(dom.html, /disabled/);
    assert.match(dom.html, /Services ▸ Disk Health/);
    assert.deepEqual(dom.css.at(-1), {'background-color': '', 'box-shadow': ''});
});

test('widget: every listed disk is switched off in the settings', async () => {
    const w = makeWidget({}, {enabled: true, monitored: false, settings: SETTINGS, generated: null, disks: []});
    await w.onWidgetTick();
    assert.match(dom.html, /No disks are being monitored/);
    assert.match(dom.html, /Services ▸ Disk Health/);
    assert.deepEqual(dom.css.at(-1), {'background-color': '', 'box-shadow': ''});
});

test('widget: unusable settings fall back to 60/80 C', async () => {
    const w = makeWidget({}, PAYLOAD({unit: 'C', warning_temp: 90, critical_temp: 70}));
    await w.onWidgetTick();
    assert.match(dom.html, /#28a745[\s\S]*40 °C/); /* 40 C is "ok" under the defaults */
    const missing = makeWidget({}, {enabled: true, generated: 1, disks: [rec()]}); /* no settings at all */
    await missing.onWidgetTick();
    assert.match(dom.html, /40 °C/);
});

test('widget turns red on a critical disk, amber on a warning disk, and ignores unselected disks', async () => {
    const payload = PAYLOAD();
    payload.disks[1] = rec({device: 'ada0', status: 'critical', issues: ['SMART overall health check FAILED']});
    let w = makeWidget({}, payload);
    await w.onWidgetTick();
    assert.match(dom.css.at(-1)['background-color'], /220, 53, 69/);

    w = makeWidget({disks: ['nvme0']}, payload); /* failing disk hidden -> widget stays normal */
    await w.onWidgetTick();
    assert.equal(dom.css.at(-1)['background-color'], '');

    payload.disks[1] = rec({device: 'ada0', status: 'warning', issues: ['4 reallocated sectors']});
    w = makeWidget({}, payload);
    await w.onWidgetTick();
    assert.match(dom.css.at(-1)['background-color'], /255, 193, 7/);
});

test('widget: high temperature alone does not turn the widget red', async () => {
    const payload = PAYLOAD();
    payload.disks[0] = rec({temperature_c: 95}); /* status stays ok: the bar is red, the widget is not */
    const w = makeWidget({}, payload);
    await w.onWidgetTick();
    assert.match(dom.html, /#dc3545/);
    assert.equal(dom.css.at(-1)['background-color'], '');
});

test('widget: disk options list model names, defaults select everything', async () => {
    const w = makeWidget({}, PAYLOAD());
    const options = await w.getWidgetOptions();
    assert.deepEqual(options.disks.default, ['nvme0', 'ada0']);
    assert.equal(options.disks.options[1].label, 'ada0 (WDC WD40EFRX)');
    /* presentation only; unit and limits are firewall-wide settings */
    assert.deepEqual(Object.keys(options).sort(), ['disks', 'fields']);
});

test('widget: pending, stale and missing-API states', async () => {
    let w = makeWidget({}, {generated: null, disks: [], pending: true});
    await w.onWidgetTick();
    assert.match(dom.html, /Collecting SMART data/);

    const stale = PAYLOAD();
    stale.stale = true;
    w = makeWidget({}, stale);
    await w.onWidgetTick();
    assert.match(dom.html, /text-warning[^>]*>Data is stale/);

    const missing = Object.assign(new Error('x'), {xhr: {status: 404}});
    w = makeWidget({}, missing);
    await w.onWidgetTick();
    assert.match(dom.html, /API not found/);
});

test('widget keeps showing the last data if a refresh fails', async () => {
    const w = makeWidget({}, PAYLOAD());
    await w.onWidgetTick();
    w.ajaxCall = async () => { throw new Error('network'); };
    await w.onWidgetTick();
    assert.match(dom.html, /nvme0/);
});

test('widget: Fahrenheit with the default limits behaves like 60/80 C', async () => {
    const payload = PAYLOAD({unit: 'F', warning_temp: 140, critical_temp: 176});
    payload.disks[1] = rec({device: 'ada0', temperature_c: 65}); /* 149 F: above 140 F = 60 C */
    const w = makeWidget({}, payload);
    await w.onWidgetTick();
    assert.match(dom.html, /#ffc107[\s\S]*149 °F/);
    assert.match(dom.html, /#28a745[\s\S]*104 °F/);
});

test('per-disk limits from the collector win over the firewall-wide ones', () => {
    assert.deepEqual(diskLimits({temp_warning_c: 40, temp_critical_c: 45}, LIMITS), {warning: 40, critical: 45});
    assert.deepEqual(diskLimits({temp_warning_c: null, temp_critical_c: 45}, LIMITS), LIMITS);
    assert.deepEqual(diskLimits({temp_warning_c: 50, temp_critical_c: 40}, LIMITS), LIMITS); /* inverted */
    assert.deepEqual(diskLimits({}, LIMITS), LIMITS); /* cache written by an older collector */

    const hot = renderDisk(rec({temperature_c: 42, temp_warning_c: 40, temp_critical_c: 45}), ['temperature'], {unit: 'C', limits: LIMITS});
    assert.match(hot, /#ffc107/); /* 42 C is fine for the global 60/80 but amber for this disk */
});

test('widget: a saved selection of disks that are no longer monitored does not leave the widget empty', async () => {
    const w = makeWidget({disks: ['sda9']}, PAYLOAD());
    await w.onWidgetTick();
    assert.match(dom.html, /nvme0/);
    assert.match(dom.html, /ada0/);
});
