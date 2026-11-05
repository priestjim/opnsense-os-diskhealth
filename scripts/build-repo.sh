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

# Turn a directory of .pkg files into a signed (or unsigned) pkg repository.
#
#   scripts/build-repo.sh <dir-with-pkgs> <repo-dir> [rsa-private-key]
#
# With a key the repository is signed and the public key is written to
# <repo-dir>/../repo.pub for users to import; without one it can only be used with signature_type "none".
# Next to the repository the ready-made pkg repository definition <repo-dir>/../diskhealth.conf is written, which
# users download into /usr/local/etc/pkg/repos/. PAGES_URL is the base URL the site is served from.
set -eu

PAGES_URL=${PAGES_URL:-https://priestjim.github.io/opnsense-os-diskhealth}

PKGS=$1
REPO=$2
KEY=${3:-}

mkdir -p "$REPO/All"
cp "$PKGS"/*.pkg "$REPO/All/"

if [ -n "$KEY" ]; then
    pkg repo "$REPO" "$KEY"
    openssl rsa -in "$KEY" -pubout -out "$REPO/../repo.pub" 2> /dev/null
    SECURITY='signature_type: "pubkey",
  pubkey: "/usr/local/etc/pkg/keys/diskhealth.pub",'
else
    pkg repo "$REPO"
    SECURITY='signature_type: "none",'
fi
cat > "$REPO/../diskhealth.conf" << EOF
diskhealth: {
  url: "$PAGES_URL/repo",
  $SECURITY
  priority: 5,
  enabled: yes
}
EOF
ls -lR "$REPO"
