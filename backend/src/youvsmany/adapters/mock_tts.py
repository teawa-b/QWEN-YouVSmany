"""Deterministic offline TTS.

Renders no real audio; it returns a stable duration estimate for each line so the
master audio timeline (and the whole scene manifest) can be built and tested with
no network — the audio analogue of the offline `MockProvider`."""

from __future__ import annotations

from youvsmany.adapters.tts_base import WORDS_PER_SECOND, TTSResult


class MockTTS:
    name = "mock-tts"

    def __init__(self, model: str = "mock-tts-1") -> None:
        self.model = model

    def synthesize(self, text: str, *, voice_id: str, seed: int | None = None) -> TTSResult:
        words = max(1, len(text.split()))
        # Floor of 1.0s mirrors the transcript retime so a one-word beat still
        # occupies a real slot on the timeline.
        duration = round(max(1.0, words / WORDS_PER_SECOND), 3)
        return TTSResult(duration_s=duration, voice_id=voice_id, audio_ref=None)
