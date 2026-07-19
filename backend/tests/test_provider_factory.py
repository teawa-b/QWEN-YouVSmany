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


def test_qwen_disables_hybrid_thinking_for_fast_showrunner(monkeypatch):
    provider = build_provider(
        Settings(provider="qwen", qwen_api_key="sk-test", qwen_enable_thinking=False)
    )
    sent = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "Ready."}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }

    def fake_post(url, *, json):
        sent.update(json)
        return Response()

    monkeypatch.setattr(provider._client, "post", fake_post)
    try:
        provider.complete([{"role": "user", "content": "Make the short."}])
    finally:
        provider.close()

    assert sent["enable_thinking"] is False
