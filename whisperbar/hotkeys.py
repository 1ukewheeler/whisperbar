"""Global key monitoring via a Quartz CGEventTap.

Used both for push-to-talk (key-down starts recording, key-up stops it) and
for the "capture next keypress" flow used by the hotkey picker in the menu.

Requires the app to be granted Accessibility + Input Monitoring permission
in System Settings > Privacy & Security, otherwise CGEventTapCreate returns
None and start() raises PermissionError.
"""
from __future__ import annotations

from typing import Callable, Optional

import Quartz


class PermissionError(RuntimeError):
    """Raised when macOS refuses to create the global event tap."""


class HotkeyManager:
    def __init__(self):
        self._tap = None
        self._run_loop_source = None
        self._ptt_keycode: Optional[int] = None
        self._on_press: Optional[Callable[[], None]] = None
        self._on_release: Optional[Callable[[], None]] = None
        self._is_down = False
        self._capture_callback: Optional[Callable[[int], None]] = None

    def start(self, ptt_keycode: int, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._ptt_keycode = ptt_keycode
        self._on_press = on_press
        self._on_release = on_release

        mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
        )
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._handle_event,
            None,
        )
        if tap is None:
            raise PermissionError(
                "Could not create a global event tap. Grant WhisperBar Accessibility "
                "and Input Monitoring permission in System Settings > Privacy & Security, "
                "then relaunch it."
            )
        self._tap = tap
        self._run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), self._run_loop_source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(tap, True)

    def stop(self) -> None:
        if self._tap is not None:
            Quartz.CGEventTapEnable(self._tap, False)
        if self._run_loop_source is not None:
            Quartz.CFRunLoopRemoveSource(
                Quartz.CFRunLoopGetCurrent(), self._run_loop_source, Quartz.kCFRunLoopCommonModes
            )
        self._tap = None
        self._run_loop_source = None

    def set_ptt_keycode(self, keycode: int) -> None:
        self._ptt_keycode = keycode

    def capture_next_key(self, callback: Callable[[int], None]) -> None:
        """The next key-down event is reported to `callback(keycode)` instead of
        being treated as the push-to-talk key. Used by "Change Push-to-Talk Key…"."""
        self._capture_callback = callback

    def _handle_event(self, proxy, event_type, event, refcon):  # noqa: ARG002
        if event_type in (
            Quartz.kCGEventTapDisabledByTimeout,
            Quartz.kCGEventTapDisabledByUserInput,
        ):
            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, True)
            return event

        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)

        if event_type == Quartz.kCGEventKeyDown and self._capture_callback is not None:
            cb = self._capture_callback
            self._capture_callback = None
            cb(keycode)
            return event

        if keycode != self._ptt_keycode:
            return event

        if event_type == Quartz.kCGEventKeyDown:
            if not self._is_down:
                self._is_down = True
                if self._on_press:
                    self._on_press()
        elif event_type == Quartz.kCGEventKeyUp:
            if self._is_down:
                self._is_down = False
                if self._on_release:
                    self._on_release()

        return event


# macOS virtual keycode names for common PTT-friendly keys (no default OS meaning).
KEY_NAMES = {
    105: "F13",
    107: "F14",
    113: "F15",
    106: "F16",
    64: "F17",
    79: "F18",
    80: "F19",
    90: "F20",
}


def keycode_name(keycode: int) -> str:
    return KEY_NAMES.get(keycode, f"Key {keycode}")
