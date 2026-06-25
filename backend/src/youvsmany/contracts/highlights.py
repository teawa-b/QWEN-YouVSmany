"""Highlight (clip) candidates (blueprint 4.7).

The Clip Curator evaluates turn *windows* rather than isolated lines. A useful
15-40s short usually contains setup, clash and payoff."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Weighted highlight score (blueprint 4.7).
HIGHLIGHT_WEIGHTS = {
    "hook": 0.25,
    "conflict": 0.20,
    "clarity": 0.15,
    "novelty": 0.15,
    "emotion": 0.10,
    "self_containment": 0.10,
    "visual_potential": 0.05,
}


class HighlightScore(BaseModel):
    hook: float = Field(0.0, ge=0.0, le=1.0)
    conflict: float = Field(0.0, ge=0.0, le=1.0)
    clarity: float = Field(0.0, ge=0.0, le=1.0)
    novelty: float = Field(0.0, ge=0.0, le=1.0)
    emotion: float = Field(0.0, ge=0.0, le=1.0)
    self_containment: float = Field(0.0, ge=0.0, le=1.0)
    visual_potential: float = Field(0.0, ge=0.0, le=1.0)
    penalty: float = Field(0.0, ge=0.0, description="Subtracted for pronoun/context/length issues.")

    @property
    def total(self) -> float:
        base = sum(getattr(self, k) * w for k, w in HIGHLIGHT_WEIGHTS.items())
        return round(max(0.0, base - self.penalty), 4)


class HighlightCandidate(BaseModel):
    start_turn_id: str
    end_turn_id: str
    start_s: float
    end_s: float
    contention_tag: str | None = None
    score: HighlightScore
    summary: str = ""

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)
