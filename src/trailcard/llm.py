"""Thin client for a local Ollama server.

Everything the app asks of the model goes through :meth:`OllamaClient.chat_json`, which
constrains the reply to a JSON schema (Ollama's ``format`` parameter) so a small local
model still returns something we can validate and render.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx


class LLMUnavailable(RuntimeError):
    """The local model server could not be reached or did not answer usefully."""


class OllamaClient:
    def __init__(self, host: str, model: str, timeout_s: float = 240.0, transport: httpx.BaseTransport | None = None):
        self.host = host.rstrip("/")
        self.model = model
        self._http = httpx.Client(base_url=self.host, timeout=timeout_s, transport=transport)

    def health(self) -> dict[str, Any]:
        """Report whether the server is up and the configured model is pulled."""
        try:
            r = self._http.get("/api/tags", timeout=3.0)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return {"ok": False, "reachable": False, "model": self.model, "detail": str(exc)}
        names = {m.get("name") for m in r.json().get("models", [])}
        have = self.model in names or f"{self.model}:latest" in names
        return {"ok": have, "reachable": True, "model": self.model, "model_pulled": have}

    def chat_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        images: list[bytes] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "user", "content": user}
        if images:
            message["images"] = [base64.b64encode(b).decode("ascii") for b in images]
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,  # we want the answer, not a reasoning trace, and it is much faster
            "format": schema,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "messages": [{"role": "system", "content": system}, message],
        }
        try:
            r = self._http.post("/api/chat", json=payload)
            r.raise_for_status()
            content = r.json()["message"]["content"]
            return json.loads(content)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
