"""Stage Director (blueprint 5): LOCKED transcript -> renderer-neutral SceneManifest.

Turns a finished debate into a timecoded staging plan a Three.js player can drive:
a fixed stage layout, camera anchors, the six-state animation grammar, and a
master audio timeline built from TTS. Audio is the master clock — segment timings
come from the synthesised line durations, so no later visual can drift off the cut.
"""

from __future__ import annotations

from youvsmany.adapters.tts_base import WORDS_PER_SECOND, TTSProvider
from youvsmany.agents.scene_templates import select_template
from youvsmany.contracts.character import Cast
from youvsmany.contracts.enums import DebateState, VisualPresentation
from youvsmany.contracts.episode import Episode
from youvsmany.contracts.scene import (
    AnimationTag,
    AudioCue,
    Blocking,
    CameraAnchor,
    CameraShot,
    CameraSpec,
    CharacterRef,
    SceneManifest,
    SceneSegment,
    SceneTemplate,
    SceneTemplateRef,
    StageLayout,
    StageMark,
    Vec3,
    VisualPriority,
)
from youvsmany.media.characters import character_ref_payload, select_character_visuals
from youvsmany.contracts.transcript import (
    CAPTION_SPEAKER_ID,
    MAX_EPISODE_DURATION_S,
    Transcript,
)

# Qwen Cloud CosyVoice-v3-plus system voices: one male (longanyang), one female
# (longanhuan), both English-capable.
COSYVOICE_MALE = "longanyang"
COSYVOICE_FEMALE = "longanhuan"
VOICE_POOL = [COSYVOICE_MALE, COSYVOICE_FEMALE]

# How a non-spoken caption beat (the voted-out gavel) holds the screen.
_CAPTION_HOLD_FLOOR_S = 1.0

# Pose that each animation tag implies for the speaker (blocking).
_POSE = {
    AnimationTag.SPEAK_EMPHATIC: "stand_emphatic",
    AnimationTag.SPEAK_EXPLAIN: "speak_neutral",
    AnimationTag.CHALLENGE_LEAN: "lean_forward",
    AnimationTag.CONCEDE_NOD: "soften_nod",
    AnimationTag.REACTION_MIXED: "crowd_react",
    AnimationTag.LISTEN_NEUTRAL: "idle_listen",
}

_INTENSITY = {
    AnimationTag.SPEAK_EMPHATIC: 0.85,
    AnimationTag.CHALLENGE_LEAN: 0.8,
    AnimationTag.SPEAK_EXPLAIN: 0.55,
    AnimationTag.REACTION_MIXED: 0.6,
    AnimationTag.CONCEDE_NOD: 0.4,
    AnimationTag.LISTEN_NEUTRAL: 0.3,
}


