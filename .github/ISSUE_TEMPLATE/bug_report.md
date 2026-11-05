---
name: Bug report
about: Something is wrong with the widget, the alert or the installation
labels: bug
---

**What happened / what did you expect**

**Environment**
- OPNsense version:
- `pkg info os-diskhealth os-smart`:
- Disk type and model (NVMe / SATA SSD / HDD):

**Diagnostics** (as root; please anonymize serial numbers, WWN/EUI-64 and timestamps)
- `smartctl -x --json=c /dev/<disk>`
- `configctl diskhealth collect; cat /var/run/diskhealth/status.json`
- Browser console errors, if the widget does not render
