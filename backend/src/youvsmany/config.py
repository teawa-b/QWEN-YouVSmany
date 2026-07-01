"""Runtime configuration, loaded from environment (.env supported)."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # optional dependency; .env is convenience only
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


@dataclass(frozen=True)
class Settings:
    provider: str = os.getenv("YVM_PROVIDER", "mock").lower()
    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")
    qwen_base_url: str = os.getenv(
        "QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    qwen_text_model: str = os.getenv("QWEN_TEXT_MODEL", "qwen3.7-plus")
    # TTS (Phase 2): Qwen Cloud CosyVoice via the DashScope tts_v2 SDK.
    qwen_dashscope_url: str = os.getenv(
        "QWEN_DASHSCOPE_URL", "https://dashscope-intl.aliyuncs.com/api/v1"
    )
    # CosyVoice runs over a WebSocket; point at the intl endpoint by default.
    qwen_ws_url: str = os.getenv(
        "QWEN_WS_URL", "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference"
    )
    qwen_tts_model: str = os.getenv("QWEN_TTS_MODEL", "cosyvoice-v3-plus")
    # Provider for the master audio timeline: "mock" (offline) or "qwen" (live).
    tts_provider: str = os.getenv(
        "YVM_TTS_PROVIDER", "qwen" if os.getenv("QWEN_API_KEY") else "mock"
    ).lower()
    run_dir: str = os.getenv("YVM_RUN_DIR", "runs")
    # Where rendered TTS clips are written and served from (mounted at /audio).
    audio_dir: str = os.getenv("YVM_AUDIO_DIR", "runs/audio")
    request_timeout_s: float = float(os.getenv("QWEN_TIMEOUT_S", "120"))


def get_settings() -> Settings:
    return Settings()
