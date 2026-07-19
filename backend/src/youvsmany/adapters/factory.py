"""Provider selection from settings."""

from __future__ import annotations

from youvsmany.adapters.base import Provider
from youvsmany.adapters.cosyvoice_tts import CosyVoiceTTS
from youvsmany.adapters.mock_provider import MockProvider
from youvsmany.adapters.mock_tts import MockTTS
from youvsmany.adapters.qwen_provider import QwenProvider
from youvsmany.adapters.tts_base import TTSProvider
from youvsmany.config import Settings, get_settings


def build_provider(settings: Settings | None = None) -> Provider:
    settings = settings or get_settings()
    if settings.provider == "qwen":
        return QwenProvider(
            api_key=settings.qwen_api_key,
            base_url=settings.qwen_base_url,
            model=settings.qwen_text_model,
            timeout_s=settings.request_timeout_s,
            enable_thinking=settings.qwen_enable_thinking,
        )
    return MockProvider()


def effective_tts_provider(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    # Mock debates should still use live CosyVoice clips when the hosted backend
    # has a Qwen key. This lets Railway run deterministic text generation while
    # avoiding robotic browser SpeechSynthesis.
    if settings.qwen_api_key and settings.tts_provider in {"mock", "qwen", "cosyvoice"}:
        return "qwen"
    return settings.tts_provider


def build_tts_provider(settings: Settings | None = None) -> TTSProvider:
    settings = settings or get_settings()
    if effective_tts_provider(settings) == "qwen":
        # Fall back to offline mock rather than crash if the key or the dashscope
        # SDK is missing, so a running app degrades gracefully to browser voices.
        try:
            return CosyVoiceTTS(
                api_key=settings.qwen_api_key,
                model=settings.qwen_tts_model,
                audio_dir=settings.audio_dir,
                ws_url=settings.qwen_ws_url,
            )
        except (ImportError, ValueError) as e:  # pragma: no cover - env dependent
            print(f"[youvsmany] cosyvoice TTS unavailable ({e}); using mock TTS")
            return MockTTS()
    return MockTTS()
