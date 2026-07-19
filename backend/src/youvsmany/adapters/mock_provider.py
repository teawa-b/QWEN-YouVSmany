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

_GENERIC_CONTENTION_LIB: dict[str, dict[str, Any]] = {
    "framing": {
        "contention": "{topic} dodges what the words actually mean",
        "points": ["the first real example", "changing the definition", "ancestor versus finished thing"],
        "opening": "force a plain definition before the answer",
        "counter": "narrowing the claim is not dodging it",
        "rebuttal": "a moving definition dodges the question",
    },
    "evidence": {
        "contention": "{topic} has not met the burden of proof",
        "points": ["the missing proof", "the jump from story to evidence", "the claim everyone repeats"],
        "opening": "ask what evidence would actually settle it",
        "counter": "ordinary reasoning can still carry it",
        "rebuttal": "confidence is not evidence",
    },
    "consequences": {
        "contention": "{topic} creates the wrong lesson if people accept it casually",
        "points": ["the lesson people take", "the messy case", "calling the question settled"],
        "opening": "press the real-world stakes of accepting the claim",
        "counter": "the answer does not depend on life lessons",
        "rebuttal": "bad reasoning still matters even on a playful topic",
    },
    "edge-cases": {
        "contention": "{topic} breaks once the awkward cases show up",
        "points": ["the awkward exception", "the borderline case", "the simple answer breaking"],
        "opening": "bring the awkward exception into the room",
        "counter": "exceptions can define the boundary",
        "rebuttal": "a boundary that only works after exceptions is too convenient",
    },
    "values": {
        "contention": "{topic} rewards the wrong standard",
        "points": ["being technically right", "clarity versus cleverness", "the reasoning it normalizes"],
        "opening": "ask what standard the audience should reward",
        "counter": "clarity and accuracy can point the same way",
        "rebuttal": "clever accuracy can still mislead people",
    },
}

_GENERIC_TAGS = ["framing", "evidence", "consequences", "edge-cases", "values"]


def _hash_float(parts: str) -> float:
    h = hashlib.sha256(parts.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _lib_for(tag: str) -> dict[str, Any]:
    if tag in _CONTENTION_LIB:
        return _CONTENTION_LIB[tag]
    if tag in _GENERIC_CONTENTION_LIB:
        return _GENERIC_CONTENTION_LIB[tag]
    return {
        "contention": f"{{topic}} has a weak spot around {tag}",
        "points": [f"the hard {tag} example", f"the overlooked {tag} tradeoff", f"the messy {tag} exception"],
        "opening": f"press the concrete {tag} example",
        "counter": f"the {tag} concern narrows the claim but does not erase it",
        "rebuttal": f"the {tag} concern still deserves a direct answer",
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
        n = int(params.get("num_challengers", 2))
        while len(tags) < n:
            tags.append(_GENERIC_TAGS[len(tags) % len(_GENERIC_TAGS)])
        tags = tags[:n]
        names = _distinct_names(topic, seed, n + 1)

        protagonist = {
            "character_id": "protagonist",
            "display_name": names[0],
            "role": "protagonist",
            "stance": stance,
            "visual_presentation": _presentation_for_name(names[0]),
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
                    "visual_presentation": _presentation_for_name(names[1 + i]),
                    "core_contention": lib["contention"].format(topic=topic),
                    "contention_tag": tag,
                    "supporting_points": list(lib["points"]),
                    "personality": _persona(f"ch{i}", topic, seed),
                    "boundaries": ["no personal insults", "no invented facts"],
                }
            )
        # No moderator: the cast is just the debating voices (1 protagonist + N
        # challengers). The voted-out gavel is rendered as a non-spoken caption.
        return {"protagonist": protagonist, "challengers": challengers, "moderator": None}

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
                "response_length_range": [7, 10],
            }
        return {
            "opening": lib["opening"],
            "expected_counter": lib["counter"],
            "rebuttal": lib["rebuttal"],
            "main_points": list(lib["points"])[:2] + [lib["rebuttal"]],
            "fallback_point": f"at minimum, {tag} deserves a real answer",
            "genuine_concession": f"the {tag} case has one fair exception",
            "response_length_range": [7, 10],
        }

    def _task_plan(self, params: dict, seed: int) -> dict:
        thesis = params.get("thesis", "the proposition holds")
        tags: list[str] = list(params.get("tags") or [])
        return {
            "thesis": thesis,
            "opening_objective": "state the thesis and invite the whole room to challenge one claim",
            "contentions": [
                {
                    "challenger_id": f"challenger_{t}",
                    "contention_tag": t,
                    "objective": f"press the shared claim from the concrete {t} angle",
                }
                for t in tags
            ],
            "rapid_rebuttal_objective": "extra crossfire only if the room needs more turns",
            "closing_objective": "summarise the room's strongest pressure and the unresolved core",
            "target_turns": int(params.get("target_turns", 7)),
        }

    def _task_turn(self, params: dict, seed: int) -> dict:
        state = params.get("state", "CONTENTIONS")
        role = params.get("role", "challenger")
        name = params.get("speaker_name", "Speaker")
        tag = params.get("contention_tag")
        opp_tag = params.get("opposing_tag")
        opp_name = params.get("opposing_name") or "you"
        objective = params.get("objective", "")
        latest = params.get("latest_opposing_claim", "")
        topic = params.get("topic", "the proposition")
        lo, hi = (params.get("length_range") or [18, 40])
        jitter = _hash_float(f"{name}{state}{tag}{opp_tag}{seed}{params.get('index')}")
        # These templates are authored for the full short-form allowance;
        # random shortening made otherwise clean lines end mid-thought.
        target_words = int(hi)
        text = _line(
            state,
            role,
            name,
            tag,
            opp_tag,
            opp_name,
            objective,
            latest,
            topic,
            target_words,
            jitter,
        )
        return {"text": text}


