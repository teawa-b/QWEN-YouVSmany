"""Runtime configuration, loaded from environment (.env supported)."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # optional dependency; .env is convenience only
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    provider: str = os.getenv("YVM_PROVIDER", "mock").lower()
    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")
    qwen_base_url: str = os.getenv(
        "QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    qwen_text_model: str = os.getenv("QWEN_TEXT_MODEL", "qwen3.7-plus")
    # qwen3.7-plus enables hybrid thinking by default. The showrunner schema is
    # intentionally compact, so direct generation is much faster and cheaper.
    qwen_enable_thinking: bool = _env_bool("QWEN_ENABLE_THINKING", False)
    # TTS (Phase 2): Qwen Cloud CosyVoice via the DashScope tts_v2 SDK.
    qwen_dashscope_url: str = os.getenv(
        "QWEN_DASHSCOPE_URL", "https://dashscope-intl.aliyuncs.com/api/v1"
    )
    qwen_dashscope_api_key: str = os.getenv(
        "DASHSCOPE_API_KEY", os.getenv("QWEN_API_KEY", "")
    )
    qwen_image_edit_url: str = os.getenv(
        "QWEN_IMAGE_EDIT_URL",
        "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    )
    qwen_image_edit_model: str = os.getenv("QWEN_IMAGE_EDIT_MODEL", "qwen-image-edit-max")
    # HappyHorse video edit (async: create task -> poll /tasks/{id}).
    qwen_video_edit_url: str = os.getenv(
        "QWEN_VIDEO_EDIT_URL",
        "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
    )
    qwen_task_url_base: str = os.getenv(
        "QWEN_TASK_URL_BASE", "https://dashscope-intl.aliyuncs.com/api/v1/tasks"
    )
    qwen_video_edit_model: str = os.getenv("QWEN_VIDEO_EDIT_MODEL", "happyhorse-1.0-video-edit")
    # Public base URL of this backend, used to build media URLs DashScope can
    # fetch. Empty = derive from the incoming request.
    public_base_url: str = os.getenv("YVM_PUBLIC_BASE_URL", "")
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
    media_dir: str = os.getenv("YVM_MEDIA_DIR", "runs/media")
    realistic_ref_dir: str = os.getenv(
        "YVM_REALISTIC_REF_DIR", "runs/media/reference/realistic-v1"
    )
    # Persistent reusable character identity bank (generated once, reused by
    # every episode instead of regenerating identities per run).
    character_bank_dir: str = os.getenv(
        "YVM_CHARACTER_BANK_DIR", "runs/media/reference/characters-v1"
    )
    # MP4 conversions of the starter WebM clips (HappyHorse rejects WebM).
    reference_mp4_dir: str = os.getenv("YVM_REFERENCE_MP4_DIR", "runs/media/reference-mp4")
    # Generated HappyHorse segment videos + stitched conversation.
    video_out_dir: str = os.getenv("YVM_VIDEO_OUT_DIR", "runs/media/videos")
    request_timeout_s: float = float(os.getenv("QWEN_TIMEOUT_S", "120"))


def get_settings() -> Settings:
    return Settings()
