"""Character + contention packet schema (blueprint 4.2, 4.3).

A personality is not enough: every debater is defined by a behavioural profile
*and* a substantive contention packet, plus a private strategy other agents
cannot see."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from youvsmany.contracts.enums import Role, Stance


class Personality(BaseModel):
    tone: str = "neutral"
    humour: float = Field(0.3, ge=0.0, le=1.0)
    assertiveness: float = Field(0.6, ge=0.0, le=1.0)
    concession_threshold: float = Field(
        0.4, ge=0.0, le=1.0, description="How readily the agent concedes a point."
    )


class PrivateStrategy(BaseModel):
    """Stored separately from the public transcript so preparation can be shown
    without exposing hidden reasoning text (blueprint 4.3)."""

    opening: str
    expected_counter: str
    rebuttal: str
    main_points: list[str] = Field(default_factory=list)
    fallback_point: str | None = None
    genuine_concession: str | None = None
    response_length_range: tuple[int, int] = Field(
        (20, 45), description="Min/max words per turn for this agent."
    )


class Character(BaseModel):
    """Matches the structured packet in blueprint 4.2."""

    character_id: str
    display_name: str
    role: Role
    stance: Stance
    core_contention: str
    contention_tag: str = Field(
        ..., description="Short slug used to verify substantive uniqueness (e.g. 'texture')."
    )
    supporting_points: list[str] = Field(default_factory=list)
    personality: Personality = Field(default_factory=Personality)
    private_strategy: PrivateStrategy | None = None
    boundaries: list[str] = Field(
        default_factory=lambda: ["no personal insults", "no invented facts"]
    )

    @field_validator("supporting_points")
    @classmethod
    def _non_empty_points(cls, v: list[str]) -> list[str]:
        return [p.strip() for p in v if p and p.strip()]


class Cast(BaseModel):
    """1 protagonist + N challengers + 1 moderator (blueprint 3.3)."""

    protagonist: Character
    challengers: list[Character]
    moderator: Character

    def all_speakers(self) -> list[Character]:
        return [self.protagonist, *self.challengers, self.moderator]

    def by_id(self, character_id: str) -> Character:
        for c in self.all_speakers():
            if c.character_id == character_id:
                return c
        raise KeyError(character_id)

    @field_validator("challengers")
    @classmethod
    def _at_least_one(cls, v: list[Character]) -> list[Character]:
        if not v:
            raise ValueError("at least one challenger is required")
        return v
