"""Character Builder + private-notes preparer (blueprint 4.2, 4.3).

Builds a cast whose challengers differ in *substance* (distinct contention
tags), then attaches a private strategy packet to each performer. Private notes
are stored separately from the public transcript."""

from __future__ import annotations

from youvsmany.adapters.base import Provider, complete_structured
from youvsmany.adapters.prompts import make_messages
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.character import Cast, PrivateStrategy


def build_cast(
    provider: Provider,
    brief: ShowBrief,
    *,
    suggested_tags: list[str] | None = None,
    seed: int = 0,
) -> tuple[Cast, int, int, int]:
    params = {
        "topic": brief.topic,
        "stance": brief.protagonist_position.value,
        "num_challengers": brief.num_challengers,
        "tags": suggested_tags or [],
        "seed": seed,
    }
    messages = make_messages(
        "cast",
        params,
        system=(
            "You are the Character Builder. Invent one protagonist and "
            f"{brief.num_challengers} challengers whose objections differ in SUBSTANCE, "
            "not just personality. Each gets a distinct contention_tag. There is no "
            "moderator — the cast is only the debating voices. Return JSON matching the "
            "Cast schema {protagonist, challengers[]}."
        ),
        instruction=(
            f"Topic: {brief.topic!r}. Protagonist argues {brief.protagonist_position.value}. "
            f"Tone: {brief.tone}."
        ),
    )
    # Cast is the largest structured output (protagonist + N challengers, each
    # with nested fields), so it needs a generous token budget.
    cast, result, retries = complete_structured(
        provider, messages, Cast, temperature=0.7, seed=seed, max_tokens=4096
    )
    _assert_distinct(cast)
    return cast, result.input_tokens, result.output_tokens, retries


def attach_private_notes(
    provider: Provider, brief: ShowBrief, cast: Cast, *, seed: int = 0
) -> tuple[int, int, int]:
    """Generate and attach a PrivateStrategy to every performer (not moderator)."""
    in_tok = out_tok = retries = 0
    for char in [cast.protagonist, *cast.challengers]:
        messages = make_messages(
            "private_notes",
            {
                "character_id": char.character_id,
                "role": char.role.value,
                "contention_tag": char.contention_tag,
                "topic": brief.topic,
                "seed": seed,
            },
            system=(
                "You are preparing PRIVATE notes for one debater. Other agents must not "
                "see these. Provide 2-3 main points, one fallback, one genuine concession, "
                "an opening move, the expected counter and a rebuttal. Return JSON matching "
                "PrivateStrategy."
            ),
            instruction=(
                f"Prepare {char.display_name} ({char.role.value}) whose contention is "
                f"{char.core_contention!r}."
            ),
        )
        notes, result, r = complete_structured(
            provider, messages, PrivateStrategy, temperature=0.6, seed=seed
        )
        char.private_strategy = notes
        in_tok += result.input_tokens
        out_tok += result.output_tokens
        retries += r
    return in_tok, out_tok, retries


def _assert_distinct(cast: Cast) -> None:
    tags = [c.contention_tag for c in cast.challengers]
    if len(set(tags)) != len(tags):
        raise ValueError(f"challenger contention tags are not distinct: {tags}")
