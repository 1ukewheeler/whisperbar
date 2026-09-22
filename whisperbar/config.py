"""Paths and persisted settings for WhisperBar."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "WhisperBar"
SETTINGS_PATH = APP_SUPPORT_DIR / "settings.json"
RULES_PATH = APP_SUPPORT_DIR / "rules.json"
CORRECTIONS_DIR = APP_SUPPORT_DIR / "corrections"
# Pre-migration single shared file. Different models mishear things
# differently, so a fix learned for one model's mistakes is dead weight
# (or worse, a false match) against another model's output -- corrections
# now live one file per model instead (see corrections_path()).
_LEGACY_CORRECTIONS_PATH = APP_SUPPORT_DIR / "corrections.json"

# kVK_F16/F17 - physical keys with no other macOS meaning, safe as silent
# push-to-talk / toggle triggers.
DEFAULT_PTT_KEYCODE = 106
DEFAULT_TOGGLE_KEYCODE = 64

DEFAULT_SETTINGS = {
    "model": "mlx-community/parakeet-tdt-0.6b-v2",
    "ptt_keycode": DEFAULT_PTT_KEYCODE,
    "toggle_keycode": DEFAULT_TOGGLE_KEYCODE,  # None disables the toggle-record key
    "sample_rate": 16000,
    "insert_method": "paste",  # "paste" (pasteboard + Cmd-V, most reliable) or "type" (synthetic keystrokes)
    "launch_at_login": False,
    "language": "en",  # Whisper language code, or None for auto-detect. Ignored by backends that don't support it.
}

DEFAULT_RULES = [
    {
        "id": "spoken-numbers",
        "type": "builtin",
        "name": "Convert spoken numbers to digits",
        "enabled": True,
    }
]

# Shipped as a fresh install's starting corrections for the default model,
# so a new user gets a small head start rather than an empty file. Purely
# generic tech-term fixes -- nothing personal to strip out.
DEFAULT_CORRECTIONS = {
    "mlx-community/parakeet-tdt-0.6b-v2": [
        {
            "id": "b1da34d0",
            "original": "DgX Spark Invidia Quen",
            "corrected": "DGX Spark, NVIDIA, Qwen",
            "created_at": 1790050491,
        },
        {
            "id": "283f3cbc",
            "original": "DgX Spark.",
            "corrected": "DGX Spark.",
            "created_at": 1790051299,
        },
        {
            "id": "e5ee3a0f",
            "original": "Quen.",
            "corrected": "Qwen.",
            "created_at": 1790051356,
        },
        {
            "id": "6eae0742",
            "original": "Quinn.",
            "corrected": "Qwen.",
            "created_at": 1790051373,
        },
    ],
}

_lock = threading.Lock()


def _ensure_dir() -> None:
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    _ensure_dir()
    if not path.exists():
        _save_json(path, default)
        return json.loads(json.dumps(default))
    try:
        with path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.replace(path)


def load_settings() -> dict:
    with _lock:
        settings = _load_json(SETTINGS_PATH, DEFAULT_SETTINGS)
        merged = {**DEFAULT_SETTINGS, **settings}
        if merged != settings:
            _save_json(SETTINGS_PATH, merged)
        return merged


def save_settings(settings: dict) -> None:
    with _lock:
        _save_json(SETTINGS_PATH, settings)


def load_rules() -> list:
    with _lock:
        return _load_json(RULES_PATH, DEFAULT_RULES)


def save_rules(rules: list) -> None:
    with _lock:
        _save_json(RULES_PATH, rules)


def corrections_path(model_repo: str) -> Path:
    safe_name = model_repo.replace("/", "--")
    return CORRECTIONS_DIR / f"{safe_name}.json"


def _migrate_legacy_corrections(model_repo: str) -> None:
    """One-time move of the old single shared corrections.json into the
    given model's file, the first time any per-model file is touched."""
    if not _LEGACY_CORRECTIONS_PATH.exists():
        return
    try:
        with _LEGACY_CORRECTIONS_PATH.open("r") as f:
            legacy = json.load(f)
    except (json.JSONDecodeError, OSError):
        legacy = None
    if legacy:
        _save_json(corrections_path(model_repo), legacy)
    _LEGACY_CORRECTIONS_PATH.rename(_LEGACY_CORRECTIONS_PATH.with_suffix(".json.migrated"))


def load_corrections(model_repo: str) -> list:
    with _lock:
        _migrate_legacy_corrections(model_repo)
        default = DEFAULT_CORRECTIONS.get(model_repo, [])
        return _load_json(corrections_path(model_repo), default)


def save_corrections(model_repo: str, corrections: list) -> None:
    with _lock:
        _save_json(corrections_path(model_repo), corrections)
