"""Thin Ollama client. No LangChain — requests + Pydantic validation.

Key decisions:
- format="json" forces valid JSON at the token level.
- num_ctx set explicitly: Ollama's small default silently truncates input.
- Validation failures retry once with the error fed back to the model.
"""
from __future__ import annotations

import json
import logging
from typing import TypeVar

import requests
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/chat"
T = TypeVar("T", bound=BaseModel)


def chat(
    model: str,
    system: str,
    user: str,
    json_mode: bool = False,
    num_ctx: int = 8192,
    temperature: float = 0.3,
    timeout: int = 300,
) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"num_ctx": num_ctx, "temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"
    resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def chat_structured(model: str, system: str, user: str, schema: type[T], **kw) -> T:
    """Chat expecting a JSON response parseable into `schema`. One retry."""
    raw = chat(model, system, user, json_mode=True, **kw)
    for attempt in (1, 2):
        try:
            return schema.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == 2:
                raise
            log.warning("invalid structured output, retrying: %s", exc)
            raw = chat(
                model,
                system,
                user + f"\n\nYour previous output was invalid: {exc}\n"
                       "Return ONLY corrected JSON matching the schema.",
                json_mode=True,
                **kw,
            )
    raise RuntimeError("unreachable")