def build_scene_manifest(ep: Episode, tts: TTSProvider) -> SceneManifest:
    cast: Cast = ep.cast  # type: ignore[assignment]
    voice_map = _assign_voices(cast)
    template = select_template(len(cast.challengers), ep.brief.seed)
    stage = _build_stage(cast, template)
    covered = _highlight_turn_ids(ep)

    segments: list[SceneSegment] = []
    audio: list[AudioCue] = []
    cursor = 0.0
    for turn in ep.transcript.turns:
        if cursor >= MAX_EPISODE_DURATION_S:
            break
        is_caption = turn.speaker_id == CAPTION_SPEAKER_ID
        if is_caption:
            duration = min(
                round(max(_CAPTION_HOLD_FLOOR_S, turn.word_count / WORDS_PER_SECOND), 3),
                MAX_EPISODE_DURATION_S - cursor,
            )
        else:
            voice_id = voice_map[turn.speaker_id]
            res = tts.synthesize(turn.text, voice_id=voice_id, seed=ep.brief.seed + turn.index)
            duration = min(res.duration_s, max(0.0, MAX_EPISODE_DURATION_S - cursor))
            audio.append(
                AudioCue(
                    dialogue_id=turn.turn_id,
                    start_s=round(cursor, 3),
                    end_s=round(cursor + duration, 3),
                    speaker_id=turn.speaker_id,
                    voice_id=voice_id,
                    text=turn.text,
                    audio_ref=res.audio_ref,
                )
            )

        start_s = round(cursor, 3)
        cursor += duration
        end_s = round(cursor, 3)

        tag = _animation_tag(turn, is_caption)
        camera = _camera(turn, cast, is_caption)
        hero = turn.turn_id in covered
        segments.append(
            SceneSegment(
                segment_id=f"seg_{turn.index:02d}",
                start_s=start_s,
                end_s=end_s,
                speaker_id=turn.speaker_id,
                dialogue=turn.text,
                emotion=_emotion(turn, is_caption),
                animation_tag=tag,
                intensity=_INTENSITY[tag],
                camera=camera,
                blocking=Blocking(
                    speaker_pose=_POSE[tag],
                    listeners="mixed_reaction" if is_caption or hero else "attentive",
                ),
                required_characters=_required(turn, cast, ep.transcript, is_caption),
                visual_priority=(
                    VisualPriority.CAPTION
                    if is_caption
                    else (VisualPriority.HERO if hero else VisualPriority.STANDARD)
                ),
                short_candidate=hero and not is_caption,
                scene_cue=turn.scene_cue,
            )
        )

        if cursor >= MAX_EPISODE_DURATION_S:
            break

    return SceneManifest(
        episode_id=ep.episode_id,
        scene_template=SceneTemplateRef(
            template_id=template.template_id,
            display_name=template.display_name,
            asset_url=template.asset_url,
            environment=template.environment,
        ),
        stage=stage,
        segments=segments,
        audio=audio,
        voice_map=voice_map,
        character_refs=_assign_character_refs(cast, ep.brief.seed),
        total_duration_s=round(cursor, 3),
        crop_safe_9x16=True,
    )


# --- mapping helpers --------------------------------------------------


def _assign_character_refs(cast: Cast, seed: int) -> dict[str, CharacterRef]:
    """Cast persistent roster identities onto this episode's speakers, so media
    generation reuses pre-generated identity images instead of inventing new
    characters per run."""
    speakers = [(c.character_id, str(c.visual_presentation.value)) for c in cast.all_speakers()]
    selected = select_character_visuals(speakers, seed)
    return {
        character_id: CharacterRef(**character_ref_payload(entry))
        for character_id, entry in selected.items()
    }


def _assign_voices(cast: Cast) -> dict[str, str]:
    speakers = cast.all_speakers()
    assigned: dict[str, str] = {}
    for i, c in enumerate(speakers):
        if c.visual_presentation == VisualPresentation.FEMALE:
            voice = COSYVOICE_FEMALE
        elif c.visual_presentation == VisualPresentation.MALE:
            voice = COSYVOICE_MALE
        else:
            voice = VOICE_POOL[i % len(VOICE_POOL)]
        assigned[c.character_id] = voice
    return assigned


def _challenger_x(template: SceneTemplate, i: int, n: int) -> float:
    """Symmetric placement inside the set's stage bounds, so N challengers stay
    balanced regardless of the set's seating capacity."""
    lo, hi = template.arc_x
    return round(lo + (hi - lo) * i / (n - 1), 3) if n > 1 else round((lo + hi) / 2, 3)


