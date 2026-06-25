"""Structured episode memory + context control (blueprint 4.6).

The full raw transcript is never copied into every prompt. Each speaking agent
receives only: its own private notes, the latest opposing claim, relevant
earlier claims and the director's objective."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpeakerStat(BaseModel):
    turns: int = 0
    words: int = 0
    consecutive: int = 0


class EpisodeMemory(BaseModel):
    rolling_summary: str = ""
    recent_turns: list[str] = Field(default_factory=list, description="Last few compact lines.")
    unresolved_claims: list[str] = Field(default_factory=list)
    concessions: list[str] = Field(default_factory=list)
    covered_contentions: list[str] = Field(default_factory=list)
    speaker_stats: dict[str, SpeakerStat] = Field(default_factory=dict)
    last_speaker_id: str | None = None

    def record(self, speaker_id: str, words: int, compact_line: str, keep_recent: int = 4) -> None:
        stat = self.speaker_stats.setdefault(speaker_id, SpeakerStat())
        stat.turns += 1
        stat.words += words
        if self.last_speaker_id == speaker_id:
            stat.consecutive += 1
        else:
            stat.consecutive = 1
            # reset the previous speaker's run
            for sid, s in self.speaker_stats.items():
                if sid != speaker_id:
                    s.consecutive = 0
        self.last_speaker_id = speaker_id
        self.recent_turns.append(compact_line)
        self.recent_turns = self.recent_turns[-keep_recent:]
