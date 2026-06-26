"""Provider selection from settings."""

from __future__ import annotations

from youvsmany.adapters.base import Provider
from youvsmany.adapters.mock_provider import MockProvider
from youvsmany.adapters.mock_tts import MockTTS
from youvsmany.adapters.qwen_provider import QwenProvider
from youvsmany.adapters.qwen_tts import QwenTTS
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
        )
    return MockProvider()


def build_tts_provider(settings: Settings | None = None) -> TTSProvider:
    settings = settings or get_settings()
    if settings.tts_provider == "qwen":
        return QwenTTS(
            api_key=settings.qwen_api_key,
            base_url=settings.qwen_dashscope_url,
            model=settings.qwen_tts_model,
            timeout_s=settings.request_timeout_s,
        )
    return MockTTS()
