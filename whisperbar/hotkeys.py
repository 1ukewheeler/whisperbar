"""Global key monitoring via a Quartz CGEventTap.

Supports multiple independent named bindings (e.g. "ptt" for hold-to-talk,
"toggle" for press-to-start/press-to-stop) on one shared event tap, plus a
"capture next keypress" mode used by the hotkey pickers in the menu.

Requires the app to be granted Accessibility + Input Monitoring permission
in System Settings > Privacy & Security, otherwise CGEventTapCreate returns
None and start() raises PermissionError.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import Quartz


class PermissionError(RuntimeError):
    """Raised when macOS refuses to create the global event tap."""


@dataclass
class _Binding:
    keycode: Optional[int]
    on_down: Optional[Callable[[], None]]
    on_up: Optional[Callable[[], None]]
    is_down: bool = False


class HotkeyManager:
    def __init__(self):
        self._tap = None
        self._run_loop_source = None
        self._bindings: dict[str, _Binding] = {}
        self._capture_callback: Optional[Callable[[int], None]] = None

    def start(self) -> None:
        if self._tap is not None:
            return  # already started; safe to call again (e.g. a "recheck permissions" retry)
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

    def bind(
        self,
        name: str,
        keycode: Optional[int],
        on_down: Optional[Callable[[], None]] = None,
        on_up: Optional[Callable[[], None]] = None,
    ) -> None:
        """Registers (or replaces) a named binding. `keycode=None` disables it."""
        self._bindings[name] = _Binding(keycode=keycode, on_down=on_down, on_up=on_up)

    def set_keycode(self, name: str, keycode: Optional[int]) -> None:
        if name in self._bindings:
            self._bindings[name].keycode = keycode
            self._bindings[name].is_down = False

    def capture_next_key(self, callback: Callable[[int], None]) -> None:
        """The next key-down event is reported to `callback(keycode)` instead of
        triggering any bound action. Used by the "Change key…" menu flow."""
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

        for binding in self._bindings.values():
            if keycode != binding.keycode:
                continue
            if event_type == Quartz.kCGEventKeyDown:
                if not binding.is_down:
                    binding.is_down = True
                    if binding.on_down:
                        binding.on_down()
            elif event_type == Quartz.kCGEventKeyUp:
                if binding.is_down:
                    binding.is_down = False
                    if binding.on_up:
                        binding.on_up()

        return event


# macOS virtual keycodes for the function-row keys beyond F12: no default
# OS meaning, and (unlike modifier keys such as Option/Command, which only
# generate flagsChanged events our tap doesn't listen for) they generate
# ordinary keyDown/keyUp, so they work as both a "press it" capture target
# and a plain named menu choice.
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
NAME_TO_KEYCODE = {name: code for code, name in KEY_NAMES.items()}


def keycode_name(keycode: Optional[int]) -> str:
    if keycode is None:
        return "None"
    return KEY_NAMES.get(keycode, f"Key {keycode}")
