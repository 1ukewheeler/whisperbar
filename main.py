#!/usr/bin/env python3
import locale
import os

# GUI-launched apps (via LaunchServices/`open`) don't inherit LANG/LC_ALL
# from a shell profile the way a Terminal-launched process does, so
# Python's default text encoding for open() can fall back to ASCII. That
# breaks any dependency that reads a UTF-8 file without specifying the
# encoding explicitly (observed with parakeet_mlx's config.json loading).
# Set both the env vars (so anything that later calls setlocale(LC_ALL, "")
# -- Cocoa/AppKit init does this -- still resolves to UTF-8) and the
# in-process locale itself.
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")
for _candidate in ("en_US.UTF-8", "C.UTF-8", "UTF-8"):
    try:
        locale.setlocale(locale.LC_ALL, _candidate)
        break
    except locale.Error:
        continue

from whisperbar.app import run

if __name__ == "__main__":
    run()
