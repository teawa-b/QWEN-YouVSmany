"""Director's round plan (blueprint 3.2 step 3, 4.4 PREPARING)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContentionSlot(BaseModel):
    challenger_id: str
    contention_tag: str
    objective: str = Field(..., description="What this round should accomplish.")


class RoundPlan(BaseModel):
    """One shared claim, challenger pressure angles, rotating crossfire and a
    closing summary (blueprint 3.3 'Structure')."""

    thesis: str
    opening_objective: str
    contentions: list[ContentionSlot]
    rapid_rebuttal_objective: str
    closing_objective: str
    target_turns: int = Field(16, ge=12, le=20)
