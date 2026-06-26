"""Live Qwen Cloud TTS adapter (DashScope).

Synthesises a dialogue line with a Qwen Cloud TTS model and returns the rendered
clip reference plus its measured duration, which becomes the master timeline for
that beat (blueprint 5.5). Network access to DashScope is required at runtime;
when unavailable, select the mock TTS instead.

The DashScope contract is verified live (see PROGRESS.md). This adapter targets
the multimodal-generation surface (model `qwen-tts`), reads the returned audio
URL, and falls back to a word-count duration estimate if the response does not
carry an explicit duration — so a timeline can always be produced.
"""

from __future__ import annotations

import httpx

from youvsmany.adapters.tts_base import WORDS_PER_SECOND, TTSResult

_GEN_PATH = "/services/aigc/multimodal-generation/generation"


class QwenTTS:
    name = "qwen-tts"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "qwen-tts",
        *,
        timeout_s: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError("QWEN_API_KEY is required for the qwen TTS provider")
        self.model = model
        # DashScope native (non-OpenAI) API root, e.g.
        # https://dashscope-intl.aliyuncs.com/api/v1
        self._url = base_url.rstrip("/") + _GEN_PATH
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def synthesize(self, text: str, *, voice_id: str, seed: int | None = None) -> TTSResult:
        body: dict = {
            "model": self.model,
            "input": {"text": text, "voice": voice_id},
            "parameters": {},
        }
        if seed is not None:
            body["parameters"]["seed"] = seed
        resp = self._client.post(self._url, json=body)
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {}) or {}
        audio = output.get("audio", {}) or {}
        audio_ref = audio.get("url") or audio.get("audio")
        duration = audio.get("duration")
        if duration is None:
            # Fall back to a pace estimate so the master timeline can still be laid.
            duration = max(1.0, len(text.split()) / WORDS_PER_SECOND)
        return TTSResult(
            duration_s=round(float(duration), 3),
            voice_id=voice_id,
            audio_ref=audio_ref,
        )

    def close(self) -> None:  # pragma: no cover
        self._client.close()
