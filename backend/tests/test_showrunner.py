import json

from youvsmany.adapters.base import LLMResult
from youvsmany.adapters.mock_tts import MockTTS
from youvsmany.agents import orchestrator
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import DebateState


class FakeQwenProvider:
    name = "qwen"
    model = "qwen-test"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        draft = {
            "thesis": "Remote work makes well-designed teams more productive",
            "cast_names": ["Avery", "Jordan", "Mina"],
            "visual_presentations": ["male", "female", "neutral"],
            "challenger_angles": ["blocker resolution", "collaboration drift"],
            "lines": [
                "I back remote work because deep focus creates better output.",
                "Deep focus fails when teammates cannot resolve blockers together.",
                "And weak collaboration quietly turns flexibility into duplicated work.",
                "Fair pressure, but clear rituals keep distributed teams aligned.",
                "Rituals cannot replace spontaneous context between teammates, Avery.",
                "True, but documented decisions preserve context beyond one conversation.",
                "Remote work wins when teams design communication deliberately together.",
            ],
        }
        return LLMResult(text=json.dumps(draft), input_tokens=240, output_tokens=190)


def test_live_qwen_uses_one_showrunner_call_for_complete_short():
    provider = FakeQwenProvider()
    episode = orchestrator.run_full(
        ShowBrief(
            topic="Remote work makes teams more productive",
            target_duration_s=30,
            num_challengers=2,
            seed=7,
        ),
        provider=provider,
        suggested_tags=["focus", "collaboration"],
        tts=MockTTS(),
    )

    assert provider.calls == 1
    assert episode.run_report.llm_calls == 1
    assert episode.run_report.provider == "qwen"
    assert episode.state == DebateState.LOCKED
    assert episode.approved is True
    assert len(episode.cast.all_speakers()) == 3
    assert len(episode.transcript.turns) == 7
    assert all(8 <= turn.word_count <= 10 for turn in episode.transcript.turns)
    assert 20 <= episode.transcript.total_duration_s <= 30
    assert episode.scene_manifest.total_duration_s <= 30
