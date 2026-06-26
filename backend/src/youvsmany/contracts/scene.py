"""Renderer-neutral scene contract (blueprint 5.2-5.6).

Phase 2 turns a LOCKED debate transcript into a `SceneManifest`: a timecoded,
engine-agnostic description of the episode that a Three.js player (or any other
renderer) can interpret directly. The agent system never commands renderer nodes
— it emits this contract, and the master audio timeline (built from real TTS)
drives every downstream timing so generated visuals can never drift off the cut.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CameraShot(str, Enum):
    """Camera anchors from the stage design (blueprint 5.3)."""

    WIDE_MASTER = "wide_master"
    PROTAGONIST_CLOSE = "protagonist_close"
    CHALLENGER_CLOSE = "challenger_close"
    OVER_SHOULDER = "over_shoulder"
    REACTION = "reaction"
    TWO_SHOT = "two_shot"


class AnimationTag(str, Enum):
    """The six reusable animation states (blueprint 5.4)."""

    LISTEN_NEUTRAL = "listen_neutral"
    SPEAK_EXPLAIN = "speak_explain"
    SPEAK_EMPHATIC = "speak_emphatic"
    CHALLENGE_LEAN = "challenge_lean"
    REACTION_MIXED = "reaction_mixed"
    CONCEDE_NOD = "concede_nod"


class VisualPriority(str, Enum):
    HERO = "hero"          # highlight-worthy: promote to stills / generated video
    STANDARD = "standard"  # base render is enough
    CAPTION = "caption"    # non-spoken ritual graphic (e.g. the voted-out gavel)


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class StageMark(BaseModel):
    """A character's fixed position on the debate stage (Three.js world space)."""

    character_id: str
    role: str
    mark: str = Field(..., description="Semantic position label, e.g. 'center' or 'arc_2'.")
    position: Vec3
    face_to: str = Field("camera", description="character_id to face, or 'camera'.")


class CameraAnchor(BaseModel):
    """A reusable camera position the director can cut to (blueprint 5.3)."""

    name: str
    shot: CameraShot
    position: Vec3
    look_at: str = Field(..., description="character_id or 'stage_center'.")


class StageLayout(BaseModel):
    """Protagonist centre, challengers in a shallow semicircle (blueprint 5.3)."""

    marks: list[StageMark] = Field(default_factory=list)
    camera_anchors: list[CameraAnchor] = Field(default_factory=list)
    aspect_primary: str = "16:9"
    crop_guide: str = "9:16"


class CameraSpec(BaseModel):
    shot: CameraShot
    anchor: str = Field(..., description="Name of the CameraAnchor to use.")


class Blocking(BaseModel):
    speaker_pose: str
    listeners: str = "attentive"


class AudioCue(BaseModel):
    """One element of the master audio timeline (blueprint 5.5).

    Built from real TTS so every later asset inherits the same start, end and
    dialogue id. Non-spoken caption beats produce no audio cue."""

    dialogue_id: str
    start_s: float
    end_s: float
    speaker_id: str
    voice_id: str
    text: str
    audio_ref: str | None = Field(
        None, description="Path/URL to the rendered audio clip, if synthesised."
    )

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)


class SceneSegment(BaseModel):
    """One timecoded beat the renderer stages (mirrors blueprint 5.2)."""

    segment_id: str
    start_s: float
    end_s: float
    speaker_id: str
    dialogue: str
    emotion: str
    animation_tag: AnimationTag
    intensity: float = Field(0.6, ge=0.0, le=1.0)
    camera: CameraSpec
    blocking: Blocking
    required_characters: list[str] = Field(default_factory=list)
    visual_priority: VisualPriority = VisualPriority.STANDARD
    short_candidate: bool = False
    scene_cue: str = ""

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)


class SceneManifest(BaseModel):
    """The Phase 2 deliverable: a renderer-neutral, audio-locked episode plan."""

    episode_id: str
    stage: StageLayout
    segments: list[SceneSegment] = Field(default_factory=list)
    audio: list[AudioCue] = Field(default_factory=list)
    voice_map: dict[str, str] = Field(
        default_factory=dict, description="character_id -> voice_id used for TTS."
    )
    total_duration_s: float = 0.0
    crop_safe_9x16: bool = True

    @property
    def short_candidates(self) -> list[SceneSegment]:
        return [s for s in self.segments if s.short_candidate]
