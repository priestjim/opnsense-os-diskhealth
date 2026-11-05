# os-diskhealth – SMART disk health for OPNsense

[![CI](https://github.com/priestjim/opnsense-os-diskhealth/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/priestjim/opnsense-os-diskhealth/actions/workflows/ci.yml)
[![Release](https://github.com/priestjim/opnsense-os-diskhealth/actions/workflows/release.yml/badge.svg)](https://github.com/priestjim/opnsense-os-diskhealth/actions/workflows/release.yml)
[![License: BSD-2-Clause](https://img.shields.io/badge/license-BSD--2--Clause-blue.svg)](LICENSE)

A dashboard widget and system alert for the health of your firewall's drives (NVMe, SATA SSD, HDD). Built for OPNsense 26.7 and later.

- **Dashboard widget** with, per disk: overall SMART verdict, a color coded **temperature bar**, wear, total data written, bad blocks, error counters, power-on time and model details.
- **The widget turns red** when a disk reports errors (amber for warnings).
- **System alert**: a failing disk, or one that gets too hot, shows up in the OPNsense status bell and is written to syslog.
- **Configurable**: on the *Services ▸ Disk Health* page: collection interval (1–30 minutes), which disks to monitor, temperature unit (°C/°F), warning/critical temperature limits (default 60 °C / 80 °C, optionally per disk) and whether warnings and temperature raise an alert. On each widget: which of the monitored disks and which health details to show.
- **Gentle**: SMART data is collected by one background job (every 5 minutes by default); spun-down HDDs are not woken up; page loads never run `smartctl`.

## Install

This plugin is not in the official OPNsense plugin list, so it is installed from its own signed package repository. Run these commands once on the firewall as root (SSH, or *System ▸ Firmware ▸ Console*):

```sh
mkdir -p /usr/local/etc/pkg/keys
fetch -o /usr/local/etc/pkg/keys/diskhealth.pub \
    https://priestjim.github.io/opnsense-os-diskhealth/repo.pub
fetch -o /usr/local/etc/pkg/repos/diskhealth.conf \
    https://priestjim.github.io/opnsense-os-diskhealth/diskhealth.conf
pkg update
```

Then install **os-diskhealth** from *System ▸ Firmware ▸ Plugins* (reload the page if it is not listed), or from the shell with `pkg install os-diskhealth`. Updates are offered with the normal firmware updates.

`os-smart` (which brings in `smartmontools`) is a dependency: it is installed automatically from the OPNsense repository. If it cannot be installed, the installation fails and nothing is changed.

The package registers its cron job but monitors nothing yet: open *Services ▸ Disk Health*, press *Add detected disks* and **Apply**. Then open the dashboard, click **Edit ▸ Add widget ▸ Disk Health** (hard-reload the page first if the widget is not listed).

Later updates arrive through the normal `pkg upgrade` / *System ▸ Firmware ▸ Updates*.

## Uninstall

```sh
pkg delete os-diskhealth
```

This removes the widget, the collector, the alert and its cron job, and the cached data. Dashboards that contained the widget drop it automatically. `os-smart` is left installed (remove it separately with `pkg delete os-smart` if you do not need it). To also stop using the repository, delete `/usr/local/etc/pkg/repos/diskhealth.conf`.

## Settings

### Services ▸ Disk Health (firewall-wide)

| Setting | Default | Notes |
|---|---|---|
| Enabled | on | Turns the background collection, the widget data and the alert on or off |
| Collection interval | 5 minutes | 1 to 30 minutes. Values that divide 60 (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30) run at an even pace. Sleeping hard disks are never woken |
| Alert on warnings | on | Raise the status-bell alert for early warning signs too. When off, only failing (critical) disks and critical temperatures raise an alert. The widget always shows both |
| Alert on temperature | on | Raise the status-bell alert and a syslog message when a monitored disk reaches its warning (only if *Alert on warnings* is on) or critical temperature |
| Temperature unit | Celsius | Used by every Disk Health widget. Switching the unit converts the limits (global and per disk) for you |
| Warning temperature | 60 °C / 140 °F | Bar turns amber, warning alert, from this value |
| Critical temperature | 80 °C / 176 °F | Bar turns red, critical alert, from this value; must be higher than the warning temperature |

Saving applies the settings immediately (the cron job is re-registered and a collection is started).

**Monitored disks** (same page): *Add detected disks* lists every disk the system finds; the add/edit dialog also has a dropdown of the detected disks that fills the device field (the field stays editable for a disk that is not attached); edit an entry to give it its own warning/critical temperature (empty = use the global limit) or untick *Monitor* to skip it. With nothing listed, or with every listed disk switched off, no disk is monitored and the widget says so. After changing the list press **Apply**.

- **Only listed and enabled disks** are monitored. A fresh install monitors nothing until you add disks (press *Add detected disks* or add them one by one); a newly attached drive has to be added as well.
- Disks that are not monitored are never queried by `smartctl`, they do not appear on the widget and never alert. That also helps with drives behind controllers or USB bridges that react badly to SMART queries.
- Disks are matched by device name (`ada0`, `nvme0`...). If a name changes, for example after replacing a drive, select the disk again.
- A per-disk limit that is not higher than the other limit of the same disk (for example a warning above the global critical temperature) is ignored and the global limits are used.
- Changing the temperature unit converts every per-disk limit too. If a converted limit would be out of range or no longer lower than its critical limit (rounding), the save is refused and the unit field lists the disks to adjust first.
- A sleeping hard disk is not judged on its last known temperature: it raises no temperature alert until it is read again.

### Per widget

Click the pencil on the widget (Edit mode):

| Option | Default | Notes |
|---|---|---|
| Disks to show | all | Pick any subset of the **monitored** disks; a disk you hide never affects the widget's color. If a saved selection no longer matches any monitored disk the widget shows all of them |
| Health information to show | health, temperature, wear, written, bad blocks, power-on | Also available: error counters, model details (serial, firmware, capacity) |

You can add several Disk Health widgets with different disks and details, for example a compact one next to a full one.

## How health is decided

Temperature has its own verdict (see *Alerts*) and **never** changes a disk's health verdict.

| Level | Triggers |
|---|---|
| Critical (widget red, status bell error) | SMART overall check failed · NVMe critical warning · a SMART attribute failing now · endurance used ≥ 100% · NVMe spare at or below threshold |
| Warning (widget amber, status bell warning) | Reallocated / pending / uncorrectable sectors · NVMe media errors · SCSI grown defects · interface CRC errors · endurance used ≥ 90% · last self-test failed · an attribute failed in the past |
| Unknown (not colored, no alert) | The device does not support SMART (e.g. virtual disks) or `smartctl` could not read it |

"Total written" uses, in order: NVMe data units, the ATA device statistics log (`Logical Sectors Written`), then vendor attributes (`Total_LBAs_Written`, `Host_Writes_*`, `Lifetime_Writes_GiB`). Vendors use different units for the attributes; values a drive does not report show as "—".

## Alerts

When a disk becomes `critical` or `warning`, or (with *Alert on temperature*) reaches its warning or critical temperature, the plugin:

- shows it in the **status bell** in the page header (error for critical, warning otherwise) with the disk, model and reasons or temperature, and
- logs one line to **syslog** (`diskhealth`, facility `daemon`) on every change for the worse and on recovery, for health and for temperature separately. Forward these with *System ▸ Settings ▸ Logging* or alert on them with the Monit plugin.

Alerts clear on their own once the disk is healthy again, or if the collector stops updating for three intervals (at least 15 minutes), so a dead cron job cannot leave a stale alert. Choose whether warnings alert on the settings page.

## How it works

```
settings ─► /usr/local/etc/diskhealth.conf ──┐
cron (interval) ─► configd ──► collect.py ◄──┘──► smartctl -x --json (per monitored disk)
                              │
                              ▼
                  /var/run/diskhealth/status.json   (atomic, world-readable)
                      │                    │
                      ▼                    ▼
        /api/diskhealth/service/status   DiskHealthStatus.php (status bell)
                      │
                      ▼
               Disk Health widget
```

All health and temperature logic is in one place (`smartnorm.py` and `collect.py`), so the widget and the alert always agree.

## Troubleshooting

- **Widget says "Collecting SMART data"** – the first collection runs right after install; wait a minute or run `configctl diskhealth collect`.
- **A disk is missing** – with monitored disks configured, only listed and enabled disks are shown; add it under *Services ▸ Disk Health ▸ Monitored disks*.
- **No disks listed** – check `smartctl --scan` and `smartctl -x /dev/<disk>` as root. Disks behind some RAID controllers need a specific smartctl device type.
- **A disk shows "Unknown"** – the message under the disk is what `smartctl` reported (e.g. virtual disks have no SMART).
- **Look at the raw data** – `configctl diskhealth collect; cat /var/run/diskhealth/status.json`
- **Widget says monitoring is disabled** – enable it under *Services ▸ Disk Health*.
- **Widget missing from the list** – hard-reload the dashboard; check that `/usr/local/opnsense/www/js/widgets/Metadata/DiskHealth.xml` exists and the user has the *Dashboard: Disk Health widget* privilege (the settings page needs *Services: Disk Health*).

## Contributing

Bug reports, drive captures and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Maintainers: [docs/RELEASING.md](docs/RELEASING.md).

```sh
npm test    # widget (node) and collector (python) unit tests, no dependencies
```

## License

BSD 2-Clause, see [LICENSE](LICENSE). The package layout follows the [OPNsense plugins](https://github.com/opnsense/plugins) conventions so it can be proposed there.
