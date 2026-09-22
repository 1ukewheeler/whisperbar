#!/usr/bin/env python3
"""Generates AppIcon.icns: a hand-drawn vector microphone glyph on a
rounded-square gradient background.

(An emoji-based glyph was tried first, but Apple Color Emoji is a
fixed-size bitmap font that doesn't scale cleanly through NSString's
drawing APIs at icon resolution -- drawing our own shapes avoids that
entirely and stays crisp at every icon size.)

Run with the project's venv: .venv/bin/python3 make_icon.py
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSGraphicsContext,
    NSImage,
    NSMakeRect,
    NSMakePoint,
    NSPNGFileType,
)

PROJECT_DIR = Path(__file__).resolve().parent
ICONSET_DIR = PROJECT_DIR / "AppIcon.iconset"
ICNS_PATH = PROJECT_DIR / "AppIcon.icns"

SIZE = 1024
BG_START = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.20, 0.22, 0.30, 1.0)
BG_END = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.07, 0.11, 1.0)
GLYPH_COLOR = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.96, 0.97, 1.0, 1.0)
ACCENT = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.26, 0.28, 1.0)


def _draw_background(rect) -> None:
    corner_radius = SIZE * 0.22
    path_bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, corner_radius, corner_radius)
    path_bg.addClip()

    gradient_steps = 64
    for i in range(gradient_steps):
        t = i / (gradient_steps - 1)
        r = BG_START.redComponent() + (BG_END.redComponent() - BG_START.redComponent()) * t
        g = BG_START.greenComponent() + (BG_END.greenComponent() - BG_START.greenComponent()) * t
        b = BG_START.blueComponent() + (BG_END.blueComponent() - BG_START.blueComponent()) * t
        NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0).set()
        band_h = SIZE / gradient_steps
        NSBezierPath.fillRect_(NSMakeRect(0, i * band_h, SIZE, band_h + 1))


def _draw_microphone() -> None:
    cx = SIZE / 2
    line_w = SIZE * 0.05

    # Capsule body.
    body_w = SIZE * 0.24
    body_h = SIZE * 0.40
    body_top = SIZE * 0.70
    body_bottom = body_top - body_h
    body_rect = NSMakeRect(cx - body_w / 2, body_bottom, body_w, body_h)
    body = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(body_rect, body_w / 2, body_w / 2)
    GLYPH_COLOR.set()
    body.fill()

    # Stand (vertical line straight down from the capsule's base).
    stand_bottom = SIZE * 0.24
    stand = NSBezierPath.bezierPath()
    stand.setLineWidth_(line_w)
    stand.setLineCapStyle_(1)  # round
    stand.moveToPoint_(NSMakePoint(cx, body_bottom + line_w * 0.3))
    stand.lineToPoint_(NSMakePoint(cx, stand_bottom))
    GLYPH_COLOR.set()
    stand.stroke()

    # Base foot.
    foot_w = SIZE * 0.20
    foot = NSBezierPath.bezierPath()
    foot.setLineWidth_(line_w)
    foot.setLineCapStyle_(1)
    foot.moveToPoint_(NSMakePoint(cx - foot_w / 2, stand_bottom))
    foot.lineToPoint_(NSMakePoint(cx + foot_w / 2, stand_bottom))
    GLYPH_COLOR.set()
    foot.stroke()

    # Small accent dot (recording indicator) top-right of the capsule.
    dot_r = SIZE * 0.045
    dot_center = NSMakePoint(cx + body_w * 0.75, body_top - SIZE * 0.02)
    dot_rect = NSMakeRect(dot_center.x - dot_r, dot_center.y - dot_r, dot_r * 2, dot_r * 2)
    ACCENT.set()
    NSBezierPath.bezierPathWithOvalInRect_(dot_rect).fill()


def render_master_png(path: Path) -> None:
    image = NSImage.alloc().initWithSize_((SIZE, SIZE))
    image.lockFocus()
    NSGraphicsContext.currentContext().saveGraphicsState()

    rect = NSMakeRect(0, 0, SIZE, SIZE)
    _draw_background(rect)
    _draw_microphone()

    NSGraphicsContext.currentContext().restoreGraphicsState()
    image.unlockFocus()

    bitmap = NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
    png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
    png_data.writeToFile_atomically_(str(path), True)


def build_iconset(master_png: Path) -> None:
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir()

    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for size in sizes:
        out1x = ICONSET_DIR / f"icon_{size}x{size}.png"
        subprocess.run(
            ["sips", "-z", str(size), str(size), str(master_png), "--out", str(out1x)],
            check=True,
            capture_output=True,
        )
    # @2x variants (e.g. icon_16x16@2x.png == 32px master, etc.)
    pairs = [(16, 32), (32, 64), (128, 256), (256, 512), (512, 1024)]
    for base, doubled in pairs:
        src = ICONSET_DIR / f"icon_{doubled}x{doubled}.png"
        dst = ICONSET_DIR / f"icon_{base}x{base}@2x.png"
        shutil.copy(src, dst)
    # 1024 has no @2x slot in the standard iconset; drop the bare 1024 (not required).
    (ICONSET_DIR / "icon_1024x1024.png").unlink()


def main() -> None:
    master_png = PROJECT_DIR / "_icon_master.png"
    render_master_png(master_png)
    build_iconset(master_png)
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)], check=True)
    shutil.rmtree(ICONSET_DIR)
    master_png.unlink()
    print(f"Wrote {ICNS_PATH}")


if __name__ == "__main__":
    main()
