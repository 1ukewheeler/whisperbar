#!/usr/bin/env python3
"""Regression harness for the transcription pipeline.

Runs synthetic speech (generated once via `say` + ffmpeg, see
tests/audio/generate.sh) through every installed model, replicating the
app's actual threading pattern: preload on one background thread, then
transcribe each press on a fresh background thread -- this is what exposed
the Parakeet cross-thread MLX Stream bug that plain single-threaded testing
missed.

Usage: .venv/bin/python3 tests/test_transcribe.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from whisperbar import transcribe  # noqa: E402

AUDIO_DIR = Path(__file__).resolve().parent / "audio"

# (filename, substrings that must all appear in the transcription, case-insensitive)
CASES = [
    ("testing123.wav", ["testing", "1", "2", "3"]),
    ("numbers.wav", ["555", "123", "4567"]),
    ("short.wav", ["testing"]),
]

MODELS = [
    "mlx-community/whisper-large-v3-turbo",
    "mlx-community/parakeet-tdt-0.6b-v3",
    "mlx-community/parakeet-tdt-0.6b-v2",
]


def _run_on_own_thread(fn, *args):
    """Runs fn(*args) on a brand-new thread and returns its result/exception,
    mirroring how app.py spawns a fresh threading.Thread per push-to-talk
    press."""
    box = {}

    def _target():
        try:
            box["result"] = fn(*args)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=_target)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def main() -> int:
    failures = 0

    for model in MODELS:
        print(f"\n=== {model} ===")

        # Preload on its own thread, exactly like app.py's startup preload.
        _run_on_own_thread(transcribe.transcribe, np.zeros(16000, dtype=np.float32), model)

        for filename, expected in CASES:
            path = AUDIO_DIR / filename
            if not path.exists():
                print(f"  SKIP {filename}: not found (run tests/audio/generate.sh first)")
                continue
            audio, sr = sf.read(str(path), dtype="float32")

            t0 = time.time()
            try:
                text = _run_on_own_thread(transcribe.transcribe, audio, model, sr)
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL {filename}: raised {exc!r}")
                failures += 1
                continue
            elapsed = time.time() - t0

            lower = text.lower()
            missing = [s for s in expected if s.lower() not in lower]
            status = "ok" if not missing else "MISMATCH"
            if missing:
                failures += 1
            print(f"  [{status}] {filename} ({elapsed:.2f}s): {text!r}" + (f"  missing={missing}" if missing else ""))

    print(f"\n{'PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
