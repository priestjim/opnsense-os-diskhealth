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

/*
 * Disk Health dashboard widget.
 *
 * Displays the records published by the collector (scripts/OPNsense/DiskHealth/collect.py)
 * through /api/diskhealth/service/status. All health logic lives in the collector so the
 * widget and the system alert can never disagree; this file only renders and colours.
 *
 * Pure helpers are named exports so they can be unit tested under node.
 */

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export const DEFAULT_WARNING_TEMP = 60;
export const DEFAULT_CRITICAL_TEMP = 80;
const DEFAULT_LIMITS = {warning: DEFAULT_WARNING_TEMP, critical: DEFAULT_CRITICAL_TEMP};

export function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
}

export function formatTemp(celsius, unit = 'C') {
    const c = num(celsius);
    if (c === null) {
        return '—';
    }
    return unit === 'F' ? `${Math.round(c * 9 / 5 + 32)} °F` : `${Math.round(c)} °C`;
}

/* decimal units, same as BaseWidget._formatBytes */
export function formatBytes(bytes) {
    const b = num(bytes);
    if (b === null) {
        return '—';
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB'];
    const i = b > 0 ? Math.min(units.length - 1, Math.floor(Math.log10(b) / 3)) : 0;
    return `${(b / Math.pow(1000, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatHours(hours) {
    const h = num(hours);
    if (h === null) {
        return '—';
    }
    const base = `${h.toLocaleString('en-US')} h`;
    if (h >= 24 * 365) {
        return `${base} (${(h / 8760).toFixed(1)} y)`;
    }
    return h >= 48 ? `${base} (${Math.floor(h / 24)} d)` : base;
}

/*
 * The limits are entered in the displayed unit and returned in °C. Blank or unusable input
 * (not a number, not above zero, critical not above warning) falls back to the 60/80 °C defaults.
 */
export function parseLimits(warning, critical, unit = 'C') {
    const toCelsius = (v) => (unit === 'F' ? (v - 32) * 5 / 9 : v);
    const w = toCelsius(parseFloat(warning));
    const c = toCelsius(parseFloat(critical));
    if (Number.isFinite(w) && Number.isFinite(c) && w > 0 && c > w) {
        return {warning: w, critical: c};
    }
    return DEFAULT_LIMITS;
}

/* the collector sends each disk's effective limits (its own or the global ones) in °C */
export function diskLimits(rec, fallback) {
    const w = num(rec.temp_warning_c);
    const c = num(rec.temp_critical_c);
    return w !== null && c !== null && w > 0 && c > w ? {warning: w, critical: c} : fallback;
}

export function tempLevel(celsius, limits) {
    const c = num(celsius);
    if (c === null) {
        return 'none';
    }
    if (c >= limits.critical) {
        return 'critical';
    }
    return c >= limits.warning ? 'warning' : 'ok';
}

/* worst health status among the given records; unknown disks never colour the widget */
export function worstStatus(records) {
    if (records.some((r) => r.status === 'critical')) {
        return 'critical';
    }
    return records.some((r) => r.status === 'warning') ? 'warning' : 'ok';
}

/* ---------- rendering ---------- */

export const FIELD_KEYS = [
    'health', 'temperature', 'wear', 'written', 'badblocks', 'errors', 'poweron', 'identity'
];
export const DEFAULT_FIELDS = ['health', 'temperature', 'wear', 'written', 'badblocks', 'poweron'];

const FIELD_LABELS = {
    health: 'Overall health',
    temperature: 'Temperature',
    wear: 'Wear / life used',
    written: 'Total data written',
    badblocks: 'Bad blocks',
    errors: 'Error counters',
    poweron: 'Power-on time',
    identity: 'Model details (serial, firmware, capacity)',
};

const STATUS_BADGE = {
    ok: ['label-success', 'fa-check', 'Healthy'],
    warning: ['label-warning', 'fa-exclamation-triangle', 'Warning'],
    critical: ['label-danger', 'fa-times-circle', 'Critical'],
    unknown: ['label-default', 'fa-question-circle', 'Unknown'],
};

/* same palette as the core Thermal Sensors widget */
const BAR_COLORS = {ok: '#28a745', warning: '#ffc107', critical: '#dc3545'};
const TINTS = {
    critical: {'background-color': 'rgba(220, 53, 69, 0.22)', 'box-shadow': 'inset 0 0 0 2px rgba(220, 53, 69, 0.85)'},
    warning: {'background-color': 'rgba(255, 193, 7, 0.18)', 'box-shadow': 'inset 0 0 0 2px rgba(255, 193, 7, 0.7)'},
};

const defaultT = (key, fallback) => fallback;

function joinParts(parts) {
    const present = parts.filter(([, v]) => v !== null && v !== undefined);
    return present.length
        ? present.map(([label, v]) => `${esc(label)} ${esc(v.toLocaleString('en-US'))}`).join(' · ')
        : '—';
}

/* horizontal bar like the core Thermal Sensors widget; fill is 0-100 °C regardless of unit */
export function temperatureBar(celsius, unit, limits) {
    const level = tempLevel(celsius, limits);
    if (level === 'none') {
        return '—';
    }
    const fill = Math.min(100, Math.max(1, celsius));
    return `<div class="progress" style="height: 18px; margin: 2px 0;" title="${esc(formatTemp(celsius, 'C'))} / ${esc(formatTemp(celsius, 'F'))}">` +
        `<div class="progress-bar diskhealth-temp-${level}" role="progressbar" ` +
        `style="width: ${fill}%; min-width: 4.5em; background-color: ${BAR_COLORS[level]}; ` +
        `color: ${level === 'warning' ? '#212529' : '#fff'}; text-align: left; padding-left: 6px; line-height: 18px;">` +
        `${esc(formatTemp(celsius, unit))}</div></div>`;
}

export function renderDisk(rec, fields, options = {}, t = defaultT) {
    const unit = options.unit ?? 'C';
    const limits = diskLimits(rec, options.limits ?? DEFAULT_LIMITS);
    const rows = [];
    const row = (label, value, cls = '', width = '') =>
        rows.push(`<tr><td class="text-muted">${esc(label)}</td><td class="text-right ${cls}" ${width}>${value}</td></tr>`);
    const has = (f) => fields.includes(f);

    const [badgeCls, icon, badgeText] = STATUS_BADGE[rec.status] ?? STATUS_BADGE.unknown;
    const badge = has('health')
        ? ` <span class="label ${badgeCls} pull-right"><i class="fa ${icon}"></i> ${esc(t(`status_${rec.status}`, badgeText))}</span>`
        : '';
    const title = `<strong>${esc(rec.device)}</strong>` +
        (rec.model ? ` <small class="text-muted">${esc(rec.model)}</small>` : '') +
        (rec.standby ? ` <small class="text-muted">(${esc(t('standby', 'standby, last known values'))})</small>` : '');

    if (rec.error) {
        const unavailable = `<tr><td colspan="2" class="text-muted"><i class="fa fa-info-circle"></i> ${esc(rec.error)}</td></tr>`;
        return `<div class="diskhealth-disk"><div>${title}${badge}</div>` +
            `<table class="table table-condensed"><tbody>${unavailable}</tbody></table></div>`;
    }

    if (has('temperature')) {
        row(t('f_temperature', FIELD_LABELS.temperature), temperatureBar(rec.temperature_c, unit, limits), '', 'style="width: 60%;"');
    }
    if (has('wear')) {
        let text = rec.percent_used === null ? '—' : `${rec.percent_used}% used`;
        if (rec.spare_percent !== null) {
            text += ` · ${rec.spare_percent}% spare`;
        }
        row(t('f_wear', FIELD_LABELS.wear), esc(text), rec.percent_used >= 90 ? 'text-warning' : '');
    }
    if (has('written')) {
        row(t('f_written', FIELD_LABELS.written), esc(formatBytes(rec.bytes_written)));
    }
    if (has('badblocks')) {
        let text = '—';
        if (rec.bad_blocks !== null) {
            text = `${esc(rec.bad_blocks.toLocaleString('en-US'))} <small class="text-muted">(${joinParts([
                ['realloc', rec.reallocated], ['pending', rec.pending], ['uncorr', rec.uncorrectable],
                ['media err', rec.media_errors], ['grown', rec.grown_defects],
            ])})</small>`;
        }
        row(t('f_badblocks', FIELD_LABELS.badblocks), text, rec.bad_blocks > 0 ? 'text-danger' : '');
    }
    if (has('errors')) {
        row(t('f_errors', FIELD_LABELS.errors), joinParts([
            ['CRC', rec.crc_errors], ['log', rec.error_log_entries], ['unsafe shutdowns', rec.unsafe_shutdowns],
        ]), rec.crc_errors > 0 ? 'text-warning' : '');
    }
    if (has('poweron')) {
        const cycles = rec.power_cycles === null ? '' : ` · ${rec.power_cycles.toLocaleString('en-US')} cycles`;
        row(t('f_poweron', FIELD_LABELS.poweron), esc(formatHours(rec.power_on_hours) + cycles));
    }
    if (has('identity')) {
        row(t('serial', 'Serial'), esc(rec.serial ?? '—'));
        row(t('firmware', 'Firmware'), esc(rec.firmware ?? '—'));
        row(t('capacity', 'Capacity'), esc(formatBytes(rec.capacity_bytes)));
    }

    const issues = has('health') && rec.issues.length
        ? `<div class="small ${rec.status === 'critical' ? 'text-danger' : 'text-warning'}">${rec.issues.map(esc).join('; ')}</div>`
        : '';
    return `<div class="diskhealth-disk" style="margin-bottom: 8px;"><div>${title}${badge}</div>${issues}` +
        (rows.length ? `<table class="table table-condensed" style="margin-bottom: 0;"><tbody>${rows.join('')}</tbody></table>` : '') +
        '</div>';
}

/* ---------- widget ---------- */

const API_STATUS = '/api/diskhealth/service/status';

export default class DiskHealth extends BaseWidget {
    constructor(config) {
        super(config);
        /* cheap: the API only reads a cache that cron refreshes every few minutes */
        this.tickTimeout = 60;
        this.configurable = true;
        this.data = null;
        this.failure = null;
    }

    getMarkup() {
        return $(`
            <div id="${this.id}-diskhealth" class="diskhealth-widget" style="padding: 0 10px;">
                <i class="fa fa-spinner fa-spin"></i>
            </div>
        `);
    }

    _t(key, fallback) {
        return this.translations?.[key] ?? fallback;
    }

    async getWidgetOptions() {
        if (this.data === null) {
            try {
                this.data = await this.ajaxCall(API_STATUS);
            } catch (e) {
                /* options dialog still opens; the disk list is simply empty */
            }
        }
        const disks = this.data?.disks ?? [];
        const names = disks.map((d) => d.device);
        const t = (k, f) => this._t(k, f);
        /* only the disks monitored under Services > Disk Health are collected, so only those are offered */
        return {
            disks: {
                title: t('disks', 'Disks to show'),
                type: 'select_multiple',
                options: disks.map((d) => ({value: d.device, label: d.model ? `${d.device} (${d.model})` : d.device})),
                default: names,
            },
            fields: {
                title: t('fields', 'Health information to show'),
                type: 'select_multiple',
                options: FIELD_KEYS.map((k) => ({value: k, label: t(`f_${k}`, FIELD_LABELS[k])})),
                default: DEFAULT_FIELDS,
            },
        };
    }

    async onWidgetTick() {
        try {
            this.data = await this.ajaxCall(API_STATUS);
            this.failure = null;
        } catch (e) {
            this.failure = e;
        }
        this._draw(await this.getWidgetConfig());
    }

    async onWidgetOptionsChanged() {
        /* everything is rendered from the cached response, no new request needed */
        this._draw(await this.getWidgetConfig());
    }

    _tint($content, status) {
        $content.css({'background-color': '', 'box-shadow': ''});
        if (TINTS[status]) {
            $content.css(TINTS[status]);
        }
    }

    _draw(config) {
        const $body = $(`#${this.id}-diskhealth`);
        const t = (k, f) => this._t(k, f);
        let html;
        let status = 'ok';
        const notice = (cls, icon, text) =>
            `<div class="${cls}" style="margin: 1em 0;">${icon ? `<i class="fa ${icon}"></i> ` : ''}${esc(text)}</div>`;

        if (this.failure && !this.data) {
            const missing = this.failure.xhr?.status === 404;
            html = notice('text-warning', 'fa-exclamation-triangle', missing
                ? t('no_api', 'Disk Health API not found. Reinstall the os-diskhealth plugin.')
                : t('unavailable', 'Unable to retrieve SMART data.'));
        } else if (this.data?.enabled === false) {
            html = notice('text-muted', 'fa-pause-circle',
                t('disabled', 'Disk health monitoring is disabled. Enable it under Services ▸ Disk Health.'));
        } else if (this.data?.monitored === false) {
            html = notice('text-muted', 'fa-info-circle',
                t('none_monitored', 'No disks are being monitored. Add or enable disks under Services ▸ Disk Health.'));
        } else {
            const all = this.data?.disks ?? [];
            let shown = all.filter((d) => config.disks.includes(d.device));
            if (!shown.length) {
                /* a saved selection naming only disks that are no longer monitored must not leave the widget empty */
                shown = all;
            }
            const settings = this.data?.settings ?? {};
            const unit = settings.unit === 'F' ? 'F' : 'C';
            const options = {unit, limits: parseLimits(settings.warning_temp, settings.critical_temp, unit)};
            status = worstStatus(shown);

            if (shown.length) {
                html = shown.map((d) => renderDisk(d, config.fields, options, t)).join('');
            } else if (this.data?.pending) {
                html = notice('text-muted', 'fa-spinner fa-spin', t('collecting', 'Collecting SMART data, this can take a minute.'));
            } else {
                html = notice('text-muted', '', t('no_disks', 'No disks found or selected.'));
            }

            if (this.data?.generated) {
                const when = new Date(this.data.generated * 1000).toLocaleTimeString();
                html += `<div class="small ${this.data.stale ? 'text-warning' : 'text-muted'}" style="margin-top: 4px;">` +
                    `${esc(this.data.stale ? t('stale', 'Data is stale, last update') : t('updated', 'Updated'))} ${esc(when)}</div>`;
            }
        }

        $body.html(html);
        this._tint($body.closest('.widget-content'), status);
    }
}
