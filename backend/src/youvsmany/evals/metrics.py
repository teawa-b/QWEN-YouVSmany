"""Quantitative debate metrics (blueprint 11.2 'Test')."""

from __future__ import annotations

from itertools import combinations

from pydantic import BaseModel

from youvsmany.agents.repetition import similarity
from youvsmany.contracts.episode import Episode
from youvsmany.contracts.transcript import CAPTION_SPEAKER_ID


class DebateMetrics(BaseModel):
    turns: int
    duration_s: float
    duration_in_target: bool
    contention_uniqueness: float  # 1.0 = all challenger contentions fully distinct
    repetition: float             # mean max pairwise similarity (lower is better)
    persona_adherence: float      # turns within each speaker's length range
    distinct_speakers: int


def _strip_topic(text: str, topic: str) -> str:
    """Remove the shared proposition words so we measure how the *objections*
    differ, not the subject they share."""
    topic_words = {w for w in topic.lower().split()}
    return " ".join(w for w in text.split() if w.lower() not in topic_words)


def _contention_uniqueness(ep: Episode) -> float:
    if not ep.cast:
        # fall back to tags seen on turns
        tags = [t.contention_tag for t in ep.transcript.turns if t.contention_tag]
        return (len(set(tags)) / len(tags)) if tags else 0.0
    topic = ep.brief.topic
    # Use the differentiating objection text (core contention minus the shared
    # proposition, plus supporting points) so substance, not subject, is scored.
    contentions = [
        _strip_topic(c.core_contention + " " + " ".join(c.supporting_points), topic)
        for c in ep.cast.challengers
    ]
    if len(contentions) < 2:
        return 1.0
    sims = [similarity(a, b) for a, b in combinations(contentions, 2)]
    return round(1.0 - (sum(sims) / len(sims)), 4)


def _repetition(ep: Episode) -> float:
    # Ritual captions (the voted-out gavel) are deterministic and near-identical
    # by design; they are not debating voices, so exclude them from repetition.
    texts = [t.text for t in ep.transcript.turns if t.speaker_id != CAPTION_SPEAKER_ID]
    if len(texts) < 2:
        return 0.0
    worst = []
    for i, t in enumerate(texts):
        prior = texts[:i]
        if prior:
            worst.append(max(similarity(t, p) for p in prior))
    return round(sum(worst) / len(worst), 4) if worst else 0.0


def _persona_adherence(ep: Episode) -> float:
    if not ep.cast:
        return 0.0
    ok = total = 0
    ranges = {}
    for c in [ep.cast.protagonist, *ep.cast.challengers]:
        if c.private_strategy:
            ranges[c.character_id] = c.private_strategy.response_length_range
    for t in ep.transcript.turns:
        rng = ranges.get(t.speaker_id)
        if not rng:
            continue
        total += 1
        # allow a small margin around the declared range
        if rng[0] - 6 <= t.word_count <= rng[1] + 10:
            ok += 1
    return round(ok / total, 4) if total else 0.0


def score_episode(ep: Episode) -> DebateMetrics:
    dur = ep.transcript.total_duration_s
    return DebateMetrics(
        turns=len(ep.transcript.turns),
        duration_s=dur,
        duration_in_target=20.0 <= dur <= 30.0,
        contention_uniqueness=_contention_uniqueness(ep),
        repetition=_repetition(ep),
        persona_adherence=_persona_adherence(ep),
        distinct_speakers=len(
            {t.speaker_id for t in ep.transcript.turns if t.speaker_id != CAPTION_SPEAKER_ID}
        ),
    )
