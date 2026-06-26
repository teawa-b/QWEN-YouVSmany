"""Model adapters (blueprint: packages/qwen_adapter).

`Provider` is the protocol every backend implements. `QwenProvider` calls the
live OpenAI-compatible Qwen Cloud API; `MockProvider` is a deterministic offline
backend so the full pipeline + evals run reproducibly with no network."""

from youvsmany.adapters.base import LLMResult, Provider
from youvsmany.adapters.mock_provider import MockProvider
from youvsmany.adapters.qwen_provider import QwenProvider
from youvsmany.adapters.tts_base import TTSProvider, TTSResult
from youvsmany.adapters.mock_tts import MockTTS
from youvsmany.adapters.qwen_tts import QwenTTS
from youvsmany.adapters.factory import build_provider, build_tts_provider

__all__ = [
    "LLMResult",
    "Provider",
    "MockProvider",
    "QwenProvider",
    "TTSProvider",
    "TTSResult",
    "MockTTS",
    "QwenTTS",
    "build_provider",
    "build_tts_provider",
]
