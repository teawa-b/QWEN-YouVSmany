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
                    "objective": f"run a two-pass mini-duel on the concrete {t} objection",
                }
                for t in tags
            ],
            "rapid_rebuttal_objective": "urgent follow-ups only when the cast is too small",
            "closing_objective": "summarise concessions and the unresolved core",
            "target_turns": int(params.get("target_turns", 16)),
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
        target_words = int(lo + (hi - lo) * jitter)
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
    "{opp}, I hear that. But {counter}. The claim still stands.",
    "No, {opp}, that is not a dodge. {counter_cap}.",
    "Hard case, {opp}. Still, {counter}. The core survives.",
    "Fine, the edge is messy. But {counter}. I am not backing off.",
]

_PROTA_PUSHBACKS = [
    "Then show why that changes the answer, {opp}. I do not think it does.",
    "That is the point, {opp}: reality is not always clean.",
    "I am not hiding from {point}. I am saying it narrows the answer.",
    "Name the case where {point} actually flips it, {opp}. You cannot.",
    "You keep circling {point}, {opp}. It still does not touch the core.",
]

_CHALLENGER_OPENERS = [
    "{opp}, that sounds tidy, but {point} breaks it. Are you brushing that aside?",
    "Hold on, {opp}. {point_cap} is the problem, not a footnote.",
    "You make this sound obvious, {opp}, but {point} is the hard part.",
    "Here is where it cracks, {opp}: {point}. Answer that, not the easy version.",
    "Be honest, {opp} - {point} is the bit your claim quietly skips.",
]

_CHALLENGER_PUSHBACKS = [
    "No, {opp}, that is the dodge. You left {point} sitting there.",
    "That still does not land, {opp}. If {point} matters, your answer is too neat.",
    "Come on, {opp}. Calling it messy does not explain {point}.",
    "You moved the goalposts, {opp}. I asked about {point}, not the tidy version.",
    "Still ducking it, {opp}: {point} is the whole question and you skated past.",
]

_RAPID_LINES = [
    "{opp}, yes or no: if {point} is true, why should anyone buy your answer?",
    "Quickly, {opp}: deal with {point} without changing the question.",
    "Then answer the actual pressure point, {opp}: {point}.",
    "One word, {opp}: does {point} sink your claim or not?",
    "No speeches, {opp} - just {point}. Settle it.",
]

# Moderator gavel that ends a one-on-one duel, Jubilee 'Surrounded' style.
_VOTED_OUT = [
    "Time, {opp}. The majority's voted you out - back to your seat.",
    "That's the round, {opp}. You're voted out. Return to your seat.",
    "{opp}, you've been voted out. Please head back to your seat.",
    "Good work, {opp} - the vote's in, you're out. Take your seat.",
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

    if role == "moderator":
        if "voted out" in objective:
            # Crafted ritual line: keep it whole so the gavel never clips mid-phrase.
            return _clip_words(_pick(_VOTED_OUT, jitter).format(opp=opp_name), 16)
        elif state == "CLOSING":
            base = "Time. Closings now - no new arguments."
        else:
            base = f"Keep it tight. {name} wants one direct answer on {otag}, then we move."
    elif role == "protagonist":
        if state == "OPENING":
            # Crafted establishing beat: keep the full "surrounded" framing intact.
            return _clip_words(
                f"One of me, all of you. I am defending that {short}, claim by claim. "
                f"Come change my mind.",
                30,
            )
        elif state == "CLOSING":
            base = (
                f"Closing it out: {short} still holds. The others found messy edges, but not "
                f"a better answer to the main question."
            )
        elif "first claim" in objective or "next claim" in objective:
            ordinal = "first" if "first claim" in objective else "next"
            # Crafted claim card: keep the whole assertion + the dare to flip it.
            return _clip_words(f"My {ordinal} claim is that {counter}. Come change my mind.", 18)
        elif "pushback" in objective or "narrowest" in objective:
            tmpl = _pick(_PROTA_PUSHBACKS, jitter, bump)
            base = tmpl.format(
                opp=opp_name,
                counter=counter,
                counter_cap=counter_cap,
                point=point,
                short=short,
            )
        else:
            tmpl = _pick(_PROTA_REBUTTALS, jitter, bump)
            base = tmpl.format(opp=opp_name, counter=counter, counter_cap=counter_cap, short=short)
    else:
        if state == "RAPID_REBUTTAL":
            tmpl = _pick(_RAPID_LINES, jitter, bump)
            base = tmpl.format(opp=opp_name, point=point)
        elif "push" in objective:
            tmpl = _pick(_CHALLENGER_PUSHBACKS, jitter, bump)
            base = tmpl.format(opp=opp_name, point=point, point_cap=point_cap, rebuttal=rebuttal)
        else:
            tmpl = _pick(_CHALLENGER_OPENERS, jitter, bump)
            base = tmpl.format(opp=opp_name, point=point, point_cap=point_cap, rebuttal=rebuttal)
        # A duel opens with a quick handshake; clip the substance first so the
        # greeting never eats the pressure point, then prepend it whole.
        if objective.startswith("greet your opponent first"):
            return f"{_pick(_GREETINGS, jitter)} {_clip_words(base, max(8, target_words))}"
    return _clip_words(base, max(8, target_words))
