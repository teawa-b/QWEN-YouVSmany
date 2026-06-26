from youvsmany.adapters import MockProvider
from youvsmany.adapters.mock_tts import MockTTS
from youvsmany.agents import orchestrator
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.scene import AnimationTag, VisualPriority
from youvsmany.contracts.transcript import CAPTION_SPEAKER_ID


def _run(seed=0, tags=("framing", "evidence", "consequences")):
    return orchestrator.run_full(
        ShowBrief(topic="Pineapple belongs on pizza", seed=seed),
        provider=MockProvider(),
        suggested_tags=list(tags),
        tts=MockTTS(),
    )


def test_manifest_has_one_segment_per_turn():
    ep = _run()
    sm = ep.scene_manifest
    assert sm is not None
    assert len(sm.segments) == len(ep.transcript.turns)
    # Audio cues cover exactly the spoken (non-caption) turns.
    spoken = [t for t in ep.transcript.turns if t.speaker_id != CAPTION_SPEAKER_ID]
    assert len(sm.audio) == len(spoken)
    assert all(cue.speaker_id != CAPTION_SPEAKER_ID for cue in sm.audio)


def test_every_segment_camera_anchor_exists():
    ep = _run()
    sm = ep.scene_manifest
    anchor_names = {a.name for a in sm.stage.camera_anchors}
    for s in sm.segments:
        assert s.camera.anchor in anchor_names, f"{s.segment_id} -> unknown anchor {s.camera.anchor}"
        assert isinstance(s.animation_tag, AnimationTag)


def test_audio_is_the_master_timeline():
    ep = _run()
    sm = ep.scene_manifest
    # Segments tile the timeline with no gaps or overlaps, starting at 0.
    cursor = 0.0
    for s in sm.segments:
        assert abs(s.start_s - cursor) < 1e-6, f"gap at {s.segment_id}"
        assert s.end_s >= s.start_s
        cursor = s.end_s
    assert abs(sm.total_duration_s - cursor) < 1e-6
    # The spoken segments' durations are exactly the audio-cue durations (audio
    # drives the clock, so nothing can drift off the cut).
    by_id = {s.segment_id: s for s in sm.segments}
    for cue, turn in zip(sm.audio, [t for t in ep.transcript.turns if t.speaker_id != CAPTION_SPEAKER_ID]):
        seg = by_id[f"seg_{turn.index:02d}"]
        assert abs(cue.start_s - seg.start_s) < 1e-6
        assert abs(cue.end_s - seg.end_s) < 1e-6


def test_stage_is_protagonist_plus_challengers_no_moderator():
    ep = _run()
    sm = ep.scene_manifest
    roles = [m.role for m in sm.stage.marks]
    assert roles.count("protagonist") == 1
    assert roles.count("challenger") == len(ep.cast.challengers)
    assert "moderator" not in roles
    # Protagonist holds the dominant centre mark.
    centre = next(m for m in sm.stage.marks if m.role == "protagonist")
    assert centre.mark == "center"
    # Every speaking voice has a TTS voice assigned.
    assert set(sm.voice_map) == {c.character_id for c in ep.cast.all_speakers()}


def test_captions_are_priority_caption_and_unvoiced():
    ep = _run()
    sm = ep.scene_manifest
    caption_segs = [s for s in sm.segments if s.speaker_id == CAPTION_SPEAKER_ID]
    assert caption_segs, "expected voted-out caption beats"
    for s in caption_segs:
        assert s.visual_priority == VisualPriority.CAPTION
        assert s.short_candidate is False
        assert s.animation_tag == AnimationTag.REACTION_MIXED


def test_short_candidates_match_highlight_windows():
    ep = _run()
    sm = ep.scene_manifest
    index_by_id = {t.turn_id: t.index for t in ep.transcript.turns}
    covered = set()
    for h in ep.highlights:
        lo, hi = sorted((index_by_id[h.start_turn_id], index_by_id[h.end_turn_id]))
        covered.update(range(lo, hi + 1))
    for s in sm.segments:
        idx = int(s.segment_id.split("_")[1])
        spoken_hero = idx in covered and s.speaker_id != CAPTION_SPEAKER_ID
        assert s.short_candidate == spoken_hero


def test_manifest_is_deterministic():
    # episode_id is a random uuid; staging content is what must be reproducible.
    a = _run(seed=3).scene_manifest.model_dump(exclude={"episode_id"})
    b = _run(seed=3).scene_manifest.model_dump(exclude={"episode_id"})
    assert a == b


def test_crop_safe_flag_present():
    ep = _run()
    assert ep.scene_manifest.crop_safe_9x16 is True
    assert ep.scene_manifest.stage.crop_guide == "9:16"


def test_staged_against_a_premade_template():
    from youvsmany.agents.scene_templates import get_template

    ep = _run()
    ref = ep.scene_manifest.scene_template
    assert ref is not None
    # The chosen set is a real registry entry the renderer can load.
    tpl = get_template(ref.template_id)
    assert ref.asset_url == tpl.asset_url and ref.asset_url.endswith(".glb")
    # The set can seat the whole cast.
    assert tpl.max_challengers >= len(ep.cast.challengers)
    # Challenger marks stay symmetric inside the set's stage bounds.
    lo, hi = tpl.arc_x
    xs = [m.position.x for m in ep.scene_manifest.stage.marks if m.role == "challenger"]
    assert all(lo <= x <= hi for x in xs)
    assert abs(xs[0] + xs[-1]) < 1e-6  # mirror-symmetric about centre


def test_template_choice_is_deterministic_by_seed():
    from youvsmany.agents.scene_templates import select_template

    assert select_template(3, 7).template_id == select_template(3, 7).template_id
    a = _run(seed=4).scene_manifest.scene_template.template_id
    b = _run(seed=4).scene_manifest.scene_template.template_id
    assert a == b
