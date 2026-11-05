# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.2]

### Fixed
- The *Add detected disks* button added the disks but the table on the settings page only showed them after a page refresh (the same stale reference also affected the reload after saving).

## [1.0.1]

### Changed
- Easier installation: the release now publishes a ready-made repository definition (`diskhealth.conf`) next to the signing key (`repo.pub`). Installing is two `fetch` commands and `pkg update`, after which the plugin can be installed from System ▸ Firmware ▸ Plugins (see the README).

### Fixed
- A disk that could not be read for a moment (health status "unknown") was logged as "recovered" and, when it came back still failing, announced a second time. The last real health status is now kept across failed reads.
- A hot disk that went to sleep and woke up still hot was announced again, and one that woke up cool never got its "recovered" line. The last temperature status is now kept across standby.
- The cache directory could be created unreadable for the web UI under a strict umask, which left the widget on "Collecting" and the status bell silent.
- The disk dialog's list of detected disks stayed empty for the rest of the page visit after one failed scan.
- No device scan is run on every collection any more while no disk is monitored.
- The README no longer suggests data appears by itself after installation (disks have to be added first).

## [1.0.0]

### Added
- Disk Health dashboard widget: overall SMART verdict, temperature bar, wear, total data written, bad blocks, error counters, power-on time and model details for NVMe, SATA SSD and HDD.
- Services ▸ Disk Health settings page: enable/disable, collection interval (1-30 minutes, default 5), alert on warnings, alert on temperature, temperature unit (°C/°F), global warning/critical temperature limits (default 60/80 °C) and the list of monitored disks with optional per-disk limits.
- Only listed and enabled disks are monitored and queried; a fresh install monitors nothing and the widget says "No disks are being monitored" until disks are added. The *Add detected disks* button adds every detected disk, and the disk dialog has a dropdown of the detected disks. The widget offers the monitored disks, and which health details to show. Changes to the list apply to the widget and the status bell right away, without waiting for the next collection.
- Widget turns red when a disk reports errors (amber for warnings). Temperature is colored separately and never changes the health verdict.
- System status (header bell) alert and syslog messages for failing and degrading disks, and for disks that reach their warning or critical temperature (sleeping disks are not judged on their last known temperature).
- Background collector (every 5 minutes by default) that never wakes spun-down disks and publishes an atomic cache.
- Packaged as `os-diskhealth` with a dependency on `os-smart`; registers itself with System ▸ Firmware ▸ Plugins on install and unregisters on removal; installable from a signed pkg repository (trusted with its public key).
