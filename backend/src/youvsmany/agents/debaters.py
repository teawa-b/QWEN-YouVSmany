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
    # Punchy, clip-friendly turns: a full debate of ~15 turns must fit 60-120s of
    # speech (~2.5 words/sec), so cap every turn tight regardless of what the
    # private strategy asked for. The strategy still drives CONTENT, not length.
    if speaker.role == Role.MODERATOR:
        length_range = [6, 12]
    else:
        length_range = [12, 22]
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

    is_claim_beat = speaker.role == Role.PROTAGONIST and "claim is that" in objective
    is_voted_out_beat = speaker.role == Role.MODERATOR and "voted out" in objective

    if speaker.role == Role.MODERATOR:
        if is_voted_out_beat:
            system = (
                f"You are {speaker.display_name}, moderator of a Jubilee 'Surrounded'-style "
                f"one-vs-many show. A one-on-one duel just ended. In a warm, quick ritual voice, "
                f"tell {opp} the majority has voted them out and to return to their seat. No new "
                f"argument, no recap. {length_range[0]}-{length_range[1]} words. "
                f'Return JSON: {{"text": ...}}.'
            )
        else:
            system = (
                f"You are {speaker.display_name}, the moderator of a fast, punchy one-vs-many "
                f"debate show (think a televised panel). Keep order in a natural, human voice - "
                f"never robotic. Push the speakers to answer the actual question. "
                f"{length_range[0]}-{length_range[1]} words, one or two sentences. "
                f'Return JSON: {{"text": ...}}.'
            )
    elif is_claim_beat:
        system = (
            f"You are {speaker.display_name}, the one person surrounded in a Jubilee "
            f"'Surrounded'-style show on {topic!r}. You are opening a NEW claim segment: stand and "
            f"declare your claim to the whole room, starting literally with 'My first claim is "
            f"that...' or 'My next claim is that...' as the objective says. Assert it - do not "
            f"react to anyone yet, no one has answered. One punchy sentence, then invite them to "
            f"change your mind. HARD LIMIT {length_range[1]} words. "
            f'Return JSON: {{"text": ...}}.'
        )
    else:
        system = (
            f"You are {speaker.display_name}, the {speaker.role.value} in a live one-vs-many "
            f"debate on {topic!r} (a Jubilee 'Surrounded'-style show). You're spirited, sharp "
            f"and conversational - real spoken English, contractions, personality "
            f"(tone: {speaker.personality.tone}). This is a back-and-forth, not a speech.\n"
            f"RULES:\n"
            f"- React to what {opp} JUST said: paraphrase their actual claim, then hit back.\n"
            f"- Sometimes address them by name ({opp}). Be direct, annoyed if needed, but civil.\n"
            f"- Bring ONE concrete example, number, everyday scenario, or hard question. No abstract filler.\n"
            f"- Your hidden angle is {speaker.contention_tag}; translate it into normal words, "
            f"do not announce the label aloud.\n"
            f"- NEVER use canned stems like 'My objection is...' or 'On {speaker.contention_tag}, "
            f"I'll grant...'. Open differently every time. Sound like a person, not a template.\n"
            f"- Keep the heat of a real argument: short questions, clipped pushback, plain language.\n"
            f"- HARD LIMIT {length_range[1]} words. One or two short sentences, ONE sharp point - "
            f"a quick televised exchange, never a monologue or a list. Respect: "
            f"{', '.join(speaker.boundaries)}.\n"
            f'Return JSON: {{"text": ...}}.' + private_ctx
        )

    if latest_opposing_claim:
        reactor = (
            f'{opp} just said: "{latest_opposing_claim}"\n'
            f"Answer THAT directly - paraphrase their point, then counter it. "
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
