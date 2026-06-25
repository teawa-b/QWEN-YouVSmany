"""Map each turn to one of ~6 reusable scene/camera cues (blueprint 3.3, 5).

These are renderer-neutral hints consumed later by staging; Phase 1 only needs
them present and stable on the locked transcript."""

from __future__ import annotations

from youvsmany.contracts.enums import DebateState, Role

# Six reusable cues (blueprint: "six reusable animation states").
CUES = (
    "wide_establish",
    "protagonist_close",
    "challenger_close",
    "two_shot",
    "reaction_pan",
    "quick_cuts",
)


def cue_for(state: DebateState, role: Role) -> str:
    if state == DebateState.OPENING:
        return "wide_establish"
    if state == DebateState.RAPID_REBUTTAL:
        return "quick_cuts"
    if state == DebateState.CLOSING:
        return "two_shot"
    if role == Role.PROTAGONIST:
        return "protagonist_close"
    if role == Role.CHALLENGER:
        return "challenger_close"
    if role == Role.MODERATOR:
        return "reaction_pan"
    return "two_shot"
