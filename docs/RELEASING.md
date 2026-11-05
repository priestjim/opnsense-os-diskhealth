# Releasing

Releases are built by `.github/workflows/release.yml` when a `v*` tag is pushed. It builds the package on FreeBSD 15, attaches it to a GitHub release and republishes the **pkg repository** (every released version) on GitHub Pages.

## One-time setup

1. **Enable GitHub Pages**: *Settings ▸ Pages ▸ Build and deployment ▸ Source: GitHub Actions*.
2. **Create the repository signing key** (keep the private key out of the repository):

   ```sh
   openssl genrsa -out repo.key 4096
   gh secret set PKG_SIGNING_KEY < repo.key     # or add it under Settings ▸ Secrets and variables ▸ Actions
   ```

   Store `repo.key` somewhere safe (password manager); losing it means users must re-trust a new key. Without the secret the workflow still runs but publishes an **unsigned** repository (users would have to use `signature_type: "none"`), and prints a warning.
3. Optionally protect the `v*` tag pattern and the `github-pages` environment so only maintainers can release.

The workflow publishes, next to the repository, `repo.pub` (the public key) and `diskhealth.conf` (the ready-made pkg repository definition, pointing at the Pages URL of the repository and at the key). Users download both in the README install steps. If the key changes, `repo.pub` changes and users fetch it again.

## Cutting a release

1. Update `PLUGIN_VERSION` (and `PLUGIN_REVISION` for packaging-only changes) in `Makefile`, add the entry to `pkg-descr` and `CHANGELOG.md`.
2. Make sure CI is green on `main` (it already builds the package on FreeBSD).
3. Tag and push:

   ```sh
   git tag v1.0.0
   git push origin v1.0.0
   ```
4. Watch the *Release* workflow. Afterwards verify on a test firewall using the README install steps (`pkg update && pkg install os-diskhealth`, then check the widget, the status bell and `pkg delete os-diskhealth`).

The git tag must match `PLUGIN_VERSION` (`v1.0.0` ⇄ `1.0.0`): the release step attaches `os-diskhealth-<version>.pkg`.

## Rotating the signing key

Generate a new key, replace the `PKG_SIGNING_KEY` secret, cut a release, and tell users to download the new `repo.pub` to `/usr/local/etc/pkg/keys/diskhealth.pub`.

## Proposing the plugin to OPNsense

The source tree is laid out like a plugin in [opnsense/plugins](https://github.com/opnsense/plugins). To propose it upstream, copy the repository content (without `.github`, `tests`, `docs`, `scripts`, `package.json`) to `sysutils/diskhealth/` in a fork and open a pull request. Set `PLUGIN_MAINTAINER` first. Note that upstream may prefer folding the widget into `os-smart`.

## Notes on the build

`scripts/build-package.sh` runs the stock `plugins.mk` build (`make package`) on a plain FreeBSD host. `plugins.mk` queries `pkg` for the version of each dependency, so the script installs an empty stand-in for `os-smart` on the build host only; the real dependency is declared in the package metadata (`PLUGIN_DEPENDS=os-smart`) and resolved by `pkg` on the firewall. `PLUGIN_NO_ABI` makes the package independent of the FreeBSD ABI because it contains only scripts.
