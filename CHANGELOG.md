# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0]

### Added
- Disk Health dashboard widget: overall SMART verdict, temperature bar, wear, total data written, bad blocks, error counters, power-on time and model details for NVMe, SATA SSD and HDD.
- Services ▸ Disk Health settings page: enable/disable, collection interval (1-30 minutes, default 5), alert on warnings, alert on temperature, temperature unit (°C/°F), global warning/critical temperature limits (default 60/80 °C) and the list of monitored disks with optional per-disk limits.
- Only listed and enabled disks are monitored and queried; a fresh install monitors nothing and the widget says "No disks are being monitored" until disks are added. The *Add detected disks* button adds every detected disk, and the disk dialog has a dropdown of the detected disks. The widget offers the monitored disks, and which health details to show. Changes to the list apply to the widget and the status bell right away, without waiting for the next collection.
- Widget turns red when a disk reports errors (amber for warnings). Temperature is colored separately and never changes the health verdict.
- System status (header bell) alert and syslog messages for failing and degrading disks, and for disks that reach their warning or critical temperature (sleeping disks are not judged on their last known temperature).
- Background collector (every 5 minutes by default) that never wakes spun-down disks and publishes an atomic cache.
- Packaged as `os-diskhealth` with a dependency on `os-smart`; registers itself with System ▸ Firmware ▸ Plugins on install and unregisters on removal; installable from a signed pkg repository (trusted with its public key).
