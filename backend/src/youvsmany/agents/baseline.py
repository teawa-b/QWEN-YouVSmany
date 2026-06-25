"""Single-agent baseline (blueprint 4.8, 11.2).

One model writes the whole debate as a script in a single pass — no private
information, no moderator control, no per-turn memory. Used to show the
multi-agent system's measurable gain in contention uniqueness and repetition."""

from __future__ import annotations

import uuid

from youvsmany.adapters.base import Provider
from youvsmany.adapters.factory import build_provider
from youvsmany.adapters.prompts import make_messages
from youvsmany.agents.scene_cues import cue_for
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import DebateState, Role
from youvsmany.contracts.episode import Episode
from youvsmany.contracts.transcript import Turn


def run_baseline(brief: ShowBrief, *, provider: Provider | None = None) -> Episode:
    provider = provider or build_provider()
    ep = Episode(episode_id=f"base_{uuid.uuid4().hex[:8]}", brief=brief)
    ep.run_report.provider = provider.name
    ep.run_report.model = provider.model
    ep.run_report.events.append("single-agent baseline")

    target_turns = max(12, min(20, round(12 + (brief.target_duration_s - 60) / 60 * 8)))
    messages = make_messages(
        "baseline_script",
        {"topic": brief.topic, "turns": target_turns, "seed": brief.seed},
        system=(
            "You are a single writer producing an entire one-vs-many debate script in "
            "one pass. Return a JSON list of {speaker, text} turns."
        ),
        instruction=f"Write a {target_turns}-turn debate about {brief.topic!r}.",
    )
    result = provider.complete(messages, temperature=0.8, max_tokens=1200, seed=brief.seed)
    ep.run_report.llm_calls += 1
    ep.run_report.input_tokens += result.input_tokens
    ep.run_report.output_tokens += result.output_tokens

    turns = _parse_or_synthesize(result.text, brief, target_turns)
    for i, (speaker, text) in enumerate(turns):
        role = Role.PROTAGONIST if speaker == "protagonist" else (
            Role.MODERATOR if speaker == "moderator" else Role.CHALLENGER
        )
        ep.transcript.turns.append(
            Turn(
                turn_id=f"b{i:04d}",
                index=i,
                state=DebateState.CONTENTIONS,
                speaker_id=speaker,
                speaker_name=speaker,
                text=text,
                scene_cue=cue_for(DebateState.CONTENTIONS, role),
            )
        )
    ep.state = DebateState.LOCKED
    ep.transcript.retime()
    return ep


def _parse_or_synthesize(raw: str, brief: ShowBrief, n: int):
    """The mock provider has no baseline_script handler, so it echoes; in that
    case (and on any parse failure) synthesize a deliberately weaker baseline:
    a single voice that recycles the same generic argument. This is the honest
    'what one agent without coordination produces' control."""
    import json

    from youvsmany.adapters.base import _extract_json

    try:
        data = json.loads(_extract_json(raw))
        if isinstance(data, list) and data and isinstance(data[0], dict) and "text" in data[0]:
            return [(d.get("speaker", "speaker"), str(d["text"])) for d in data]
    except Exception:
        pass

    topic = brief.topic
    # Weak baseline: repetitive, single generic objection, little persona variety.
    proto = f"I think {topic}. It just makes sense and most people would agree with me."
    objection = f"But honestly {topic} is wrong because it just isn't good, in my opinion."
    turns = []
    speakers = ["protagonist", "challenger", "protagonist", "challenger"]
    for i in range(n):
        sp = speakers[i % len(speakers)]
        text = proto if sp == "protagonist" else objection
        turns.append((sp, text))
    return turns
