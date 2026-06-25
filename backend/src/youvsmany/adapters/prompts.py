"""Prompt construction shared by every provider.

Each structured call carries a machine-readable directive line
(`YVM_TASK=<name> PARAMS=<json>`) at the top of the system message followed by
human-readable instructions. The live Qwen model reads the prose; the offline
MockProvider parses the directive so the whole pipeline is reproducible without
network."""

from __future__ import annotations

import json
import re
from typing import Any

_TASK_RE = re.compile(r"YVM_TASK=(\w+)\s+PARAMS=(\{.*?\})\s*(?:\n|$)", re.DOTALL)


def make_messages(
    task: str,
    params: dict[str, Any],
    *,
    system: str,
    instruction: str,
) -> list[dict[str, str]]:
    directive = f"YVM_TASK={task} PARAMS={json.dumps(params, ensure_ascii=False)}\n"
    return [
        {"role": "system", "content": directive + system},
        {"role": "user", "content": instruction},
    ]


def parse_directive(messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    for m in messages:
        if m.get("role") == "system":
            match = _TASK_RE.search(m["content"])
            if match:
                return match.group(1), json.loads(match.group(2))
    return "", {}
