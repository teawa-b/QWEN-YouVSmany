from youvsmany.adapters.factory import build_provider, effective_tts_provider
from youvsmany.adapters.qwen_provider import QwenProvider
from youvsmany.config import Settings


def test_qwen_key_upgrades_mock_tts_to_cosyvoice():
    settings = Settings(provider="mock", qwen_api_key="sk-test", tts_provider="mock")

    assert effective_tts_provider(settings) == "qwen"


def test_without_qwen_key_tts_stays_mock():
    settings = Settings(provider="mock", qwen_api_key="", tts_provider="mock")

    assert effective_tts_provider(settings) == "mock"


def test_qwen_setting_builds_live_text_provider():
    provider = build_provider(Settings(provider="qwen", qwen_api_key="sk-test"))
    try:
        assert isinstance(provider, QwenProvider)
    finally:
        provider.close()