_NAME_POOL = ["Mara", "Devin", "Priya", "Otis", "Lena", "Caleb", "Nadia", "Rhys", "Tom", "Iris"]
_FEMALE_PRESENTING_NAMES = {"mara", "priya", "lena", "nadia", "iris"}
_MALE_PRESENTING_NAMES = {"devin", "otis", "caleb", "rhys", "tom"}


def _presentation_for_name(name: str) -> str:
    key = name.strip().split()[0].lower()
    if key in _FEMALE_PRESENTING_NAMES:
        return "female"
    if key in _MALE_PRESENTING_NAMES:
        return "male"
    return "neutral"


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
    floor = max(6, target - 7)
    for end in range(min(target, len(words)), floor - 1, -1):
        if words[end - 1].endswith((".", "?", "!")):
            return " ".join(words[:end])
    out = " ".join(words[:target])
    return out.rstrip(",;:") + "."


def _short_topic(topic: str) -> str:
    """A compact noun phrase for the proposition (avoids restating the whole line)."""
    t = topic.strip().rstrip(".")
    return t[:1].lower() + t[1:] if t else "the case"


# Humanized turn templates. These keep the offline provider close to the intended
# live Qwen behavior.
_PROTA_REBUTTALS = [
    "{opp}, fair pressure. Still, {counter}.",
    "No dodge, {opp}: {counter}.",
    "Hard case, {opp}. The core survives.",
    "The edge is messy. The claim still holds.",
]

_PROTA_ROOM_REPLIES = [
    "Different angles, same answer: {counter}.",
    "{opp}, fair pressure. Still, {counter}.",
    "The pile-on lands, but {counter}.",
    "I hear the room. {counter_cap}.",
]

_PROTA_PUSHBACKS = [
    "That narrows the claim; it does not overturn it.",
    "{opp}, messy is not the same as wrong.",
    "{point_cap} matters, but the center still holds.",
    "That pressure lands, {opp}. It still does not decide this.",
    "You found an edge, {opp}, not a knockout.",
]

_CHALLENGER_OPENERS = [
    "{opp}, {point} breaks that claim.",
    "{point_cap} is the real problem, {opp}.",
    "Your claim skips {point}, {opp}.",
    "{opp}, answer {point}; do not dodge.",
    "Be honest, {opp}: you skipped {point}.",
]

_CHALLENGER_BUILDERS = [
    "Yes, {opp}: {point} makes it worse.",
    "Add {point}; the claim starts wobbling.",
    "Now {point} is the test, {opp}.",
    "Not just that, {opp}: add {point}.",
    "The pile-on is {point}, {opp}.",
]

_CHALLENGER_PUSHBACKS = [
    "{opp}, you still have not answered {point}.",
    "{point_cap} still breaks your answer, {opp}.",
    "Messy does not explain {point}, {opp}.",
    "No goalpost shift, {opp}. Answer {point}.",
    "Still ducking {point}, {opp}.",
]

