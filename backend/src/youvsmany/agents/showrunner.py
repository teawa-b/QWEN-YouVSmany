"""Fast live-Qwen showrunner pass for the 30-second product.

The offline provider keeps the granular multi-agent simulation for deterministic
evaluation. In production, one Qwen call writes the cast, the two distinct
pressure angles and the complete seven-beat script together. That preserves the
agentic showrunner role while removing a dozen serial network round-trips from
the creator-facing request.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from youvsmany.adapters.base import Provider, complete_structured
from youvsmany.adapters.prompts import make_messages
from youvsmany.agents import director
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.character import (
    Cast,
    Character,
    Personality,
    PrivateStrategy,
)
from youvsmany.contracts.enums import DebateState, Role, Stance, VisualPresentation
from youvsmany.contracts.episode import Episode
from youvsmany.contracts.plan import ContentionSlot, RoundPlan
from youvsmany.contracts.transcript import Turn


class ShowrunnerDraft(BaseModel):
    """Small, reliable schema for the single production Qwen call."""

    thesis: str = Field(min_length=3, max_length=180)
    cast_names: list[str] = Field(min_length=3, max_length=3)
    visual_presentations: list[VisualPresentation] = Field(min_length=3, max_length=3)
    challenger_angles: list[str] = Field(min_length=2, max_length=2)
    lines: list[str] = Field(min_length=7, max_length=7)

    @field_validator("cast_names")
    @classmethod
    def distinct_short_names(cls, names: list[str]) -> list[str]:
        cleaned = [name.strip() for name in names]
        if any(not name or len(name.split()) > 2 for name in cleaned):
            raise ValueError("cast names must be one or two words")
        if len({name.casefold() for name in cleaned}) != 3:
            raise ValueError("cast names must be distinct")
        return cleaned

    @field_validator("challenger_angles")
    @classmethod
    def distinct_angles(cls, angles: list[str]) -> list[str]:
        cleaned = [angle.strip() for angle in angles]
        if any(not angle for angle in cleaned):
            raise ValueError("challenger angles cannot be empty")
        if cleaned[0].casefold() == cleaned[1].casefold():
            raise ValueError("challenger angles must be distinct")
        return cleaned

    @field_validator("lines")
    @classmethod
    def complete_short_lines(cls, lines: list[str]) -> list[str]:
        cleaned = [line.strip() for line in lines]
        for index, line in enumerate(cleaned):
            words = line.split()
            if not 8 <= len(words) <= 10:
                raise ValueError(f"line {index + 1} must contain 8-10 words")
            if not line.endswith((".", "?", "!")):
                raise ValueError(f"line {index + 1} must be a complete sentence")
        return cleaned


def draft_episode(
    provider: Provider,
    brief: ShowBrief,
    *,
    suggested_tags: list[str] | None = None,
) -> tuple[ShowrunnerDraft, int, int, int]:
    """Ask Qwen to make every creative decision in one coordinated pass."""

    tags = [tag for tag in (suggested_tags or []) if tag][:2]
    speaker_order = [
        "lead hook and shared claim",
        "challenger one attacks the claim",
        "challenger two builds with a different angle",
        "lead answers both challengers",
        "challenger one presses the answer",
        "lead replies directly",
        "lead closes with the unresolved core",
    ]
    messages = make_messages(
        "showrunner",
        {
            "topic": brief.topic,
            "stance": brief.protagonist_position.value,
            "tone": brief.tone,
            "tags": tags,
            "speaker_order": speaker_order,
            "seed": brief.seed,
        },
        system=(
            "You are the AI Showrunner for a premium vertical short. In one pass, cast "
            "three distinct adult debaters, choose two substantive challenger angles, "
            "and write the complete seven-beat episode. cast_names order is [lead, "
            "challenger one, challenger two]. visual_presentations uses male, female or "
            "neutral in the same order. lines MUST follow the supplied speaker order. "
            "Every line must be a natural, complete sentence of 8-10 words, with no "
            "speaker labels. Make adjacent lines react to each other. No greetings, "
            "stage directions, filler, invented statistics or personal insults. The "
            "whole script must feel conclusive in under 30 seconds."
        ),
        instruction=(
            f"Direct a seven-beat debate on {brief.topic!r}. The lead argues "
            f"{brief.protagonist_position.value}. Tone: {brief.tone}. "
            f"Preferred challenger angles, if useful: {tags or 'choose the strongest two'}. "
            f"Line order: {speaker_order}."
        ),
    )
    draft, result, retries = complete_structured(
        provider,
        messages,
        ShowrunnerDraft,
        temperature=0.65,
        max_tokens=1200,
        seed=brief.seed,
        max_attempts=2,
    )
    return draft, result.input_tokens, result.output_tokens, retries


def apply_draft(
    ep: Episode,
    draft: ShowrunnerDraft,
    *,
    suggested_tags: list[str] | None = None,
) -> Episode:
    """Hydrate the existing validated episode contracts from a showrunner draft."""

    lead_stance = ep.brief.protagonist_position
    opposing_stance = Stance.AGAINST if lead_stance != Stance.AGAINST else Stance.FOR
    preferred = [tag for tag in (suggested_tags or []) if tag][:2]
    raw_tags = preferred + draft.challenger_angles[len(preferred) :]
    tags = _distinct_tags(raw_tags)

    protagonist = Character(
        character_id="protagonist",
        display_name=draft.cast_names[0],
        role=Role.PROTAGONIST,
        stance=lead_stance,
        visual_presentation=draft.visual_presentations[0],
        core_contention=draft.thesis,
        contention_tag="thesis",
        supporting_points=[draft.thesis],
        personality=Personality(tone="confident and responsive", assertiveness=0.72),
        private_strategy=_strategy(draft.thesis, draft.challenger_angles[0]),
    )
    challengers: list[Character] = []
    for index in range(2):
        angle = draft.challenger_angles[index]
        challengers.append(
            Character(
                character_id=f"challenger_{tags[index]}",
                display_name=draft.cast_names[index + 1],
                role=Role.CHALLENGER,
                stance=opposing_stance,
                visual_presentation=draft.visual_presentations[index + 1],
                core_contention=f"{angle} weakens the central claim",
                contention_tag=tags[index],
                supporting_points=[angle],
                personality=Personality(
                    tone="sharp and conversational",
                    assertiveness=0.68 + index * 0.04,
                ),
                private_strategy=_strategy(angle, draft.thesis),
            )
        )
    ep.cast = Cast(protagonist=protagonist, challengers=challengers)
    ep.plan = RoundPlan(
        thesis=draft.thesis,
        opening_objective="land one shared claim and invite the room",
        contentions=[
            ContentionSlot(
                challenger_id=challenger.character_id,
                contention_tag=challenger.contention_tag,
                objective=f"pressure the shared claim through {draft.challenger_angles[index]}",
            )
            for index, challenger in enumerate(challengers)
        ],
        rapid_rebuttal_objective="one direct follow-up and answer",
        closing_objective="close on the strongest pressure and unresolved core",
        target_turns=7,
    )

    speakers = [
        protagonist,
        challengers[0],
        challengers[1],
        protagonist,
        challengers[0],
        protagonist,
        protagonist,
    ]
    states = [
        DebateState.OPENING,
        DebateState.CONTENTIONS,
        DebateState.CONTENTIONS,
        DebateState.CONTENTIONS,
        DebateState.RAPID_REBUTTAL,
        DebateState.RAPID_REBUTTAL,
        DebateState.CLOSING,
    ]
    cues = [
        "claim_card",
        "challenger_close",
        "challenger_close",
        "protagonist_close",
        "quick_cuts",
        "quick_cuts",
        "two_shot",
    ]
    objectives = [
        director.room_claim_objective(ep.brief.topic),
        director.opening_pressure_objective(tags[0], ep.brief.topic),
        director.build_pressure_objective(tags[1], challengers[0].display_name, ep.brief.topic),
        director.answer_room_objective(ep.brief.topic),
        director.follow_up_objective(tags[0], ep.brief.topic),
        director.answer_follow_up_objective(tags[0]),
        ep.plan.closing_objective,
    ]
    for index, (speaker, state, cue, objective, text) in enumerate(
        zip(speakers, states, cues, objectives, draft.lines, strict=True)
    ):
        ep.transcript.turns.append(
            Turn(
                turn_id=f"t{index:04d}",
                index=index,
                state=state,
                speaker_id=speaker.character_id,
                speaker_name=speaker.display_name,
                text=text,
                contention_tag=(speaker.contention_tag if speaker.role == Role.CHALLENGER else None),
                objective=objective,
                scene_cue=cue,
            )
        )
    ep.transcript.retime()
    ep.memory.rolling_summary = f"7 showrunner beats; contentions: {', '.join(tags)}."
    ep.memory.covered_contentions = tags
    ep.state = DebateState.LOCKED
    ep.run_report.events.extend(
        [
            "state -> PREPARING",
            "qwen showrunner -> cast + angles + seven-beat script",
            "state -> LOCKED",
        ]
    )
    return ep


def _strategy(opening: str, counter: str) -> PrivateStrategy:
    return PrivateStrategy(
        opening=opening,
        expected_counter=counter,
        rebuttal="answer the exact pressure without changing the claim",
        main_points=[opening, counter],
        fallback_point="concede the narrow edge and hold the core",
        genuine_concession="the opposing angle identifies a real tradeoff",
        response_length_range=(8, 10),
    )


def _distinct_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    for index, value in enumerate(values[:2]):
        tag = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:28]
        tag = tag or f"angle-{index + 1}"
        if tag in tags:
            tag = f"{tag}-{index + 1}"
        tags.append(tag)
    while len(tags) < 2:
        tags.append(f"angle-{len(tags) + 1}")
    return tags
