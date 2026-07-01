"""Enumerations shared across the debate pipeline."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    PROTAGONIST = "protagonist"
    CHALLENGER = "challenger"
    MODERATOR = "moderator"


class Stance(str, Enum):
    FOR = "for"
    AGAINST = "against"
    NEUTRAL = "neutral"


class VisualPresentation(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


class TopicKind(str, Enum):
    """Opinion topics are free to argue; factual topics must be grounded in a
    SourceBrief and pass a factuality note (blueprint 3.4)."""

    OPINION = "opinion"
    FACTUAL = "factual"


class ContentRating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG-13"


class DebateState(str, Enum):
    """Debate state machine (blueprint 4.4)."""

    BRIEFED = "BRIEFED"
    PREPARING = "PREPARING"
    OPENING = "OPENING"
    CONTENTIONS = "CONTENTIONS"
    RAPID_REBUTTAL = "RAPID_REBUTTAL"
    CLOSING = "CLOSING"
    LOCKED = "LOCKED"

    @property
    def order(self) -> int:
        return _STATE_ORDER[self]


_STATE_ORDER = {
    DebateState.BRIEFED: 0,
    DebateState.PREPARING: 1,
    DebateState.OPENING: 2,
    DebateState.CONTENTIONS: 3,
    DebateState.RAPID_REBUTTAL: 4,
    DebateState.CLOSING: 5,
    DebateState.LOCKED: 6,
}

# Legal forward transitions for the debate state machine.
STATE_TRANSITIONS: dict[DebateState, tuple[DebateState, ...]] = {
    DebateState.BRIEFED: (DebateState.PREPARING,),
    DebateState.PREPARING: (DebateState.OPENING,),
    DebateState.OPENING: (DebateState.CONTENTIONS,),
    DebateState.CONTENTIONS: (DebateState.RAPID_REBUTTAL,),
    DebateState.RAPID_REBUTTAL: (DebateState.CLOSING,),
    DebateState.CLOSING: (DebateState.LOCKED,),
    DebateState.LOCKED: (),
}
