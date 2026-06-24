"""Deterministic offline provider.

Generates schema-valid JSON for every structured task using only the task
directive + a seed, so the full debate pipeline and the 5-seed eval run
reproducibly with no network. It deliberately produces *substantively distinct*
contentions and personas per challenger and dialogue that references the latest
opposing claim, so uniqueness/repetition metrics have real signal."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from youvsmany.adapters.base import LLMResult
from youvsmany.adapters.prompts import parse_directive

_TONES = [
    "precise and mildly impatient",
    "warm but stubborn",
    "dry, analytical, deadpan",
    "energetic and combative",
    "calm and professorial",
]

# Phrase banks keyed by contention tag give each challenger its own substance.
_CONTENTION_LIB: dict[str, dict[str, Any]] = {
    "texture": {
        "contention": "{topic} fails on texture balance",
        "points": ["moisture pooling", "heat-softened structure", "contrast collapse"],
        "opening": "ask for a definition of a balanced bite",
        "counter": "sweet-salty contrast is intentional",
        "rebuttal": "contrast is useful only when structure survives",
    },
    "tradition": {
        "contention": "{topic} disrespects established tradition",
        "points": ["regional authenticity", "craft lineage", "name protection"],
        "opening": "invoke the original canonical form",
        "counter": "traditions evolve with taste",
        "rebuttal": "evolution still needs a defensible core",
    },
    "culinary-innovation": {
        "contention": "{topic} is lazy novelty, not real innovation",
        "points": ["shock over craft", "no technique gain", "trend chasing"],
        "opening": "demand a concrete technique improvement",
        "counter": "delight is its own justification",
        "rebuttal": "delight without craft does not last",
    },
    "productivity": {
        "contention": "{topic} ignores how output actually peaks",
        "points": ["circadian variance", "deep-work windows", "meeting tyranny"],
        "opening": "ask when their best work happens",
        "counter": "discipline beats biology",
        "rebuttal": "discipline aimed at the wrong hour wastes effort",
    },
    "health": {
        "contention": "{topic} overstates the health case",
        "points": ["sleep debt", "light exposure", "stress load"],
        "opening": "ask for the grounded evidence",
        "counter": "habit drives health more than timing",
        "rebuttal": "habit cannot override chronic mistiming",
    },
    "social-rhythm": {
        "contention": "{topic} misreads how people actually connect",
        "points": ["evening culture", "family overlap", "creative hours"],
        "opening": "ask whose schedule society rewards",
        "counter": "mornings are simply more shared",
        "rebuttal": "shared is not the same as better",
    },
    "independence": {
        "contention": "{topic} undervalues autonomy",
        "points": ["self-sufficiency", "low demand", "quiet company"],
        "opening": "ask what 'better companion' means",
        "counter": "loyalty beats independence",
        "rebuttal": "loyalty without space becomes a burden",
    },
    "affection": {
        "contention": "{topic} misjudges real affection",
        "points": ["bonding depth", "responsiveness", "comfort"],
        "opening": "ask how affection is measured",
        "counter": "affection should be earned, not constant",
        "rebuttal": "earned affection still must show up",
    },
    "maintenance": {
        "contention": "{topic} ignores the cost of upkeep",
        "points": ["time", "money", "space"],
        "opening": "ask about daily upkeep",
        "counter": "upkeep is a fair price for joy",
        "rebuttal": "joy priced too high is not a bargain",
    },
    "reasoning": {
        "contention": "{topic} overstates the reasoning gains",
        "points": ["benchmark cherry-picking", "regression cases", "prompt sensitivity"],
        "opening": "ask which benchmark and which split",
        "counter": "aggregate scores clearly improved",
        "rebuttal": "aggregates can hide real regressions",
    },
    "multimodality": {
        "contention": "{topic} leans on multimodality it rarely needs",
        "points": ["modality overhead", "use-case fit", "latency"],
        "opening": "ask for the grounded spec",
        "counter": "more modalities widen the market",
        "rebuttal": "unused capability is just cost",
    },
    "efficiency": {
        "contention": "{topic} trades efficiency for headline scores",
        "points": ["tokens per task", "serving cost", "throughput"],
        "opening": "ask the cost per solved task",
        "counter": "quality justifies the spend",
        "rebuttal": "quality you cannot afford does not ship",
    },
    "identity-fidelity": {
        "contention": "{topic} drifts on identity under motion",
        "points": ["face consistency", "wardrobe drift", "frame coherence"],
        "opening": "ask for an identity check across angles",
        "counter": "reference conditioning fixes identity",
        "rebuttal": "references still slip during fast motion",
    },
    "motion-preservation": {
        "contention": "{topic} loses the source motion and timing",
        "points": ["lip sync", "audio lock", "beat alignment"],
        "opening": "ask whether source timing is preserved",
        "counter": "regeneration buys better visuals",
        "rebuttal": "better frames are useless if timing breaks",
    },
    "cost": {
        "contention": "{topic} wins on quality but loses on cost",
        "points": ["per-second price", "retries", "budget cap"],
        "opening": "ask the all-in cost per accepted clip",
        "counter": "quality reduces total retries",
        "rebuttal": "retries are exactly where cost hides",
    },
}

_GENERIC_TAGS = ["framing", "evidence", "consequences", "edge-cases", "values"]


def _hash_float(parts: str) -> float:
    h = hashlib.sha256(parts.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _lib_for(tag: str) -> dict[str, Any]:
    if tag in _CONTENTION_LIB:
        return _CONTENTION_LIB[tag]
    return {
        "contention": f"{{topic}} is weak on {tag}",
        "points": [f"{tag} gap A", f"{tag} gap B", f"{tag} gap C"],
        "opening": f"press the {tag} angle",
        "counter": f"the {tag} concern is overblown",
        "rebuttal": f"the {tag} concern survives scrutiny",
    }


class MockProvider:
    name = "mock"

    def __init__(self, model: str = "mock-debate-1") -> None:
        self.model = model

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        seed: int | None = None,
    ) -> LLMResult:
        task, params = parse_directive(messages)
        seed = seed if seed is not None else int(params.get("seed", 0))
        handler = getattr(self, f"_task_{task}", None)
        if handler is None:
            payload: Any = {"echo": task or "unknown"}
        else:
            payload = handler(params, seed)
        text = json.dumps(payload, ensure_ascii=False)
        # rough token accounting for the run report
        return LLMResult(
            text=text,
            input_tokens=sum(len(m["content"].split()) for m in messages),
            output_tokens=len(text.split()),
        )

    # --- task handlers -------------------------------------------------

    def _task_source_brief(self, params: dict, seed: int) -> dict:
        topic = params.get("topic", "the topic")
        return {
            "topic": topic,
            "facts": [
                f"{topic}: claim must be tied to a cited or commonly agreed fact.",
                f"{topic}: no fabricated specifications or numbers are permitted.",
            ],
            "disputed": [f"{topic}: relative ranking is genuinely contested."],
        }

    def _task_cast(self, params: dict, seed: int) -> dict:
        topic = params.get("topic", "the proposition")
        stance = params.get("stance", "for")
        opp = "against" if stance == "for" else "for"
        tags: list[str] = list(params.get("tags") or [])
        n = int(params.get("num_challengers", 3))
        while len(tags) < n:
            tags.append(_GENERIC_TAGS[len(tags) % len(_GENERIC_TAGS)])
        tags = tags[:n]
        names = _distinct_names(topic, seed, n + 2)

        protagonist = {
            "character_id": "protagonist",
            "display_name": names[0],
            "role": "protagonist",
            "stance": stance,
            "core_contention": f"{topic} is right on the merits",
            "contention_tag": "thesis",
            "supporting_points": ["clear definition", "strongest case first", "address objections"],
            "personality": _persona("protagonist", topic, seed),
            "boundaries": ["no personal insults", "no invented facts"],
        }
        challengers = []
        for i, tag in enumerate(tags):
            lib = _lib_for(tag)
            challengers.append(
                {
                    "character_id": f"challenger_{tag}",
                    "display_name": names[1 + i],
                    "role": "challenger",
                    "stance": opp,
                    "core_contention": lib["contention"].format(topic=topic),
                    "contention_tag": tag,
                    "supporting_points": list(lib["points"]),
                    "personality": _persona(f"ch{i}", topic, seed),
                    "boundaries": ["no personal insults", "no invented facts"],
                }
            )
        moderator = {
            "character_id": "moderator",
            "display_name": names[-1],
            "role": "moderator",
            "stance": "neutral",
            "core_contention": "keep the debate fair, distinct and on time",
            "contention_tag": "control",
            "supporting_points": ["enforce turns", "kill repetition", "force disputed questions"],
            "personality": _persona("mod", topic, seed),
            "boundaries": ["stay neutral", "no new arguments"],
        }
        return {"protagonist": protagonist, "challengers": challengers, "moderator": moderator}

    def _task_private_notes(self, params: dict, seed: int) -> dict:
        tag = params.get("contention_tag", "framing")
        topic = params.get("topic", "the topic")
        role = params.get("role", "challenger")
        lib = _lib_for(tag)
        if role == "protagonist":
            return {
                "opening": "state the thesis in one crisp sentence",
                "expected_counter": "objections on texture, tradition and novelty",
                "rebuttal": "concede the smallest point, hold the core",
                "main_points": ["define terms", "lead with the strongest case", "pre-empt the obvious objection"],
                "fallback_point": "even skeptics admit the appeal",
                "genuine_concession": "it is not for every palate",
                "response_length_range": [14, 24],
            }
        return {
            "opening": lib["opening"],
            "expected_counter": lib["counter"],
            "rebuttal": lib["rebuttal"],
            "main_points": list(lib["points"])[:2] + [lib["rebuttal"]],
            "fallback_point": f"at minimum, {tag} deserves a real answer",
            "genuine_concession": f"the {tag} case has one fair exception",
            "response_length_range": [10, 20],
        }

    def _task_plan(self, params: dict, seed: int) -> dict:
        thesis = params.get("thesis", "the proposition holds")
        tags: list[str] = list(params.get("tags") or [])
        return {
            "thesis": thesis,
            "opening_objective": "state the thesis and the single strongest reason",
            "contentions": [
                {
                    "challenger_id": f"challenger_{t}",
                    "contention_tag": t,
                    "objective": f"introduce the distinct {t} objection and get a direct reply",
                }
                for t in tags
            ],
            "rapid_rebuttal_objective": "short, sharp exchanges that surface the real disagreement",
            "closing_objective": "summarise concessions and the unresolved core",
            "target_turns": int(params.get("target_turns", 16)),
        }

    def _task_turn(self, params: dict, seed: int) -> dict:
        state = params.get("state", "CONTENTIONS")
        role = params.get("role", "challenger")
        name = params.get("speaker_name", "Speaker")
        tag = params.get("contention_tag")
        opp_tag = params.get("opposing_tag")
        topic = params.get("topic", "the proposition")
        lo, hi = (params.get("length_range") or [18, 40])
        jitter = _hash_float(f"{name}{state}{tag}{opp_tag}{seed}{params.get('index')}")
        target_words = int(lo + (hi - lo) * jitter)
        text = _line(state, role, name, tag, opp_tag, topic, target_words, jitter)
        return {"text": text}


_NAME_POOL = ["Mara", "Devin", "Priya", "Otis", "Lena", "Caleb", "Nadia", "Rhys", "Tom", "Iris"]


def _distinct_names(topic: str, seed: int, count: int) -> list[str]:
    """Deterministic, collision-free name assignment for a cast."""
    start = int(_hash_float(f"names{topic}{seed}") * len(_NAME_POOL))
    return [_NAME_POOL[(start + i) % len(_NAME_POOL)] for i in range(count)]


def _persona(key: str, topic: str, seed: int) -> dict:
    r = _hash_float(f"persona{key}{topic}{seed}")
    return {
        "tone": _TONES[int(r * len(_TONES)) % len(_TONES)],
        "humour": round(0.15 + r * 0.5, 2),
        "assertiveness": round(0.55 + ((r * 7) % 1) * 0.4, 2),
        "concession_threshold": round(0.3 + ((r * 13) % 1) * 0.4, 2),
    }


def _clip_words(text: str, target: int) -> str:
    words = text.split()
    if len(words) <= target:
        return text
    out = " ".join(words[:target])
    return out.rstrip(",;:") + "."


# Protagonist rebuttal templates, varied by the objection being answered so the
# protagonist does not recite one stock line (keeps the repetition metric honest).
_PROTA_REBUTTALS = [
    "On {otag}, I'll grant the narrow case — but the {otag} worry doesn't reach the core of {short}.",
    "The {otag} objection is the strongest one here, and it still only dents the edge, not {short}.",
    "Fair on {otag}; yet fix that one detail and {short} holds exactly as I framed it.",
    "I hear the {otag} point, but it proves a limit, not a refutation — {short} survives it.",
]


def _short_topic(topic: str) -> str:
    """A compact noun phrase for the proposition (avoids restating the whole line)."""
    t = topic.strip().rstrip(".")
    return t[:1].lower() + t[1:] if t else "the case"


def _line(state, role, name, tag, opp_tag, topic, target_words, jitter) -> str:
    lib = _lib_for(tag) if tag else None
    short = _short_topic(topic)
    otag = opp_tag or "that objection"
    if role == "moderator":
        if state == "CLOSING":
            base = "Time. Closing statements now — one tight summary, no new arguments."
        else:
            base = (
                f"Let's keep this fair. On {otag}: one clear claim, one direct answer, "
                f"no reusing ground we've covered."
            )
    elif role == "protagonist":
        if state == "OPENING":
            base = (
                f"My position is simple: {topic}. I'll define terms, lead with the strongest "
                f"reason, and meet every serious objection head on."
            )
        elif state == "CLOSING":
            base = (
                f"To close: {short} still stands. I conceded the smallest point honestly, "
                f"but the core held against every distinct objection."
            )
        else:
            tmpl = _PROTA_REBUTTALS[int(jitter * len(_PROTA_REBUTTALS)) % len(_PROTA_REBUTTALS)]
            base = tmpl.format(otag=otag, short=short)
    else:  # challenger
        contention = lib["contention"].format(topic=short) if lib else f"{short} is weak on {tag}"
        point = (lib["points"][int(jitter * len(lib["points"]))] if lib else tag)
        if state == "RAPID_REBUTTAL":
            base = f"Still on {tag}: {point} is the crack, and you haven't closed it. Answer directly."
        else:
            base = (
                f"My objection is {tag}: {contention}. Concretely, {point} — that's where "
                f"the argument breaks."
            )
    return _clip_words(base, max(8, target_words))