_RAPID_LINES = [
    "{opp}, yes or no: if {point} is true, why should anyone buy your answer?",
    "Quickly, {opp}: deal with {point} without changing the question.",
    "Then answer the actual pressure point, {opp}: {point}.",
    "One word, {opp}: does {point} sink your claim or not?",
    "No speeches, {opp} - just {point}. Settle it.",
]

_GREETINGS = ["Nice to meet you.", "Hey, good to meet you.", "How's it going?"]


def _clean_sentence(text: str) -> str:
    if not text:
        return ""
    return text[:1].upper() + text[1:].rstrip(".")


def _pick(items: list[str], jitter: float, bump: int = 0) -> str:
    return items[(int(jitter * len(items)) + bump) % len(items)]


def _line(
    state,
    role,
    name,
    tag,
    opp_tag,
    opp_name,
    objective,
    latest,
    topic,
    target_words,
    jitter,
) -> str:
    lib = _lib_for(tag) if tag else None
    opp_lib = _lib_for(opp_tag) if opp_tag else None
    short = _short_topic(topic)
    otag = opp_tag or "that point"
    # When the repetition guard regenerates a turn it appends "do not restate" to
    # the objective once per retry; honor that by rotating both the concrete point
    # and the template so a deep one-on-one duel does not echo itself.
    bump = objective.count("do not restate")
    if lib:
        point = lib["points"][(int(jitter * len(lib["points"])) + bump) % len(lib["points"])]
    else:
        point = otag
    if opp_lib and role == "protagonist":
        point = opp_lib["points"][(int(jitter * len(opp_lib["points"])) + bump) % len(opp_lib["points"])]
    source_lib = opp_lib if role == "protagonist" and opp_lib else lib or _lib_for(otag)
    counter = source_lib["counter"]
    rebuttal = source_lib["rebuttal"]
    point_cap = _clean_sentence(point)
    counter_cap = _clean_sentence(counter)

    if role == "protagonist":
        if state == "OPENING":
            # The hook is also the shared claim card in the short-form cut.
            if len(short.split()) <= 4 and not short.endswith("?"):
                return f"My claim is that {short}. Prove it."
            return "I back the proposition on screen. Prove me wrong."
        elif state == "CLOSING":
            base = "The edges got tested. The central claim still stands."
        elif objective.startswith("State the shared claim") or "first claim" in objective or "next claim" in objective:
            # Crafted claim card: keep the whole assertion + the dare to flip it.
            return _clip_words(
                f"My claim is that {short}; your best objections can test the edges, "
                "not erase the center. All of you, change my mind.",
                max(7, target_words),
            )
        elif "answer the room" in objective:
            tmpl = _pick(_PROTA_ROOM_REPLIES, jitter, bump)
            base = tmpl.format(
                opp=opp_name,
                counter=counter,
                counter_cap=counter_cap,
                point=point,
                point_cap=point_cap,
                short=short,
            )
        elif "pushback" in objective or "narrowest" in objective or "follow-up" in objective:
            tmpl = _pick(_PROTA_PUSHBACKS, jitter, bump)
            base = tmpl.format(
                opp=opp_name,
                counter=counter,
                counter_cap=counter_cap,
                point=point,
                point_cap=point_cap,
                short=short,
            )
        else:
            tmpl = _pick(_PROTA_REBUTTALS, jitter, bump)
            base = tmpl.format(opp=opp_name, counter=counter, counter_cap=counter_cap, short=short)
    else:
        if state == "RAPID_REBUTTAL":
            tmpl = _pick(_RAPID_LINES, jitter, bump)
            base = tmpl.format(opp=opp_name, point=point)
        elif "build on" in objective:
            tmpl = _pick(_CHALLENGER_BUILDERS, jitter, bump)
            base = tmpl.format(opp=opp_name, point=point, point_cap=point_cap, rebuttal=rebuttal)
        elif "push" in objective or "follow up" in objective:
            tmpl = _pick(_CHALLENGER_PUSHBACKS, jitter, bump)
            base = tmpl.format(opp=opp_name, point=point, point_cap=point_cap, rebuttal=rebuttal)
        else:
            tmpl = _pick(_CHALLENGER_OPENERS, jitter, bump)
            base = tmpl.format(opp=opp_name, point=point, point_cap=point_cap, rebuttal=rebuttal)
        # A duel opens with a quick handshake; clip the substance first so the
        # greeting never eats the pressure point, then prepend it whole.
        if objective.startswith("greet your opponent first"):
            return f"{_pick(_GREETINGS, jitter)} {_clip_words(base, max(8, target_words))}"
    return _clip_words(base, max(7, target_words))
