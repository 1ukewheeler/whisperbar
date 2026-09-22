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

cd "${PROJECT_DIR}"
rm -rf build dist
.venv/bin/python3 setup.py py2app -A --dist-dir dist >/dev/null

rm -rf "${DEST}"
mkdir -p "$(dirname "${DEST}")"
mv "dist/${APP_NAME}.app" "${DEST}"
rm -rf build dist

echo "Built ${DEST}"
echo "This launcher runs the project's venv in place -- keep ${PROJECT_DIR} where it is."
echo "First launch: right-click ${APP_NAME}.app in Finder > Open (macOS will ask you to confirm once, since it's unsigned)."
