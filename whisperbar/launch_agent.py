"""Run WhisperBar.app at login via a per-user LaunchAgent.

Only works once WhisperBar is running from a built .app bundle (see
build_app.sh) -- there's no meaningful "launch at login" target when running
main.py directly out of the venv during development.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from AppKit import NSBundle

LABEL = "com.whisperbar.app"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


class NotPackagedError(RuntimeError):
    pass


def _executable_path() -> str:
    bundle_path = NSBundle.mainBundle().bundlePath()
    if not bundle_path.endswith(".app"):
        raise NotPackagedError("WhisperBar is not running from a built .app bundle")
    return NSBundle.mainBundle().executablePath()


def install() -> None:
    exe = _executable_path()
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist)
    subprocess.run(["launchctl", "unload", "-w", str(PLIST_PATH)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)], check=False, capture_output=True)


def uninstall() -> None:
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", "-w", str(PLIST_PATH)], check=False, capture_output=True)
        PLIST_PATH.unlink()
