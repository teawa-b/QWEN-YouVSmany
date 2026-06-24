"""Repetition / semantic-similarity checks (blueprint 4.5 'Repetition rule').

No network embeddings: similarity blends a normalized token Jaccard with a
sequence ratio. Cheap, deterministic and good enough to catch an agent
restating an earlier argument."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "is", "are",
    "that", "this", "it", "you", "i", "we", "they", "for", "with", "as", "at",
    "be", "by", "not", "so", "if", "then", "than", "my", "your",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return round(0.6 * jaccard + 0.4 * seq, 4)


def max_similarity(candidate: str, prior: list[str]) -> float:
    return max((similarity(candidate, p) for p in prior), default=0.0)


def is_repetitive(candidate: str, prior: list[str], threshold: float = 0.6) -> bool:
    return max_similarity(candidate, prior) >= threshold
