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


def _claim_segments(ep):
    """Split the CONTENTIONS turns into Surrounded-style claim segments: each one
    opens on a protagonist claim card and closes on a moderator voted-out gavel."""
    contentions = [t for t in ep.transcript.turns if t.state == DebateState.CONTENTIONS]
    segments, current = [], []
    for t in contentions:
        if t.scene_cue == "claim_card" and current:
            segments.append(current)
            current = []
        current.append(t)
    if current:
        segments.append(current)
    return segments


def test_claim_segments_follow_surrounded_rhythm():
    ep = _run(topic="the chicken came before egg", tags=("framing", "evidence", "consequences"))
    protagonist_id = ep.cast.protagonist.character_id
    moderator_id = ep.cast.moderator.character_id

    segments = _claim_segments(ep)
    # One claim segment per challenger, in cast order.
    assert len(segments) == len(ep.cast.challengers)

    for seg_index, (segment, challenger) in enumerate(zip(segments, ep.cast.challengers)):
        # Opens on the protagonist raising a claim to the room.
        head = segment[0]
        assert head.scene_cue == "claim_card"
        assert head.speaker_id == protagonist_id
        ordinal = "first claim" if seg_index == 0 else "next claim"
        assert ordinal in head.text.lower()

        # Closes on the moderator voting the challenger out, by name.
        tail = segment[-1]
        assert tail.scene_cue == "voted_out"
        assert tail.speaker_id == moderator_id
        assert challenger.display_name in tail.text

        # The duel in between is a strict one-on-one: challenger then protagonist,
        # alternating, never two of the same speaker back to back.
        duel = segment[1:-1]
        assert len(duel) >= 2 and len(duel) % 2 == 0
        for i, turn in enumerate(duel):
            expected = challenger.character_id if i % 2 == 0 else protagonist_id
            assert turn.speaker_id == expected

    transcript_text = " ".join(t.text for t in ep.transcript.turns)
    forbidden = ["My objection is", "gap A", "gap B", "weak on", "I'll grant"]
    assert not any(phrase in transcript_text for phrase in forbidden)


def test_every_challenger_is_greeted_and_voted_out():
    ep = _run()
    voted_out = [t for t in ep.transcript.turns if t.scene_cue == "voted_out"]
    claim_cards = [t for t in ep.transcript.turns if t.scene_cue == "claim_card"]
    assert len(voted_out) == len(claim_cards) == len(ep.cast.challengers)
    # Each duel opens with a handshake from the challenger.
    greetings = ("nice to meet you", "good to meet you", "how's it going")
    for challenger in ep.cast.challengers:
        first_line = next(
            t.text.lower() for t in ep.transcript.turns if t.speaker_id == challenger.character_id
        )
        assert any(g in first_line for g in greetings)
