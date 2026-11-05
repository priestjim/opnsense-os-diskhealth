#!/bin/sh
#
# Copyright (C) 2026 Panagiotis Papadomitsos
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

# Build the os-diskhealth package on a plain FreeBSD host (used by CI).
#
#   scripts/build-package.sh <opnsense-plugins-checkout> <output-dir>
#
# The checkout of https://github.com/opnsense/plugins only has to provide
# Mk/, Templates/ and Scripts/. The plugin Makefile expects to live at
# <plugins>/<category>/<name>, so the sources are staged there first.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
PLUGINS_SRC=$(cd "$1" && pwd)
OUT=$2

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

command -v git > /dev/null && git config --global --add safe.directory '*' || true

# plugins.mk records the dependencies of the package by querying pkg for the
# installed version, so os-smart has to be known to the build host. Satisfy
# that with an empty stand-in; the real package is pulled in on the firewall.
STUB=$(mktemp -d)
mkdir -p "$STUB/root"
cat > "$STUB/+MANIFEST" << EOF
name: os-smart
version: "2.0"
origin: opnsense/os-smart
comment: "build time stand-in"
maintainer: "ci@invalid"
www: "https://invalid"
prefix: /usr/local
desc: "build time stand-in, not part of the output"
EOF
pkg create -M "$STUB/+MANIFEST" -r "$STUB/root" -o "$STUB"
pkg add "$STUB"/os-smart-2.0.pkg

WORK=$(mktemp -d)
mkdir -p "$WORK/plugins/sysutils/diskhealth"
cp -R "$PLUGINS_SRC/Mk" "$PLUGINS_SRC/Templates" "$PLUGINS_SRC/Scripts" "$WORK/plugins/"
# On its development branch opnsense/plugins ships Mk/devel.mk, which forces
# every plugin into development mode (package os-diskhealth-devel). We publish
# the regular package, so build as the stable branch would.
rm -f "$WORK/plugins/Mk/devel.mk"
(cd "$HERE" && tar -cf - --exclude ./node_modules --exclude ./work --exclude ./opnsense-plugins --exclude ./package-out .) | tar -xf - -C "$WORK/plugins/sysutils/diskhealth"

cd "$WORK/plugins/sysutils/diskhealth"
make package

find work/pkg -name 'os-diskhealth-*.pkg' -exec cp {} "$OUT/" \;
ls -l "$OUT"
