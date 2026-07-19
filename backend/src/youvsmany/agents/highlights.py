"""Clip Curator: highlight detection over turn windows (blueprint 4.7).

Evaluates sliding windows (setup -> clash -> payoff), scores each with the
weighted formula and penalises pronoun/context dependence and over-length, then
returns top candidates spread across different contentions."""

from __future__ import annotations

import re

from youvsmany.agents.repetition import similarity
from youvsmany.contracts.enums import Role
from youvsmany.contracts.highlights import HighlightCandidate, HighlightScore
from youvsmany.contracts.transcript import Transcript, Turn

_DANGLING_PRONOUN = re.compile(r"^\s*(it|they|that|this|those|these|he|she)\b", re.IGNORECASE)
_HOOK_WORDS = ("simple", "here's", "concretely", "answer that", "the crack", "breaks")
_EMOTION_WORDS = ("honestly", "head on", "stubborn", "dodging", "burden", "lazy", "wins", "loses")

MIN_WINDOW_S = 5.0
MAX_WINDOW_S = 14.0


def _role_of(turn: Turn, transcript: Transcript) -> str:
    return turn.speaker_id


def score_window(window: list[Turn]) -> HighlightScore:
    joined = " ".join(t.text for t in window)
    speakers = {t.speaker_id for t in window}
    tags = {t.contention_tag for t in window if t.contention_tag}

    conflict = min(1.0, 0.4 * (len(speakers) - 1) + 0.2 * (len(window) - 1))
    hook = min(1.0, sum(w in joined.lower() for w in _HOOK_WORDS) / 3 + 0.3)
    clarity = 1.0 if 18 <= len(joined.split()) <= 90 else 0.5
    novelty = min(1.0, 0.4 + 0.3 * len(tags))
    emotion = min(1.0, sum(w in joined.lower() for w in _EMOTION_WORDS) / 3 + 0.2)
    # self-containment: low overlap with what came before is good; here we proxy
    # via not starting on a dangling pronoun.
    self_containment = 0.4 if _DANGLING_PRONOUN.match(window[0].text) else 0.9
    visual = 0.6

    penalty = 0.0
    if _DANGLING_PRONOUN.match(window[0].text):
        penalty += 0.1
    dur = sum(t.duration_s for t in window)
    if dur > MAX_WINDOW_S:
        penalty += 0.15
    return HighlightScore(
        hook=round(hook, 3),
        conflict=round(conflict, 3),
        clarity=clarity,
        novelty=round(novelty, 3),
        emotion=round(emotion, 3),
        self_containment=self_containment,
        visual_potential=visual,
        penalty=round(penalty, 3),
    )


def detect_highlights(
    transcript: Transcript, *, top_k: int = 3, max_turns_per_window: int = 4
) -> list[HighlightCandidate]:
    turns = transcript.turns
    candidates: list[HighlightCandidate] = []
    for i in range(len(turns)):
        for span in range(2, max_turns_per_window + 1):
            window = turns[i : i + span]
            if len(window) < 2:
                continue
            dur = sum(t.duration_s for t in window)
            if dur < MIN_WINDOW_S or dur > MAX_WINDOW_S:
                continue
            score = score_window(window)
            tag = next((t.contention_tag for t in window if t.contention_tag), None)
            candidates.append(
                HighlightCandidate(
                    start_turn_id=window[0].turn_id,
                    end_turn_id=window[-1].turn_id,
                    start_s=window[0].start_s,
                    end_s=window[-1].end_s,
                    contention_tag=tag,
                    score=score,
                    summary=_summary(window),
                )
            )
    candidates.sort(key=lambda c: c.score.total, reverse=True)
    return _diversify(candidates, top_k)


def _summary(window: list[Turn]) -> str:
    return " / ".join(f"{t.speaker_name}: {t.text[:48]}" for t in window)


def _diversify(candidates: list[HighlightCandidate], top_k: int) -> list[HighlightCandidate]:
    """Prefer clips covering *different* contentions and non-overlapping spans."""
    chosen: list[HighlightCandidate] = []
    used_tags: set[str] = set()
    used_spans: list[tuple[float, float]] = []

    def overlaps(c: HighlightCandidate) -> bool:
        return any(not (c.end_s <= s or c.start_s >= e) for s, e in used_spans)

    for c in candidates:
        if len(chosen) >= top_k:
            break
        if overlaps(c):
            continue
        if c.contention_tag and c.contention_tag in used_tags:
            continue
        chosen.append(c)
        used_spans.append((c.start_s, c.end_s))
        if c.contention_tag:
            used_tags.add(c.contention_tag)
    # backfill if diversity left us short
    for c in candidates:
        if len(chosen) >= top_k:
            break
        if c not in chosen and not overlaps(c):
            chosen.append(c)
            used_spans.append((c.start_s, c.end_s))
    return chosen
