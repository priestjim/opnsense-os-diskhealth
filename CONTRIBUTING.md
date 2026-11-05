# Contributing

Thanks for helping make disk monitoring on OPNsense better. Bug reports, drive captures, translations and code are all welcome.

## Quick start

```sh
git clone https://github.com/priestjim/opnsense-os-diskhealth
cd opnsense-os-diskhealth
npm test        # node (widget) + python (collector); nothing to install
```

Requirements: Node 22+ and Python 3.11+ (OPNsense 26.7 ships 3.13). There are no third-party dependencies; please keep it that way.

## Layout

| Path | What |
|---|---|
| `src/opnsense/scripts/OPNsense/DiskHealth/smartnorm.py` | smartctl JSON → one record + health verdict. The single source of truth for health |
| `src/opnsense/scripts/OPNsense/DiskHealth/collect.py` | Runs smartctl per disk (via configd/cron), writes the cache |
| `src/opnsense/www/js/widgets/DiskHealth.js` | Dashboard widget (rendering only) |
| `src/opnsense/mvc/app/library/OPNsense/System/Status/DiskHealthStatus.php` | System status (bell) alert |
| `src/opnsense/mvc/app/controllers/OPNsense/DiskHealth/Api/` | API: serves the cache (`service/status`), applies settings (`service/reconfigure`), settings get/set (`general`) |
| `src/opnsense/mvc/app/models/OPNsense/DiskHealth/` | Settings model (`General.xml`, incl. the monitored-disks list), menu, ACL; the settings page is `controllers/.../GeneralController.php`, `forms/general.xml`, `forms/dialogDisk.xml`, `views/.../general.volt` |
| `src/opnsense/service/templates/OPNsense/DiskHealth/` | Renders the settings for `collect.py` to `/usr/local/etc/diskhealth.conf` |
| `Makefile`, `pkg-descr`, `+POST_*.post` | OPNsense plugin packaging (same conventions as opnsense/plugins) |
| `tests/` | `diskhealth.test.mjs` (widget), `py/` (collector), `fixtures/` (smartctl captures) |

## Adding support for a drive (the most useful contribution)

1. As root on the firewall: `smartctl -x --json=c /dev/<disk> > capture.json`
2. **Anonymize it** (this repo is public). Replace or remove:
   - serial number (`serial_number`), WWN (`wwn.id`), NVMe EUI-64 (`eui64.ext_id`)
   - timestamps (`local_time`), the `platform_info` / kernel string
   - hostnames, IP addresses, anything else that identifies you or your network
3. Save it as `tests/fixtures/<type>_<vendor>_<model>.json` (trim huge irrelevant sections such as `ata_log_directory`).
4. Add a test in `tests/py/test_smartnorm.py` asserting what you expect to see.
5. If the test fails, fix `smartnorm.py`. smartctl's JSON layout differs between versions, always read both layouts when you know of them.

## Making changes

- **Tests first.** New behavior gets a test; bug fixes get a test that fails before the fix.
- **Health logic belongs in `smartnorm.py`**, never in the widget or the PHP, so the widget and the alert cannot disagree. Temperature must not influence the health `status`; it has its own `temperature_status`, also decided in `collect.py`.
- Missing values are `null`/`None`, never `0`.
- Escape everything that comes from a drive (`esc()` in JS, `clean()` in PHP).
- The status class and API only **read** the cache. Nothing on a page load may run `smartctl`.
- Every source file carries the BSD-2-Clause header (CI checks this).
- New widget option / displayed field: add it to `getWidgetOptions()` or `FIELD_KEYS`, the strings to `Metadata/DiskHealth.xml`, tests, and document it in the README.
- Keep to the style of the surrounding code; the PHP follows OPNsense's PSR-12 style.

## What CI checks

Node tests (22, 24), Python tests (3.13), `php -l`, XML/JSON validity, shell syntax, license headers, and a real package build on FreeBSD 15 (`scripts/build-package.sh`), including a check that `os-smart` is declared as a dependency.

## Trying a change on a firewall

`./install.sh root@<firewall>` copies the working tree onto a **test** firewall without building a package (development only; it is not a supported way to install). Use `pkg` for real installations.

## Pull requests

Keep them focused, describe what changed and why, and mention how you tested it (ideally on which drive and OPNsense version). By contributing you agree that your contribution is licensed under the project's BSD 2-Clause license.

## Reporting issues

Please include the OPNsense version, `pkg info os-diskhealth os-smart`, the disk type/model and the **anonymized** output of `smartctl -x --json=c /dev/<disk>`.

## Security

Please report vulnerabilities privately through GitHub's *Security ▸ Report a vulnerability* instead of a public issue.
