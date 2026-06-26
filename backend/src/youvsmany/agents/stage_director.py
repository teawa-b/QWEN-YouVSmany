"""Stage Director (blueprint 5): LOCKED transcript -> renderer-neutral SceneManifest.

Turns a finished debate into a timecoded staging plan a Three.js player can drive:
a fixed stage layout, camera anchors, the six-state animation grammar, and a
master audio timeline built from TTS. Audio is the master clock — segment timings
come from the synthesised line durations, so no later visual can drift off the cut.
"""

from __future__ import annotations

from youvsmany.adapters.tts_base import WORDS_PER_SECOND, TTSProvider
from youvsmany.contracts.character import Cast
from youvsmany.contracts.enums import DebateState
from youvsmany.contracts.episode import Episode
from youvsmany.contracts.scene import (
    AnimationTag,
    AudioCue,
    Blocking,
    CameraAnchor,
    CameraShot,
    CameraSpec,
    SceneManifest,
    SceneSegment,
    StageLayout,
    StageMark,
    Vec3,
    VisualPriority,
)
from youvsmany.contracts.transcript import CAPTION_SPEAKER_ID, Transcript

# Plausible Qwen Cloud TTS voice ids; exact ids are confirmed live (see PROGRESS.md).
VOICE_POOL = ["Ethan", "Cherry", "Chelsie", "Serena", "Dylan", "Jada"]

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
    stage = _build_stage(cast)
    covered = _highlight_turn_ids(ep)

    segments: list[SceneSegment] = []
    audio: list[AudioCue] = []
    cursor = 0.0
    for turn in ep.transcript.turns:
        is_caption = turn.speaker_id == CAPTION_SPEAKER_ID
        if is_caption:
            duration = round(max(_CAPTION_HOLD_FLOOR_S, turn.word_count / WORDS_PER_SECOND), 3)
        else:
            voice_id = voice_map[turn.speaker_id]
            res = tts.synthesize(turn.text, voice_id=voice_id, seed=ep.brief.seed + turn.index)
            duration = res.duration_s
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

    return SceneManifest(
        episode_id=ep.episode_id,
        stage=stage,
        segments=segments,
        audio=audio,
        voice_map=voice_map,
        total_duration_s=round(cursor, 3),
        crop_safe_9x16=True,
    )


# --- mapping helpers --------------------------------------------------


def _assign_voices(cast: Cast) -> dict[str, str]:
    speakers = cast.all_speakers()
    return {c.character_id: VOICE_POOL[i % len(VOICE_POOL)] for i, c in enumerate(speakers)}


def _build_stage(cast: Cast) -> StageLayout:
    """Protagonist centre-front; challengers in a shallow semicircle behind."""
    marks = [
        StageMark(
            character_id=cast.protagonist.character_id,
            role="protagonist",
            mark="center",
            position=Vec3(x=0.0, y=0.0, z=2.0),
            face_to="camera",
        )
    ]
    n = len(cast.challengers)
    for i, ch in enumerate(cast.challengers):
        # Spread challengers evenly across a 3.0-wide arc, slightly upstage.
        x = -1.5 + (3.0 * i / (n - 1)) if n > 1 else 0.0
        marks.append(
            StageMark(
                character_id=ch.character_id,
                role="challenger",
                mark=f"arc_{i + 1}",
                position=Vec3(x=round(x, 3), y=0.0, z=-0.5),
                face_to=cast.protagonist.character_id,
            )
        )

    anchors = [
        CameraAnchor(name="wide_master", shot=CameraShot.WIDE_MASTER,
                     position=Vec3(x=0.0, y=1.6, z=6.0), look_at="stage_center"),
        CameraAnchor(name="protagonist_close", shot=CameraShot.PROTAGONIST_CLOSE,
                     position=Vec3(x=0.0, y=1.6, z=3.6), look_at=cast.protagonist.character_id),
        CameraAnchor(name="reaction", shot=CameraShot.REACTION,
                     position=Vec3(x=1.0, y=1.9, z=4.5), look_at="stage_center"),
        CameraAnchor(name="two_shot", shot=CameraShot.TWO_SHOT,
                     position=Vec3(x=0.8, y=1.6, z=4.2), look_at="stage_center"),
    ]
    for i, ch in enumerate(cast.challengers):
        x = -1.5 + (3.0 * i / (n - 1)) if n > 1 else 0.0
        anchors.append(
            CameraAnchor(
                name=f"challenger_close_{ch.character_id}",
                shot=CameraShot.CHALLENGER_CLOSE,
                position=Vec3(x=round(x * 0.6, 3), y=1.6, z=1.8),
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
