from youvsmany.adapters import MockProvider
from youvsmany.agents import orchestrator
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import DebateState


def _run(seed=0, topic="Pineapple belongs on pizza", tags=("texture", "tradition", "culinary-innovation")):
    provider = MockProvider()
    brief = ShowBrief(topic=topic, seed=seed)
    return orchestrator.run_full(brief, provider=provider, suggested_tags=list(tags))


def test_reaches_locked_with_stable_ids_and_cues():
    ep = _run()
    assert ep.state == DebateState.LOCKED
    ids = [t.turn_id for t in ep.transcript.turns]
    assert len(ids) == len(set(ids)), "turn ids must be unique/stable"
    assert all(t.scene_cue for t in ep.transcript.turns), "every turn has a scene cue"


def test_exit_criterion_and_duration():
    ep = _run()
    assert ep.approved is True
    assert 12 <= len(ep.transcript.turns) <= 24
    assert 55.0 <= ep.transcript.total_duration_s <= 130.0
    assert len(ep.highlights) >= 3


def test_dominance_cap_no_three_in_a_row():
    ep = _run()
    speakers = [t.speaker_id for t in ep.transcript.turns]
    for i in range(2, len(speakers)):
        assert not (speakers[i] == speakers[i - 1] == speakers[i - 2]), \
            "no speaker should exceed the consecutive-turn cap"


def test_determinism_same_seed():
    a = _run(seed=3)
    b = _run(seed=3)
    assert [t.text for t in a.transcript.turns] == [t.text for t in b.transcript.turns]


def test_distinct_contentions():
    ep = _run()
    tags = [c.contention_tag for c in ep.cast.challengers]
    assert len(set(tags)) == len(tags)


def test_contentions_are_sequential_mini_duels_without_canned_labels():
    ep = _run(topic="the chicken came before egg", tags=("framing", "evidence", "consequences"))
    contentions = [t for t in ep.transcript.turns if t.state == DebateState.CONTENTIONS]
    ids = [t.speaker_id for t in contentions]

    protagonist_id = ep.cast.protagonist.character_id
    expected = []
    for challenger in ep.cast.challengers:
        expected.extend([challenger.character_id, protagonist_id, challenger.character_id, protagonist_id])
    assert ids == expected

    transcript_text = " ".join(t.text for t in ep.transcript.turns)
    forbidden = ["My objection is", "gap A", "gap B", "weak on", "I'll grant"]
    assert not any(phrase in transcript_text for phrase in forbidden)
