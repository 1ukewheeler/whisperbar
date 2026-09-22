"""A small floating indicator that follows the mouse cursor while
push-to-talk is held, so it's visually obvious recording is happening.

A real system-wide cursor image swap isn't reliably possible for a
background app while some other app is focused, so this draws a borderless,
click-through overlay window next to the pointer instead and repositions it
on a timer while active.
"""
from __future__ import annotations

import rumps
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSPanel,
    NSTextAlignmentCenter,
    NSTextField,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakeRect

SIZE = 28
OFFSET_X = 16
OFFSET_Y = -16  # AppKit screen coordinates are bottom-left origin.
REPOSITION_INTERVAL = 0.03


class CursorOverlay:
    def __init__(self, symbol: str = "\U0001f534"):  # red circle
        rect = NSMakeRect(0, 0, SIZE, SIZE)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setLevel_(NSFloatingWindowLevel + 1)
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorIgnoresCycle
        )

        label = NSTextField.alloc().initWithFrame_(rect)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setAlignment_(NSTextAlignmentCenter)
        label.setFont_(NSFont.systemFontOfSize_(20))
        label.setStringValue_(symbol)
        panel.setContentView_(label)

        self._panel = panel
        self._label = label
        self._timer: rumps.Timer | None = None

    def show(self) -> None:
        self._reposition()
        self._panel.orderFrontRegardless()
        if self._timer is None:
            self._timer = rumps.Timer(self._tick, REPOSITION_INTERVAL)
            self._timer.start()

    def hide(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._panel.orderOut_(None)

    def _tick(self, _timer) -> None:
        self._reposition()

    def _reposition(self) -> None:
        loc = NSEvent.mouseLocation()
        self._panel.setFrameOrigin_((loc.x + OFFSET_X, loc.y + OFFSET_Y))
