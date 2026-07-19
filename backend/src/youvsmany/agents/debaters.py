"""Performance agents: protagonist + challenger turn generation (blueprint 4.6).

Each speaking agent receives only compact, role-specific context: its own
private notes, the latest opposing claim, the director's objective - never the
whole transcript."""

from __future__ import annotations

from youvsmany.adapters.base import Provider
from youvsmany.adapters.prompts import make_messages
from youvsmany.contracts.character import Character
from youvsmany.contracts.enums import DebateState, Role


def generate_turn(
    provider: Provider,
    *,
    speaker: Character,
    state: DebateState,
    objective: str,
    latest_opposing_claim: str,
    topic: str,
    index: int,
    latest_opposing_tag: str | None = None,
    latest_opposing_name: str = "",
    seed: int = 0,
) -> tuple[str, int, int]:
    """Return (text, input_tokens, output_tokens) for one spoken turn."""
    strat = speaker.private_strategy
    # Seven complete beats have to fit inside one 30-second final cut. Ten words
    # per speaker leaves a little breathing room for real TTS cadence.
    length_range = [7, 10]
    params = {
        "state": state.value,
        "speaker_id": speaker.character_id,
        "speaker_name": speaker.display_name,
        "role": speaker.role.value,
        "contention_tag": speaker.contention_tag,
        "opposing_tag": latest_opposing_tag,
        "opposing_name": latest_opposing_name,
        "objective": objective,
        "latest_opposing_claim": latest_opposing_claim,
        "topic": topic,
        "length_range": length_range,
        "index": index,
        "seed": seed,
    }
    opp = latest_opposing_name or "your opponent"

    # Compact, role-specific context only.
    private_ctx = ""
    if strat:
        private_ctx = (
            f" Your private game plan (do NOT read it aloud) - opening angle: {strat.opening}; "
            f"go-to rebuttal: {strat.rebuttal}; main points: {', '.join(strat.main_points)}."
        )

    is_claim_beat = speaker.role == Role.PROTAGONIST and (
        "claim is that" in objective or "shared claim" in objective
    )

    if is_claim_beat:
        system = (
            f"You are {speaker.display_name}, the one person facing a room of challengers "
            f"on {topic!r}. Put ONE shared claim on the floor for everyone to attack. "
            f"For a short proposition, start with 'My claim is that...'. If the proposition "
            f"cannot fit intact, say exactly 'I back the proposition on screen. Prove me wrong.' "
            f"Make it the same claim all challengers can argue with. HARD LIMIT "
            f"{length_range[1]} words. "
            f'Return JSON: {{"text": ...}}.'
        )
    else:
        system = (
            f"You are {speaker.display_name}, the {speaker.role.value} in a live one-vs-many "
            f"debate on {topic!r}. Everyone is arguing over the SAME central claim. "
            f"You're spirited, sharp "
            f"and conversational - real spoken English, contractions, personality "
            f"(tone: {speaker.personality.tone}). This is a back-and-forth, not a speech.\n"
            f"RULES:\n"
            f"- React to what {opp} JUST said: paraphrase their actual claim, then hit back, "
            f"build on it, or redirect it toward the protagonist.\n"
            f"- Sometimes address them by name ({opp}). Be direct, annoyed if needed, but civil.\n"
            f"- Bring ONE concrete example, number, everyday scenario, or hard question. No abstract filler.\n"
            f"- Your hidden angle is {speaker.contention_tag}; translate it into normal words, "
            f"do not announce the label aloud.\n"
            f"- NEVER use canned stems like 'My objection is...' or 'On {speaker.contention_tag}, "
            f"I'll grant...'. Open differently every time. Sound like a person, not a template.\n"
            f"- Keep the heat of a real group argument: short questions, clipped pushback, plain language.\n"
            f"- HARD LIMIT {length_range[1]} words. One short sentence, ONE sharp point - "
            f"a quick televised exchange, never a monologue or a list. Respect: "
            f"{', '.join(speaker.boundaries)}.\n"
            f'Return JSON: {{"text": ...}}.' + private_ctx
        )

    if latest_opposing_claim:
        reactor = (
            f'{opp} just said: "{latest_opposing_claim}"\n'
            f"Answer THAT directly - paraphrase their point, then counter, build, or redirect it. "
        )
    else:
        reactor = ""
    instruction = (
        f"[{state.value}] {reactor}Your job this turn: {objective}. "
        f"Give your single spoken line now."
    )
    messages = make_messages("turn", params, system=system, instruction=instruction)
    # Tight token cap as a backstop so a turn can't balloon into an essay.
    result = provider.complete(messages, temperature=0.9, max_tokens=90, seed=seed)
    # turn task returns {"text": ...}; parse leniently
    text = _clip_words(_coerce_text(result.text), length_range[1])
    return text, result.input_tokens, result.output_tokens


def _coerce_text(raw: str) -> str:
    import json

    from youvsmany.adapters.base import _extract_json

    try:
        obj = json.loads(_extract_json(raw))
        if isinstance(obj, dict) and "text" in obj:
            return str(obj["text"]).strip()
    except Exception:
        pass
    return raw.strip()


def _clip_words(text: str, limit: int) -> str:
    """Provider-independent safety rail for the 30-second episode contract."""
    words = text.split()
    if len(words) <= limit:
        return text
    clipped = " ".join(words[:limit]).rstrip(",;:")
    return clipped if clipped.endswith((".", "?", "!")) else clipped + "."
