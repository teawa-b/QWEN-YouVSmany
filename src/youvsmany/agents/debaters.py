"""Performance agents: protagonist + challenger turn generation (blueprint 4.6).

Each speaking agent receives only compact, role-specific context: its own
private notes, the latest opposing claim, the director's objective — never the
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
    seed: int = 0,
) -> tuple[str, int, int]:
    """Return (text, input_tokens, output_tokens) for one spoken turn."""
    strat = speaker.private_strategy
    if strat:
        length_range = list(strat.response_length_range)
    elif speaker.role == Role.MODERATOR:
        length_range = [10, 18]  # moderator interjections stay short
    else:
        length_range = [12, 24]
    params = {
        "state": state.value,
        "speaker_id": speaker.character_id,
        "speaker_name": speaker.display_name,
        "role": speaker.role.value,
        "contention_tag": speaker.contention_tag,
        "opposing_tag": latest_opposing_tag,
        "objective": objective,
        "latest_opposing_claim": latest_opposing_claim,
        "topic": topic,
        "length_range": length_range,
        "index": index,
        "seed": seed,
    }
    # Compact, role-specific context only.
    private_ctx = ""
    if strat:
        private_ctx = (
            f" Your private plan — opening: {strat.opening}; rebuttal: {strat.rebuttal}; "
            f"main points: {', '.join(strat.main_points)}."
        )
    system = (
        f"You are {speaker.display_name}, the {speaker.role.value}. "
        f"Tone: {speaker.personality.tone}. Stay in persona, stay on your contention "
        f"({speaker.contention_tag}), respect boundaries: {', '.join(speaker.boundaries)}. "
        f"Keep it to {length_range[0]}-{length_range[1]} words. Return JSON: {{\"text\": ...}}."
        + private_ctx
    )
    instruction = (
        f"State: {state.value}. Objective: {objective}. "
        + (f'Latest opposing claim: "{latest_opposing_claim}". ' if latest_opposing_claim else "")
        + "Produce your single spoken turn."
    )
    messages = make_messages("turn", params, system=system, instruction=instruction)
    result = provider.complete(messages, temperature=0.8, max_tokens=300, seed=seed)
    # turn task returns {"text": ...}; parse leniently
    text = _coerce_text(result.text)
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
