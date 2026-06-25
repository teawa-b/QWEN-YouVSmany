"""Director: round plan (PREPARING) + moderator control (blueprint 4.4, 4.5)."""

from __future__ import annotations

from youvsmany.adapters.base import Provider, complete_structured
from youvsmany.adapters.prompts import make_messages
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.character import Cast
from youvsmany.contracts.memory import EpisodeMemory
from youvsmany.contracts.plan import RoundPlan


def build_round_plan(
    provider: Provider, brief: ShowBrief, cast: Cast, *, seed: int = 0
) -> tuple[RoundPlan, int, int, int]:
    tags = [c.contention_tag for c in cast.challengers]
    # The live model must reference the cast's real ids; pass them explicitly so
    # contention slots line up with the characters that were actually built.
    challengers = [
        {"challenger_id": c.character_id, "contention_tag": c.contention_tag}
        for c in cast.challengers
    ]
    target_turns = _target_turns(brief.target_duration_s)
    messages = make_messages(
        "plan",
        {
            "thesis": cast.protagonist.core_contention,
            "tags": tags,  # consumed by the offline MockProvider
            "challengers": challengers,
            "target_turns": target_turns,
            "seed": seed,
        },
        system=(
            "You are the Director. Lay out the round structure for a natural "
            "one-vs-many debate: opening claim, then one challenger at a time in a "
            "mini-duel with the protagonist, then optional rapid pressure only if the "
            "cast is too small, and a closing summary. Create exactly one contention "
            "slot per challenger, copying its challenger_id and contention_tag VERBATIM "
            "from the list provided. Return JSON matching RoundPlan."
        ),
        instruction=(
            f"Topic: {brief.topic!r}. Build one contention slot for each of these "
            f"challengers, reusing their exact challenger_id and contention_tag: "
            f"{challengers}."
        ),
    )
    plan, result, retries = complete_structured(
        provider, messages, RoundPlan, temperature=0.4, seed=seed
    )
    return plan, result.input_tokens, result.output_tokens, retries


def _target_turns(duration_s: int) -> int:
    """12-20 turns for 60-120s (blueprint 3.3)."""
    return max(12, min(20, round(12 + (duration_s - 60) / 60 * 8)))


# --- Moderator control rules (blueprint 4.5) --------------------------

MAX_CONSECUTIVE = 2  # dominance: cap consecutive turns per agent


def next_speaker_blocked(memory: EpisodeMemory, speaker_id: str) -> bool:
    """Dominance rule: block a speaker who would exceed the consecutive cap."""
    stat = memory.speaker_stats.get(speaker_id)
    if stat is None:
        return False
    return memory.last_speaker_id == speaker_id and stat.consecutive >= MAX_CONSECUTIVE


def disputed_question(tag: str, topic: str) -> str:
    """Conflict rule: a precise question both sides must answer."""
    return f"On {tag}: does {topic} hold once that specific objection is granted? Yes or no, and why."
