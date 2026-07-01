"""Live Qwen Cloud CosyVoice TTS adapter (DashScope tts_v2).

Synthesises each dialogue line with `cosyvoice-v3-plus`, writes the rendered mp3
into the served audio directory, and returns the clip reference plus an estimated
duration for the master timeline (blueprint 5.5). Playback in the browser is
event-driven off the real clip, so a word-count duration estimate is enough here.

Requires the `dashscope` SDK and network access; when either is unavailable the
factory falls back to the offline MockTTS so the pipeline never breaks. The exact
model id and voice ids are confirmed against the Qwen Cloud voice list
(cosyvoice-v3-plus ships `longanyang` / `longanhuan`).
"""

from __future__ import annotations

import hashlib
import os

from youvsmany.adapters.tts_base import WORDS_PER_SECOND, TTSResult


class CosyVoiceTTS:
    name = "cosyvoice"

    def __init__(
        self,
        api_key: str,
        model: str = "cosyvoice-v3-plus",
        *,
        audio_dir: str = "runs/audio",
        ws_url: str = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference",
        audio_route: str = "/audio",
    ) -> None:
        if not api_key:
            raise ValueError("QWEN_API_KEY is required for the cosyvoice TTS provider")
        import dashscope  # lazy: keep the SDK an optional dependency until used

        dashscope.api_key = api_key
        if ws_url:
            dashscope.base_websocket_api_url = ws_url
        self.model = model
        self.audio_dir = audio_dir
        self.audio_route = audio_route.rstrip("/")
        os.makedirs(self.audio_dir, exist_ok=True)

    def synthesize(self, text: str, *, voice_id: str, seed: int | None = None) -> TTSResult:
        from dashscope.audio.tts_v2 import SpeechSynthesizer

        # Deterministic, cacheable filename keyed on model+voice+text so re-runs of
        # the same episode reuse clips instead of re-synthesising.
        key = hashlib.sha1(f"{self.model}|{voice_id}|{text}".encode("utf-8")).hexdigest()[:16]
        fname = f"{key}.mp3"
        path = os.path.join(self.audio_dir, fname)

        if not os.path.exists(path):
            synth = SpeechSynthesizer(model=self.model, voice=voice_id)
            audio = synth.call(text)
            if not audio:
                # Model/network failure: no clip, but still return a timeline slot.
                return TTSResult(duration_s=self._estimate(text), voice_id=voice_id, audio_ref=None)
            with open(path, "wb") as f:
                f.write(audio)

        return TTSResult(
            duration_s=self._estimate(text),
            voice_id=voice_id,
            audio_ref=f"{self.audio_route}/{fname}",
        )

    @staticmethod
    def _estimate(text: str) -> float:
        return round(max(1.0, len(text.split()) / WORDS_PER_SECOND), 3)
