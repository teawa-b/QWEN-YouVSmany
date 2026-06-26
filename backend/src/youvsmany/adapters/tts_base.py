"""TTS provider protocol + result (blueprint 5.5, "audio as the master timeline").

Mirrors the LLM `Provider`/`LLMResult` split so the stage director can build the
master audio timeline offline (mock) or against Qwen Cloud (live) without code
changes. The synthesiser returns the *measured* duration of each line; the stage
director uses those durations as the master timeline, so visuals can never drift
off the cut."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

# Spoken pace used to estimate duration when no real audio is rendered. Matches
# the transcript's WORDS_PER_SECOND so mock timings stay consistent with Phase 1.
WORDS_PER_SECOND = 2.5


class TTSResult(BaseModel):
    duration_s: float
    voice_id: str
    sample_rate: int = 24000
    audio_ref: str | None = None  # path/URL to rendered audio, if any


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, *, voice_id: str, seed: int | None = None) -> TTSResult: ...
