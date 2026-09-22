"""Model discovery, download, and transcription -- backend-agnostic.

Actual model loading/inference is delegated to whichever Backend in
backends.py claims a given repo id (see backends.py for why that split
exists). Everything here just needs a repo id string; it doesn't care what
architecture is behind it.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import numpy as np
from huggingface_hub import scan_cache_dir, snapshot_download

from .backends import backend_for

# (menu label, Whisper language code or None for auto-detect)
LANGUAGES = [
    ("Auto-detect", None),
    ("English", "en"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
]


def list_installed_models() -> list[str]:
    """Locally cached HF repos that a known backend can actually load."""
    try:
        cache = scan_cache_dir()
    except Exception:
        return []
    models = []
    for repo in cache.repos:
        if repo.repo_type != "model":
            continue
        backend = backend_for(repo.repo_id)
        if backend is None:
            continue
        filenames = {f.file_name for rev in repo.revisions for f in rev.files}
        if backend.has_required_files(filenames):
            models.append(repo.repo_id)
    return sorted(set(models))


def download_model(repo_id: str, on_progress: Optional[Callable[[str], None]] = None) -> None:
    if on_progress:
        on_progress(f"Downloading {repo_id}…")
    snapshot_download(repo_id=repo_id)
    if on_progress:
        on_progress(f"Downloaded {repo_id}")


def download_model_async(repo_id: str, on_done: Callable[[Optional[str]], None]) -> None:
    def _run():
        try:
            download_model(repo_id)
            on_done(None)
        except Exception as exc:  # noqa: BLE001
            on_done(str(exc))

    threading.Thread(target=_run, daemon=True).start()


def transcribe(
    audio: np.ndarray, model_repo: str, sample_rate: int = 16000, language: Optional[str] = None
) -> str:
    backend = backend_for(model_repo)
    if backend is None:
        raise ValueError(f"No transcription backend recognizes model {model_repo!r}")
    return backend.transcribe(audio, sample_rate, model_repo, language=language)


def supports_language(model_repo: str) -> bool:
    backend = backend_for(model_repo)
    return bool(backend and backend.supports_language)


def preload_model(model_repo: str, on_done: Optional[Callable[[], None]] = None) -> None:
    """Warms the model into memory in the background so the *first*
    push-to-talk press after launch isn't stuck waiting for (multi-GB)
    weights to load off disk."""

    def _run():
        try:
            transcribe(np.zeros(16000, dtype=np.float32), model_repo)
        except Exception:
            pass
        finally:
            if on_done:
                on_done()

    threading.Thread(target=_run, daemon=True).start()
