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
            "one-vs-many debate: one shared claim on the floor, every challenger "
            "pressing that same claim from a distinct angle, rotating follow-ups, "
            "and a closing summary. Create exactly one contention slot per challenger, "
            "copying its challenger_id and contention_tag VERBATIM from the list provided. "
            "Return JSON matching RoundPlan."
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
    """Six or seven sharp beats for a complete episode no longer than 30s."""
    return max(6, min(7, round(6 + (duration_s - 20) / 10)))


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


# --- Surrounded-style segment ritual (claim -> duel -> "voted out") ----


def claim_objective(ordinal: str, tag: str, topic: str) -> str:
    """Protagonist beat that opens a claim segment, Jubilee 'Surrounded' style.

    The word 'claim' and the ordinal are load-bearing: the offline provider keys
    its template off them, and the live model reads them as a stage direction."""
    return (
        f"State your {ordinal} claim to the room out loud, Jubilee 'Surrounded' style: "
        f"say 'My {ordinal} claim is that …' and assert your strongest line on {tag} "
        f"for {topic}. One sentence, then dare them to change your mind."
    )


# Non-spoken caption that ends a one-on-one duel and resets the seat. With no
# moderator voice, the gavel is an on-screen ritual beat, not a spoken turn.
_VOTED_OUT_CAPTIONS = (
    "{name} is voted out — back to the bench.",
    "The majority votes {name} out. Seat reset.",
    "{name} is sent back to their seat.",
    "Voted out: {name} returns to the bench.",
)


def voted_out_caption(challenger_name: str, index: int) -> str:
    """Ritual caption text shown when a challenger is voted out (no speaker)."""
    return _VOTED_OUT_CAPTIONS[index % len(_VOTED_OUT_CAPTIONS)].format(name=challenger_name)


CEILING_TURNS = 24


def segment_passes(num_segments: int, target_turns: int) -> list[int]:
    """How many challenger->protagonist passes each claim segment runs.

    Every segment carries a fixed 2-turn ritual overhead (claim card + voted-out
    closer) on top of its duel passes. Opening + closing add 3 more turns.

    A single pass is one objection and one answer — the gavel falls before the
    challenger can press the protagonist's actual reply, so the exchange reads as
    flat. We therefore give every duel a back-and-forth *floor* of two passes
    whenever the whole run still fits under the locked 24-turn ceiling, then add
    further passes round-robin toward the director's target."""
    n = max(1, num_segments)
    fixed = 1 + 1  # opening + protagonist closing (no moderator turns)

    def total(ps: list[int]) -> int:
        return fixed + sum(2 + p * 2 for p in ps)

    # Floor of 2 passes per duel when it fits; fall back to 1 only for casts so
    # large that two passes each would blow the ceiling.
    floor = 2 if total([2] * n) <= CEILING_TURNS else 1
    passes = [floor] * n

    target = max(12, min(20, target_turns))
    i = 0
    # Grow toward the target, then make sure we clear the 12-turn floor, never
    # crossing the 24-turn ceiling.
    while total(passes) + 2 <= min(target, CEILING_TURNS):
        passes[i % n] += 1
        i += 1
    while total(passes) < 12 and total(passes) + 2 <= CEILING_TURNS:
        passes[i % n] += 1
        i += 1
    return passes


# --- Shared-room exchange helpers -------------------------------------


def room_claim_objective(topic: str) -> str:
    """Protagonist beat that puts one shared claim in front of the room."""
    return (
        f"State the shared claim to the whole room: say 'My claim is that {topic}' "
        "and give the strongest reason in one punchy line. Invite all challengers "
        "to attack that same claim, not separate side claims."
    )


def opening_pressure_objective(tag: str, topic: str) -> str:
    return (
        f"enter the shared debate by challenging {topic} through {tag}; one concrete "
        "pressure point, aimed at the protagonist's single claim"
    )


def build_pressure_objective(tag: str, previous_name: str, topic: str) -> str:
    return (
        f"build on {previous_name}'s pressure, then sharpen a different {tag} objection "
        f"against the same claim about {topic}"
    )


def follow_up_objective(tag: str, topic: str) -> str:
    return (
        "follow up on the protagonist's answer; keep the fight on the same claim "
        f"about {topic}, using your {tag} angle"
    )


def answer_room_objective(topic: str) -> str:
    return (
        f"answer the room on the single claim about {topic}; group the pressure, "
        "then defend the core without giving a speech"
    )


def answer_follow_up_objective(tag: str) -> str:
    return f"reply directly to the {tag} follow-up and keep the central claim alive"


def crossfire_pairs(num_challengers: int, target_turns: int) -> int:
    """How many challenger->protagonist follow-up pairs to run.

    A 30-second episode has room for one follow-up pair after both challengers
    make their opening pressure. This keeps a real back-and-forth without turning
    the short into a speed-read.
    """
    del num_challengers, target_turns
    return 1
