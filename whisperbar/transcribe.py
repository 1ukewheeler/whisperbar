"""Model discovery, download, and transcription -- backend-agnostic.

Actual model loading/inference is delegated to whichever Backend in
backends.py claims a given repo id (see backends.py for why that split
exists). Everything here just needs a repo id string; it doesn't care what
architecture is behind it.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, Optional

import numpy as np
from huggingface_hub import scan_cache_dir, snapshot_download

from .backends import backend_for

# Every model load and inference call runs on this one thread, serially.
# MLX (0.32+) streams are thread-local, so a model loaded on one thread
# raises "There is no Stream(gpu, N) in current thread" when used from
# another -- and running two transcriptions concurrently (e.g. the startup
# preload overlapping the first press, or a second press while the first
# is still transcribing) was reproduced deadlocking inside mlx_whisper
# forever, leaving the app stuck on the transcribing icon.
_mlx_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")


class TranscriptionTimeout(RuntimeError):
    """The MLX worker didn't finish in time. It may be permanently wedged:
    nothing short of restarting the process gets it back, since the loaded
    model is bound to that thread."""

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


def _local_model_path(repo_id: str) -> str:
    """The already-downloaded snapshot dir for repo_id, so loading never
    touches the network (mlx_whisper otherwise calls snapshot_download() on
    every load, which can stall on a flaky connection, e.g. right after
    login or wake). Falls back to the repo id if it isn't cached."""
    try:
        return snapshot_download(repo_id=repo_id, local_files_only=True)
    except Exception:  # noqa: BLE001
        return repo_id


def _transcribe_on_worker(audio, model_repo, sample_rate, language) -> str:
    backend = backend_for(model_repo)
    if backend is None:
        raise ValueError(f"No transcription backend recognizes model {model_repo!r}")
    return backend.transcribe(audio, sample_rate, _local_model_path(model_repo), language=language)


def transcribe(
    audio: np.ndarray,
    model_repo: str,
    sample_rate: int = 16000,
    language: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    """Blocks the calling thread (never call from the main thread) until the
    MLX worker has transcribed `audio`, queueing behind any earlier calls.
    Raises TranscriptionTimeout after `timeout` seconds."""
    future = _mlx_executor.submit(_transcribe_on_worker, audio, model_repo, sample_rate, language)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        raise TranscriptionTimeout(f"Transcription took longer than {timeout:.0f}s") from None


def supports_language(model_repo: str) -> bool:
    backend = backend_for(model_repo)
    return bool(backend and backend.supports_language)


def preload_model(model_repo: str, on_done: Optional[Callable[[], None]] = None) -> None:
    """Warms the model into memory in the background so the *first*
    push-to-talk press after launch isn't stuck waiting for (multi-GB)
    weights to load off disk."""

    def _run():
        try:
            _transcribe_on_worker(np.zeros(16000, dtype=np.float32), model_repo, 16000, None)
        except Exception:
            pass
        finally:
            if on_done:
                on_done()

    _mlx_executor.submit(_run)
