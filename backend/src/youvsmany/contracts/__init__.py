"""Shared Pydantic/JSON contracts (blueprint: packages/contracts).

Every Qwen output is validated against these schemas before it can contaminate
later stages (blueprint 12 "Schema validation").
"""

from youvsmany.contracts.enums import (
    ContentRating,
    DebateState,
    Role,
    Stance,
    TopicKind,
)
from youvsmany.contracts.brief import ShowBrief, SafetyReport, SourceBrief
from youvsmany.contracts.character import (
    Cast,
    Character,
    Personality,
    PrivateStrategy,
)
from youvsmany.contracts.plan import ContentionSlot, RoundPlan
from youvsmany.contracts.transcript import Transcript, Turn
from youvsmany.contracts.memory import EpisodeMemory, SpeakerStat
from youvsmany.contracts.highlights import HighlightCandidate, HighlightScore
from youvsmany.contracts.scene import (
    AnimationTag,
    AudioCue,
    CameraShot,
    SceneManifest,
    SceneSegment,
    StageLayout,
    VisualPriority,
)
from youvsmany.contracts.episode import Episode

__all__ = [
    "ContentRating",
    "DebateState",
    "Role",
    "Stance",
    "TopicKind",
    "ShowBrief",
    "SafetyReport",
    "SourceBrief",
    "Cast",
    "Character",
    "Personality",
    "PrivateStrategy",
    "ContentionSlot",
    "RoundPlan",
    "Transcript",
    "Turn",
    "EpisodeMemory",
    "SpeakerStat",
    "HighlightCandidate",
    "HighlightScore",
    "AnimationTag",
    "AudioCue",
    "CameraShot",
    "SceneManifest",
    "SceneSegment",
    "StageLayout",
    "VisualPriority",
    "Episode",
]
