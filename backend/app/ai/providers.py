"""LLM providers. Thin REST clients (httpx) so behaviour is explicit and failures are contained.

A provider call never raises: it returns AIResult(ok=False, error=...) and the deterministic
workflow carries on. Keys live only in backend environment variables.
"""
import json
import re
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings


@dataclass
class AIResult:
    ok: bool
    provider: str
    model: str = ""
    data: dict | None = None
    error: str | None = None
    latency_ms: float = 0.0
    raw: str = ""


@dataclass
class AIStats:
    calls: int = 0
    failures: int = 0
    by_provider: dict = field(default_factory=dict)

    def record(self, res: AIResult):
        if res.error == "not_configured":
            return
        self.calls += 1
        p = self.by_provider.setdefault(res.provider, {"calls": 0, "failures": 0, "latency_ms": 0.0})
        p["calls"] += 1
        p["latency_ms"] += res.latency_ms
        if not res.ok:
            self.failures += 1
            p["failures"] += 1


stats = AIStats()


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model response."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in model response")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise ValueError("model response is not a JSON object")
    return obj


async def _post(url, headers, payload):
    async with httpx.AsyncClient(timeout=settings.ai_timeout_s) as client:
        return await client.post(url, headers=headers, json=payload)


async def claude_json(system: str, user: str, model: str | None = None, schema=None) -> AIResult:
    """Ask Claude for a JSON object. `schema` is a Pydantic model used to validate the reply."""
    model = model or settings.claude_model_orchestrator
    if not settings.claude_enabled:
        return AIResult(False, "claude", model, error="not_configured")
    t0 = time.perf_counter()
    res = AIResult(False, "claude", model)
    try:
        r = await _post(f"{settings.anthropic_base_url}/v1/messages",
                        {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                        {"model": model, "max_tokens": settings.ai_max_tokens, "system": system,
                         "messages": [{"role": "user", "content": user}]})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        res.raw = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        data = extract_json(res.raw)
        res.data = schema.model_validate(data).model_dump() if schema else data
        res.ok = True
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:300]
    res.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    stats.record(res)
    return res


async def openai_json(system: str, user: str, schema=None) -> AIResult:
    """Ask the OpenAI reviewer model for a JSON object."""
    model = settings.openai_model
    if not settings.openai_enabled:
        return AIResult(False, "openai", model, error="not_configured")
    t0 = time.perf_counter()
    res = AIResult(False, "openai", model)
    try:
        r = await _post(f"{settings.openai_base_url}/v1/chat/completions",
                        {"Authorization": f"Bearer {settings.openai_api_key}", "content-type": "application/json"},
                        {"model": model, "response_format": {"type": "json_object"},
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        res.raw = r.json()["choices"][0]["message"]["content"] or ""
        data = extract_json(res.raw)
        res.data = schema.model_validate(data).model_dump() if schema else data
        res.ok = True
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:300]
    res.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    stats.record(res)
    return res
