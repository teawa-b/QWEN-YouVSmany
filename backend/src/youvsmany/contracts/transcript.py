"""Public transcript with stable turn IDs and scene cues (blueprint 4.4 LOCKED)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from youvsmany.contracts.enums import DebateState


# Words per second used to estimate spoken duration from text length.
# ~150 wpm conversational pace = 2.5 words/sec.
WORDS_PER_SECOND = 2.5

# Sentinel speaker id for non-spoken ritual captions (e.g. the voted-out gavel).
# Captions appear in the transcript but are not a debating voice, so metrics and
# opponent-reaction lookups skip turns carrying this id.
CAPTION_SPEAKER_ID = "caption"


class Turn(BaseModel):
    turn_id: str = Field(..., description="Stable, ordered id e.g. 't0007'.")
    index: int
    state: DebateState
    speaker_id: str
    speaker_name: str
    text: str
    contention_tag: str | None = None
    objective: str | None = Field(None, description="Director objective for this turn.")
    scene_cue: str = Field(
        "two_shot",
        description="Reusable animation/camera cue consumed later by staging.",
    )
    start_s: float = 0.0
    duration_s: float = 0.0

    @property
    def end_s(self) -> float:
        return round(self.start_s + self.duration_s, 3)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class Transcript(BaseModel):
    turns: list[Turn] = Field(default_factory=list)

    @property
    def total_duration_s(self) -> float:
        return round(sum(t.duration_s for t in self.turns), 3)

    def retime(self) -> None:
        """Recompute start/duration from word counts so timings stay consistent."""
        cursor = 0.0
        for t in self.turns:
            t.start_s = round(cursor, 3)
            t.duration_s = round(max(1.0, t.word_count / WORDS_PER_SECOND), 3)
            cursor += t.duration_s

    def speaker_turn_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self.turns:
            counts[t.speaker_id] = counts.get(t.speaker_id, 0) + 1
        return counts
