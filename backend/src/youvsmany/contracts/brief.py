"""Show brief + safety/factuality gate artifacts (blueprint 3.2, 3.4, 13)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from youvsmany.contracts.enums import ContentRating, Stance, TopicKind


class ShowBrief(BaseModel):
    """What the creator supplies (blueprint 3.2 step 1).

    A starter-menu topic and a custom topic produce the *same* brief shape and
    run the *same* pipeline (blueprint 3.4)."""

    topic: str = Field(..., min_length=3, max_length=160, description="The proposition to debate.")
    protagonist_position: Stance = Stance.FOR
    tone: str = Field("witty but substantive", description="Desired show tone.")
    target_duration_s: int = Field(
        30,
        ge=20,
        le=30,
        description="Target runtime for the complete short-form episode (hard max: 30s).",
    )
    content_rating: ContentRating = ContentRating.PG
    visual_style: str = Field("clean modern debate stage", description="Used later by staging.")
    topic_kind: TopicKind = TopicKind.OPINION
    num_challengers: int = Field(
        2,
        ge=1,
        le=2,
        description="One protagonist plus at most two challengers keeps the short readable.",
    )
    seed: int = Field(0, description="Determinism seed for reproducible runs.")


class SafetyReport(BaseModel):
    """Output of the safety/factuality gate that runs at brief time
    (blueprint 3.1 / 13.2). Cheap and deterministic; runs before anything else."""

    allowed: bool = True
    reasons: list[str] = Field(default_factory=list)
    requires_source_brief: bool = False
    sanitized_topic: str | None = None


class SourceBrief(BaseModel):
    """A fixed set of grounding facts for factual topics so agents do not invent
    specifications (blueprint 3.4 'Qwen2 vs Qwen3' caution)."""

    topic: str
    facts: list[str] = Field(default_factory=list)
    disputed: list[str] = Field(
        default_factory=list,
        description="Points known to be contested; agents may argue these.",
    )
