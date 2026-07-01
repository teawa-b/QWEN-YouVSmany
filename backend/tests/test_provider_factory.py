from youvsmany.adapters.factory import effective_tts_provider
from youvsmany.config import Settings


def test_qwen_key_upgrades_mock_tts_to_cosyvoice():
    settings = Settings(provider="mock", qwen_api_key="sk-test", tts_provider="mock")

    assert effective_tts_provider(settings) == "qwen"


def test_without_qwen_key_tts_stays_mock():
    settings = Settings(provider="mock", qwen_api_key="", tts_provider="mock")

    assert effective_tts_provider(settings) == "mock"
