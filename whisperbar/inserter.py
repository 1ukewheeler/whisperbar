"""Inserts transcribed text into whichever app is currently focused."""
from __future__ import annotations

import time

import Quartz
from AppKit import NSPasteboard, NSStringPboardType


def _post_unicode_string(text: str) -> None:
    down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    Quartz.CGEventKeyboardSetUnicodeString(down, len(text), text)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)

    up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
    Quartz.CGEventKeyboardSetUnicodeString(up, len(text), text)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)


def _post_paste(text: str) -> None:
    pasteboard = NSPasteboard.generalPasteboard()
    saved = pasteboard.stringForType_(NSStringPboardType)
    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSStringPboardType)

    cmd_down = Quartz.CGEventCreateKeyboardEvent(None, 0x09, True)  # 'v'
    Quartz.CGEventSetFlags(cmd_down, Quartz.kCGEventFlagMaskCommand)
    cmd_up = Quartz.CGEventCreateKeyboardEvent(None, 0x09, False)
    Quartz.CGEventSetFlags(cmd_up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, cmd_down)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, cmd_up)

    # Give the paste a moment to land before restoring the user's clipboard.
    time.sleep(0.4)
    if saved is not None:
        pasteboard.clearContents()
        pasteboard.setString_forType_(saved, NSStringPboardType)


def insert_text(text: str, method: str = "type") -> None:
    if not text:
        return
    if method == "paste":
        _post_paste(text)
    else:
        _post_unicode_string(text)
