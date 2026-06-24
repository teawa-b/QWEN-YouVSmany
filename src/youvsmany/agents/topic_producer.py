"""Topic Producer: safety/factuality gate + optional source brief.

Runs at brief time, before anything expensive (blueprint 3.1, 3.4, 13.2). The
gate itself is cheap and deterministic; the source brief (for factual topics)
is generated through the provider and schema-validated."""

from __future__ import annotations

from youvsmany.adapters.base import Provider, complete_structured
from youvsmany.adapters.prompts import make_messages
from youvsmany.contracts.brief import SafetyReport, ShowBrief, SourceBrief
from youvsmany.contracts.enums import TopicKind

# Minimal blocklist for the hackathon MVP; the real system would call a
# moderation model. Topics here are rejected outright.
_BLOCKED = [
    "suicide", "self-harm", "bomb", "weapon", "terror", "child", "porn",
    "genocide", "slur",
]


def safety_gate(brief: ShowBrief) -> SafetyReport:
    topic = brief.topic.strip()
    lower = topic.lower()
    reasons: list[str] = []
    hit = [w for w in _BLOCKED if w in lower]
    if hit:
        return SafetyReport(
            allowed=False,
            reasons=[f"topic touches a disallowed area: {', '.join(hit)}"],
        )
    if len(topic) < 3:
        return SafetyReport(allowed=False, reasons=["topic is too short to debate"])
    requires_source = brief.topic_kind == TopicKind.FACTUAL
    if requires_source:
        reasons.append("factual topic: a source brief will be built before agents argue")
    return SafetyReport(
        allowed=True,
        reasons=reasons,
        requires_source_brief=requires_source,
        sanitized_topic=topic,
    )


def build_source_brief(
    provider: Provider, brief: ShowBrief, *, seed: int = 0
) -> tuple[SourceBrief, int, int, int]:
    messages = make_messages(
        "source_brief",
        {"topic": brief.topic, "seed": seed},
        system=(
            "You are the Topic Producer. For a FACTUAL proposition, assemble a small "
            "fixed source brief of grounded facts so debaters cannot invent "
            "specifications. Return JSON: {topic, facts[], disputed[]}."
        ),
        instruction=f"Build a source brief for the proposition: {brief.topic!r}.",
    )
    sb, result, retries = complete_structured(
        provider, messages, SourceBrief, temperature=0.2, seed=seed
    )
    return sb, result.input_tokens, result.output_tokens, retries
