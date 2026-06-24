"""Provider protocol + structured-output helper with schema validation/retry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    """Minimal text-generation surface used by every agent."""

    name: str
    model: str

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        seed: int | None = None,
    ) -> LLMResult: ...


def _extract_json(text: str) -> str:
    """Pull the first balanced JSON object/array out of a model response."""
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    if start == -1:
        return text
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


class StructuredError(RuntimeError):
    pass


def complete_structured(
    provider: Provider,
    messages: list[dict[str, str]],
    schema: type[T],
    *,
    temperature: float = 0.5,
    max_tokens: int = 900,
    seed: int | None = None,
    max_attempts: int = 3,
) -> tuple[T, LLMResult, int]:
    """Call the provider and validate the JSON response against `schema`.

    Reject malformed model output before it contaminates later stages
    (blueprint 12 "Schema validation"). Returns (model, last_result, retries)."""

    retries = 0
    last_err: Exception | None = None
    convo = list(messages)
    aggregate = LLMResult(text="")
    for attempt in range(max_attempts):
        result = provider.complete(
            convo, temperature=temperature, max_tokens=max_tokens, seed=seed
        )
        aggregate.input_tokens += result.input_tokens
        aggregate.output_tokens += result.output_tokens
        aggregate.text = result.text
        try:
            payload = json.loads(_extract_json(result.text))
            return schema.model_validate(payload), aggregate, retries
        except (json.JSONDecodeError, ValidationError) as err:
            last_err = err
            retries += 1
            convo = convo + [
                {"role": "assistant", "content": result.text},
                {
                    "role": "user",
                    "content": (
                        "That was not valid against the required JSON schema "
                        f"({type(err).__name__}: {err}). Return ONLY a single valid "
                        "JSON object matching the schema, no prose, no code fences."
                    ),
                },
            ]
    raise StructuredError(f"schema {schema.__name__} not satisfied after {max_attempts} attempts: {last_err}")
