from youvsmany.adapters import MockProvider
from youvsmany.agents import orchestrator
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import DebateState, VisualPresentation
from youvsmany.contracts.transcript import CAPTION_SPEAKER_ID
from youvsmany.evals.metrics import score_episode


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


def test_cast_is_protagonist_plus_challengers_only():
    ep = _run()
    # No moderator voice: the cast is 1 main + N opposing, and the only speakers
    # in the transcript are those debating voices (captions do not count).
    assert ep.cast.moderator is None
    assert len(ep.cast.all_speakers()) == 1 + len(ep.cast.challengers)
    spoken = {t.speaker_id for t in ep.transcript.turns if t.speaker_id != CAPTION_SPEAKER_ID}
    assert spoken == {c.character_id for c in ep.cast.all_speakers()}
    assert score_episode(ep).distinct_speakers == 1 + len(ep.cast.challengers)


def test_mock_cast_marks_female_presenting_speakers():
    ep = _run()
    by_name = {c.display_name: c.visual_presentation for c in ep.cast.all_speakers()}
    assert by_name["Iris"] == VisualPresentation.FEMALE
    assert by_name["Mara"] == VisualPresentation.FEMALE
    assert by_name["Tom"] == VisualPresentation.MALE


def test_dominance_cap_no_three_in_a_row():
    ep = _run()
    speakers = [t.speaker_id for t in ep.transcript.turns]
    for i in range(2, len(speakers)):
        assert not (speakers[i] == speakers[i - 1] == speakers[i - 2]), (
            "no speaker should exceed the consecutive-turn cap"
        )


def test_determinism_same_seed():
    a = _run(seed=3)
    b = _run(seed=3)
    assert [t.text for t in a.transcript.turns] == [t.text for t in b.transcript.turns]


def test_distinct_contentions():
    ep = _run()
    tags = [c.contention_tag for c in ep.cast.challengers]
    assert len(set(tags)) == len(tags)


def test_shared_claim_room_crossfire():
    ep = _run(topic="the chicken came before egg", tags=("framing", "evidence", "consequences"))
    protagonist_id = ep.cast.protagonist.character_id
    contentions = [t for t in ep.transcript.turns if t.state == DebateState.CONTENTIONS]
    claim_cards = [t for t in contentions if t.scene_cue == "claim_card"]
    assert len(claim_cards) == 1
    assert claim_cards[0].speaker_id == protagonist_id
    assert "my claim is that" in claim_cards[0].text.lower()

    after_claim = contentions[1:]
    first_wave = after_claim[: len(ep.cast.challengers)]
    assert [t.speaker_id for t in first_wave] == [c.character_id for c in ep.cast.challengers]

    room_answer = after_claim[len(ep.cast.challengers)]
    assert room_answer.speaker_id == protagonist_id

    followups = after_claim[len(ep.cast.challengers) + 1 :]
    assert len(followups) >= len(ep.cast.challengers) * 2
    assert len(followups) % 2 == 0
    for i in range(0, len(followups), 2):
        assert followups[i].speaker_id != protagonist_id
        assert followups[i + 1].speaker_id == protagonist_id

    transcript_text = " ".join(t.text for t in ep.transcript.turns)
    forbidden = ["My objection is", "gap A", "gap B", "weak on", "I'll grant", "voted out"]
    assert not any(phrase in transcript_text for phrase in forbidden)


def test_every_challenger_gets_opening_and_followup_pressure():
    ep = _run()
    for challenger in ep.cast.challengers:
        challenger_turns = [
            t for t in ep.transcript.turns if t.speaker_id == challenger.character_id
        ]
        assert len(challenger_turns) >= 2
