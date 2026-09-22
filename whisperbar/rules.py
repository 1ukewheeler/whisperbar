"""Ordered, user-editable text-transform rules applied after transcription.

Rules live in rules.json (see config.py). Two kinds:
  - {"type": "builtin", "id": "spoken-numbers", "enabled": bool}
  - {"type": "regex", "pattern": str, "replacement": str, "enabled": bool}
"""
from __future__ import annotations

import re

from . import config

# Word-by-word (not compound: "one two three" -> "1 2 3", not "123") since
# that matches how people dictate codes/digits/serials, and avoids ambiguity
# about whether adjacent number words should combine into one number.
NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def apply_spoken_numbers(text: str) -> str:
    def _replace(match: re.Match) -> str:
        return NUMBER_WORDS[match.group(0).lower()]

    return _NUMBER_WORD_RE.sub(_replace, text)


class RuleEngine:
    def apply(self, text: str) -> str:
        for rule in config.load_rules():
            if not rule.get("enabled", True):
                continue
            if rule.get("type") == "builtin" and rule.get("id") == "spoken-numbers":
                text = apply_spoken_numbers(text)
            elif rule.get("type") == "regex":
                try:
                    text = re.sub(rule["pattern"], rule["replacement"], text)
                except re.error:
                    continue
        return text

    def set_builtin_enabled(self, rule_id: str, enabled: bool) -> None:
        rules = config.load_rules()
        for rule in rules:
            if rule.get("type") == "builtin" and rule.get("id") == rule_id:
                rule["enabled"] = enabled
        config.save_rules(rules)

    def is_builtin_enabled(self, rule_id: str) -> bool:
        for rule in config.load_rules():
            if rule.get("type") == "builtin" and rule.get("id") == rule_id:
                return rule.get("enabled", True)
        return False
