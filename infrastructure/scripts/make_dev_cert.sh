#!/usr/bin/env bash
# Creates a SELF-SIGNED certificate in deploy/certs/ so the production stack can be run on a workstation.
# Browsers will warn about it. Do not use it on a real deployment: install a certificate from a CA instead
# (docs/deployment-guide.md). The files are git-ignored.
#
#   ./infrastructure/scripts/make_dev_cert.sh [hostname]      # default: localhost
#   CERT_DIR=some/dir ./infrastructure/scripts/make_dev_cert.sh   # write somewhere else
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash on Windows would otherwise rewrite the /CN=... subject as a file path

host="${1:-localhost}"
dir="${CERT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)/deploy/certs}"
mkdir -p "$dir"

if [ -e "$dir/tls.key" ] && [ -z "${FORCE:-}" ]; then
  echo "deploy/certs/tls.key already exists; set FORCE=1 to replace it." >&2
  exit 1
fi

san="DNS:${host}"
case "$host" in localhost) san="DNS:localhost,IP:127.0.0.1,IP:::1" ;; esac

openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 30 \
  -keyout "$dir/tls.key" -out "$dir/tls.crt" \
  -subj "/CN=${host}" -addext "subjectAltName=${san}"

# nginx runs as an unprivileged user inside the container and reads the key through a read-only bind mount.
chmod 644 "$dir/tls.crt" "$dir/tls.key"
echo "Wrote $dir/tls.crt and tls.key (self-signed, valid 30 days, for ${host})."
