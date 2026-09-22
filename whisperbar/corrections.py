"""Learned mistake -> fix phrase replacements, kept per model.

Populated via the "Correct Last Transcription…" menu flow. Different models
mishear things differently, so corrections are scoped to whichever model
was active when they were learned -- see config.corrections_path(). Stored
as plain JSON the user can open in their default editor to review or
hand-edit/delete entries.
"""
from __future__ import annotations

import re
import time
import uuid

from . import config

_WORD_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_TRAILING_PUNCT = ".,!?;:\"'"
# Below this length, fuzzy matching is too likely to collide with an
# unrelated short/common word (e.g. "Quen" at distance 1 already reaches
# "when") to be worth it -- only exact matches apply to short words.
_MIN_FUZZY_WORD_LEN = 3


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,  # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + (ca != cb),  # substitution
            )
        prev = curr
    return prev[-1]


def _max_fuzzy_distance(word_len: int) -> int:
    # Scaled conservatively by length: short words tolerate almost no drift
    # before they risk colliding with a different real word.
    if word_len <= 4:
        return 1
    if word_len <= 8:
        return 2
    return 3


class CorrectionsStore:
    def add(self, model_repo: str, original: str, corrected: str) -> None:
        original = original.strip()
        corrected = corrected.strip()
        if not original or original == corrected:
            return
        corrections = config.load_corrections(model_repo)
        # Replace an existing entry for the same original phrase rather than duplicating it.
        corrections = [c for c in corrections if c.get("original") != original]
        corrections.append(
            {
                "id": uuid.uuid4().hex[:8],
                "original": original,
                "corrected": corrected,
                "created_at": int(time.time()),
            }
        )
        config.save_corrections(model_repo, corrections)

    def apply(self, model_repo: str, text: str) -> str:
        corrections = [c for c in config.load_corrections(model_repo) if c.get("original", "").strip()]
        # Multi-word corrections only ever make sense as an exact phrase
        # match; single-word ones additionally get a fuzzy pass below, to
        # catch mishearings close to (but not identical to) what was taught
        # -- e.g. correcting "Quen" -> "Qwen" also catching "Quem", "Kwen".
        word_corrections = [c for c in corrections if " " not in c["original"].strip()]

        # Exact matches first, longest phrase first so a correction for a
        # longer phrase isn't shadowed by a shorter one that's a substring
        # of it.
        for c in sorted(corrections, key=lambda c: len(c["original"]), reverse=True):
            original = c["original"]
            if original in text:
                text = text.replace(original, c["corrected"])

        if not word_corrections:
            return text

        candidates = [
            (c["original"].strip().rstrip(_TRAILING_PUNCT).lower(), c["corrected"].rstrip(_TRAILING_PUNCT))
            for c in word_corrections
        ]
        candidates = [(orig, fixed) for orig, fixed in candidates if len(orig) >= _MIN_FUZZY_WORD_LEN]

        def _replace_token(match: re.Match) -> str:
            token = match.group(0)
            lower = token.lower()
            if len(lower) < _MIN_FUZZY_WORD_LEN:
                return token
            for original, fixed in candidates:
                if lower == original:
                    continue  # already handled by the exact pass above
                limit = _max_fuzzy_distance(max(len(lower), len(original)))
                if _levenshtein(lower, original) <= limit:
                    return fixed
            return token

        return _WORD_RE.sub(_replace_token, text)
