#!/bin/bash
# Builds WhisperBar.app using py2app's *alias* mode: a real compiled
# launcher that embeds Python in-process and runs everything straight out
# of this project's venv, without freezing/copying any dependencies into
# the bundle.
#
# Two things that don't work were tried and ruled out first:
#   - A hand-written launcher that exec()s the venv's python3: this
#     replaces the process image, which breaks the window-server
#     connection LaunchServices set up for the original signed bundle --
#     confirmed with a minimal test app that never showed a menu bar icon.
#   - Full (non-alias) py2app builds: py2app's dependency freezer is
#     unreliable with mlx's compiled Metal shader libraries and native
#     extensions.
# Alias mode's launcher keeps a single process image throughout (like a
# real compiled app) while leaving dependencies exactly where they are on
# disk (like the exec approach) -- it's the combination this needs.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="WhisperBar"
DEST="${1:-/Applications/${APP_NAME}.app}"

if [ ! -x "${PROJECT_DIR}/.venv/bin/python3" ]; then
    echo "error: ${PROJECT_DIR}/.venv not found. Run: python3 -m venv --system-site-packages .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

# Stable code signing identity. py2app signs ad-hoc, and macOS ties
# Accessibility / Input Monitoring / Microphone grants to an ad-hoc
# signature's exact hash -- so every rebuild silently revoked them. Signing
# with one persistent self-signed certificate instead makes the app's
# identity "com.whisperbar.app + this certificate", which survives rebuilds.
# The certificate is created in the login keychain on first run. It's only
# ever used locally, so it doesn't need to be trusted (codesign accepts it
# by SHA-1 hash).
SIGNING_NAME="WhisperBar Local Signing"

signing_identity_hash() {
    { security find-certificate -c "${SIGNING_NAME}" -Z 2>/dev/null || true; } | awk '/^SHA-1 hash:/ {print $3; exit}'
}

create_signing_identity() {
    local tmp
    tmp="$(mktemp -d)"
    # /usr/bin/openssl (LibreSSL) on purpose: its PKCS#12 encryption is what
    # `security import` understands; Homebrew OpenSSL 3's default isn't.
    /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -subj "/CN=${SIGNING_NAME}" \
        -addext "keyUsage=critical,digitalSignature" \
        -addext "extendedKeyUsage=critical,codeSigning" \
        -keyout "${tmp}/key.pem" -out "${tmp}/cert.pem" 2>/dev/null
    /usr/bin/openssl pkcs12 -export -inkey "${tmp}/key.pem" -in "${tmp}/cert.pem" \
        -name "${SIGNING_NAME}" -passout pass:whisperbar -out "${tmp}/identity.p12"
    security import "${tmp}/identity.p12" -P whisperbar -T /usr/bin/codesign >/dev/null
    rm -rf "${tmp}"
    echo "Created code signing certificate \"${SIGNING_NAME}\" in your login keychain."
}

SIGNING_HASH="$(signing_identity_hash)"
if [ -z "${SIGNING_HASH}" ]; then
    create_signing_identity
    SIGNING_HASH="$(signing_identity_hash)"
fi

cd "${PROJECT_DIR}"
rm -rf build dist
.venv/bin/python3 setup.py py2app -A --dist-dir dist >/dev/null
codesign --force --sign "${SIGNING_HASH}" --identifier com.whisperbar.app "dist/${APP_NAME}.app"

rm -rf "${DEST}"
mkdir -p "$(dirname "${DEST}")"
mv "dist/${APP_NAME}.app" "${DEST}"
rm -rf build dist

echo "Built ${DEST} (signed with \"${SIGNING_NAME}\" -- permissions carry over between rebuilds)"
echo "This launcher runs the project's venv in place -- keep ${PROJECT_DIR} where it is."
