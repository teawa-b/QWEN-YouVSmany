"""Live Qwen Cloud provider (OpenAI-compatible chat completions).

POSTs to ${QWEN_BASE_URL}/chat/completions with a Bearer key. This matches the
OpenAI-compatible surface Qwen Cloud exposes for qwen3.7-plus (blueprint
"Project at a glance"). Network access to the Qwen host is required at runtime;
when unavailable, select the mock provider instead."""

from __future__ import annotations

import httpx

from youvsmany.adapters.base import LLMResult


class QwenProvider:
    name = "qwen"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        timeout_s: float = 60.0,
        enable_thinking: bool = False,
    ) -> None:
        if not api_key:
            raise ValueError("QWEN_API_KEY is required for the qwen provider")
        self.model = model
        self._enable_thinking = enable_thinking
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        seed: int | None = None,
    ) -> LLMResult:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Model Studio's raw OpenAI-compatible HTTP surface accepts this as
            # a top-level field. qwen3.7-plus otherwise thinks by default.
            "enable_thinking": self._enable_thinking,
        }
        if seed is not None:
            body["seed"] = seed
        resp = self._client.post(self._url, json=body)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {}) or {}
        return LLMResult(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            raw=data,
        )

    def close(self) -> None:  # pragma: no cover
        self._client.close()