def _build_stage(cast: Cast, template: SceneTemplate) -> StageLayout:
    """Place the cast on marks inside the premade set, and reuse its camera
    anchors (rebinding the protagonist look-at to the actual protagonist id)."""
    p = template.protagonist_pos
    marks = [
        StageMark(
            character_id=cast.protagonist.character_id,
            role="protagonist",
            mark="center",
            position=Vec3(x=p.x, y=p.y, z=p.z),
            face_to="camera",
        )
    ]
    n = len(cast.challengers)
    for i, ch in enumerate(cast.challengers):
        marks.append(
            StageMark(
                character_id=ch.character_id,
                role="challenger",
                mark=f"arc_{i + 1}",
                position=Vec3(x=_challenger_x(template, i, n), y=0.0, z=template.arc_z),
                face_to=cast.protagonist.character_id,
            )
        )

    # The set's predefined cameras, with the protagonist sentinel resolved.
    anchors: list[CameraAnchor] = []
    for a in template.base_anchors:
        look_at = cast.protagonist.character_id if a.look_at == "protagonist" else a.look_at
        anchors.append(a.model_copy(update={"look_at": look_at}))
    for i, ch in enumerate(cast.challengers):
        anchors.append(
            CameraAnchor(
                name=f"challenger_close_{ch.character_id}",
                shot=CameraShot.CHALLENGER_CLOSE,
                position=Vec3(x=round(_challenger_x(template, i, n) * 0.6, 3), y=1.6, z=1.8),
                look_at=ch.character_id,
            )
        )
    return StageLayout(marks=marks, camera_anchors=anchors)


def _animation_tag(turn, is_caption: bool) -> AnimationTag:
    if is_caption:
        return AnimationTag.REACTION_MIXED
    obj = (turn.objective or "").lower()
    if turn.state == DebateState.OPENING:
        return AnimationTag.SPEAK_EMPHATIC
    if turn.scene_cue == "claim_card":
        return AnimationTag.SPEAK_EMPHATIC
    if "concede" in obj:
        return AnimationTag.CONCEDE_NOD
    if turn.speaker_id.startswith("challenger") or turn.scene_cue == "challenger_close":
        return AnimationTag.CHALLENGE_LEAN
    return AnimationTag.SPEAK_EXPLAIN


def _camera(turn, cast: Cast, is_caption: bool) -> CameraSpec:
    if is_caption:
        return CameraSpec(shot=CameraShot.REACTION, anchor="reaction")
    if turn.state == DebateState.OPENING or turn.state == DebateState.CLOSING:
        return CameraSpec(shot=CameraShot.WIDE_MASTER, anchor="wide_master")
    if turn.speaker_id == cast.protagonist.character_id:
        return CameraSpec(shot=CameraShot.PROTAGONIST_CLOSE, anchor="protagonist_close")
    return CameraSpec(
        shot=CameraShot.CHALLENGER_CLOSE, anchor=f"challenger_close_{turn.speaker_id}"
    )


def _emotion(turn, is_caption: bool) -> str:
    if is_caption:
        return "ritual"
    if turn.state == DebateState.OPENING:
        return "commanding"
    if turn.state == DebateState.CLOSING:
        return "resolute"
    if turn.scene_cue == "claim_card":
        return "assertive"
    if turn.speaker_id == "protagonist" or turn.speaker_id.startswith("protagonist"):
        return "calm_confident"
    return "confident_frustration"


def _required(turn, cast: Cast, transcript: Transcript, is_caption: bool) -> list[str]:
    if is_caption:
        # A reaction cutaway of the bench: the remaining challengers plus the host
        # position (the protagonist still on their mark).
        return [cast.protagonist.character_id] + [c.character_id for c in cast.challengers]
    required = [turn.speaker_id]
    other = _latest_other_speaker(turn, transcript)
    if other and other not in required:
        required.append(other)
    return required


def _latest_other_speaker(turn, transcript: Transcript) -> str | None:
    for prior in reversed(transcript.turns[: turn.index]):
        if prior.speaker_id == CAPTION_SPEAKER_ID:
            continue
        if prior.speaker_id != turn.speaker_id:
            return prior.speaker_id
    return None


def _highlight_turn_ids(ep: Episode) -> set[str]:
    """Turn ids that fall inside any highlight window -> hero / short candidates."""
    index_by_id = {t.turn_id: t.index for t in ep.transcript.turns}
    covered: set[str] = set()
    for h in ep.highlights:
        start = index_by_id.get(h.start_turn_id)
        end = index_by_id.get(h.end_turn_id)
        if start is None or end is None:
            continue
        lo, hi = sorted((start, end))
        for t in ep.transcript.turns:
            if lo <= t.index <= hi:
                covered.add(t.turn_id)
    return covered
