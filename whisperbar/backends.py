"""Transcription backends.

Different MLX transcription model families use completely different
libraries, checkpoint layouts, and inference APIs -- there's no single
"transcribe with any HF MLX model" call. Each backend here knows how to
recognize its own repos, discover them in the local HF cache, and run
inference; everything else in the app talks to models only through
`backend_for()` so adding a new architecture means adding one more Backend
subclass, not touching the rest of the pipeline.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


class Backend:
    name: str
    # Whether this backend can be told which language to decode as (vs.
    # always auto-detecting, or -- for a strictly English-only checkpoint --
    # having nothing to select). Drives whether the Language menu applies.
    supports_language: bool = False

    def matches(self, repo_id: str) -> bool:
        raise NotImplementedError

    def has_required_files(self, filenames: set[str]) -> bool:
        raise NotImplementedError

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, model_repo: str, language: Optional[str] = None
    ) -> str:
        raise NotImplementedError


class WhisperBackend(Backend):
    """openai/whisper-family encoder-decoder models via mlx_whisper.

    mlx_whisper.transcribe() caches the last-loaded model at module level
    (ModelHolder, keyed by repo id), so repeated calls with the same
    `path_or_hf_repo` reuse the in-memory weights instead of reloading from
    disk each time.
    """

    name = "whisper"
    supports_language = True

    def matches(self, repo_id: str) -> bool:
        lower = repo_id.lower()
        return "whisper" in lower and "parakeet" not in lower

    def has_required_files(self, filenames: set[str]) -> bool:
        # mlx_whisper's loader hard-codes these two names; repos that ship
        # weights under a different name (e.g. some "-4bit" conversions use
        # model.safetensors) aren't actually loadable by it.
        return "weights.safetensors" in filenames or "weights.npz" in filenames

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, model_repo: str, language: Optional[str] = None
    ) -> str:
        import mlx_whisper  # imported lazily: first import is slow

        if len(audio) == 0:
            return ""
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=model_repo,
            condition_on_previous_text=False,
            # language=None lets Whisper auto-detect per utterance, which is
            # exactly what caused it to occasionally decode short/ambiguous
            # clips as Russian etc. -- pinning a language avoids that.
            language=language,
            # A single deterministic pass instead of mlx_whisper's default
            # 6-temperature retry ladder (which only kicks in when a pass
            # looks low-quality, but multiplies worst-case latency for short
            # push-to-talk clips where it rarely helps).
            temperature=0.0,
        )
        return result.get("text", "").strip()


class ParakeetBackend(Backend):
    """NVIDIA Parakeet (FastConformer + transducer) models via parakeet_mlx.

    Architecturally not an encoder-decoder like Whisper -- much faster for
    short clips since it isn't bound to Whisper's fixed 30-second-padded
    encoder pass -- but it's a different package with a different loading
    and inference API, hence its own Backend implementation.

    Like every backend, only ever called on transcribe.py's single MLX
    worker thread (see there for why).
    """

    name = "parakeet"
    # parakeet_mlx's API has no language parameter -- it always predicts
    # whichever of its trained languages it thinks it hears (the multilingual
    # v3 checkpoint covers ~25 languages, with no way to constrain that from
    # here). The Language menu is a no-op for this backend; use an
    # English-only checkpoint like parakeet-tdt-0.6b-v2 for guaranteed English.
    supports_language = False
    _loaded_repo: Optional[str] = None
    _loaded_model = None

    def matches(self, repo_id: str) -> bool:
        return "parakeet" in repo_id.lower()

    def has_required_files(self, filenames: set[str]) -> bool:
        return "config.json" in filenames and (
            "model.safetensors" in filenames or "weights.safetensors" in filenames
        )

    def _model(self, model_repo: str):
        if self._loaded_model is None or self._loaded_repo != model_repo:
            import locale

            import parakeet_mlx

            # Belt-and-suspenders re-assertion of main.py's locale fix:
            # AppKit/Cocoa initialization (rumps.App.run() -> NSApplication)
            # has been observed to reset the process locale back to
            # ASCII/"C" after main.py sets it, which breaks parakeet_mlx's
            # un-encoded open() call on config.json.
            for candidate in ("en_US.UTF-8", "C.UTF-8", "UTF-8"):
                try:
                    locale.setlocale(locale.LC_ALL, candidate)
                    break
                except locale.Error:
                    continue

            self._loaded_model = parakeet_mlx.from_pretrained(model_repo)
            self._loaded_repo = model_repo
        return self._loaded_model

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, model_repo: str, language: Optional[str] = None
    ) -> str:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        if len(audio) == 0:
            return ""
        model = self._model(model_repo)
        # Feed the samples straight in rather than via model.transcribe(path):
        # that decodes files by shelling out to `ffmpeg`, which isn't on the
        # minimal PATH a Finder/login-launched app gets (no /opt/homebrew/bin),
        # so it failed only when run as WhisperBar.app. This is what
        # transcribe() does after decoding.
        target_rate = model.preprocessor_config.sample_rate
        if sample_rate != target_rate:
            import librosa

            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=target_rate)
        mel = get_logmel(mx.array(audio.astype(np.float32)), model.preprocessor_config)
        return model.generate(mel)[0].text.strip()


BACKENDS: list[Backend] = [WhisperBackend(), ParakeetBackend()]


def backend_for(repo_id: str) -> Optional[Backend]:
    for backend in BACKENDS:
        if backend.matches(repo_id):
            return backend
    return None
