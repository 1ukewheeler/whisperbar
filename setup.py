"""py2app build script, used in *alias* mode only (see build_app.sh).

Alias mode generates a real compiled launcher that embeds Python in-process
(rather than exec'ing a separate interpreter binary -- which breaks the
window-server connection needed for a menu bar icon, confirmed by testing)
without freezing/copying any dependencies into the bundle. That matters
because mlx's compiled Metal shader libraries and native extensions are not
safe to freeze reliably; alias mode leaves everything running straight out
of this project's venv instead.
"""
from setuptools import setup

APP = ["main.py"]
OPTIONS = {
    "iconfile": "AppIcon.icns",
    "plist": {
        "CFBundleName": "WhisperBar",
        "CFBundleDisplayName": "WhisperBar",
        "CFBundleIdentifier": "com.whisperbar.app",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": (
            "WhisperBar records audio while you hold the push-to-talk key, "
            "to transcribe it locally."
        ),
        "NSAppleEventsUsageDescription": (
            "WhisperBar types transcribed text into the app you're using."
        ),
    },
}

setup(
    app=APP,
    name="WhisperBar",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
