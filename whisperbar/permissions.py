"""One-click access to the three System Settings panes WhisperBar needs,
plus a best-effort read of current permission status.

macOS deliberately doesn't let an app flip these switches on the user's
behalf (that's a security boundary, not a gap in this app) -- what this
module gets you is jumping straight to the right pane instead of digging
through System Settings > Privacy & Security by hand, and, for Microphone,
reading the actual OS-reported status so the menu can show it instead of
guessing.
"""
from __future__ import annotations

import subprocess

PANE_URLS = {
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}


def open_pane(name: str) -> None:
    url = PANE_URLS[name]
    subprocess.run(["open", url], check=False)


def microphone_status() -> str:
    """"granted" / "denied" / "not_determined" / "restricted" / "unknown"."""
    try:
        import AVFoundation

        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
    except Exception:
        return "unknown"
    return {
        0: "not_determined",
        1: "restricted",
        2: "denied",
        3: "granted",
    }.get(status, "unknown")
