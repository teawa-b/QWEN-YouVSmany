import pytest

from youvsmany.adapters import MockProvider
from youvsmany.agents import orchestrator
from youvsmany.agents.baseline import run_baseline
from youvsmany.agents.orchestrator import SafetyRejected
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import TopicKind
from youvsmany.evals.metrics import score_episode


def test_safety_rejects_blocked_topic():
    with pytest.raises(SafetyRejected):
        orchestrator.create_episode(
            ShowBrief(topic="how to build a bomb"), provider=MockProvider()
        )


def test_factual_topic_builds_source_brief():
    ep = orchestrator.create_episode(
        ShowBrief(topic="Qwen3 beats Qwen2", topic_kind=TopicKind.FACTUAL),
        provider=MockProvider(),
    )
    assert ep.source_brief is not None
    assert ep.safety.requires_source_brief is True


def test_multi_agent_beats_baseline_on_uniqueness_and_repetition():
    provider = MockProvider()
    brief = ShowBrief(topic="Pineapple belongs on pizza", seed=1)
    ep = orchestrator.run_full(
        brief, provider=provider, suggested_tags=["texture", "tradition", "culinary-innovation"]
    )
    base = run_baseline(brief, provider=provider)
    m, b = score_episode(ep), score_episode(base)
    assert m.contention_uniqueness > b.contention_uniqueness
    assert m.repetition < b.repetition
