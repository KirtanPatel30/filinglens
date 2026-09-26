"""One small interface over several LLM providers.

  ollama     local models (default for development)
  anthropic  Claude API (good choice for the hosted demo)
  openai     any OpenAI-compatible API: OpenAI, Groq, Together, OpenRouter, ...
  mock       deterministic fake used by tests and CI
"""
import json
import re
from functools import lru_cache

import httpx

from src.config import settings


class LLMError(RuntimeError):
    pass


class BaseLLM:
    name = "base"
    model = ""

    def complete(self, system: str, user: str, json_mode: bool = False, task: str = "") -> str:
        raise NotImplementedError

    def complete_json(self, system: str, user: str, task: str = "") -> dict:
        text = self.complete(system, user, json_mode=True, task=task)
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise LLMError(f"Expected JSON, got: {text[:200]}")
        return json.loads(match.group(0))


class OllamaLLM(BaseLLM):
    name = "ollama"

    def __init__(self):
        self.model = settings.ollama_model
        self.url = settings.ollama_url.rstrip("/")

    def complete(self, system, user, json_mode=False, task=""):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0},
        }
        if json_mode:
            body["format"] = "json"
        try:
            r = httpx.post(f"{self.url}/api/chat", json=body, timeout=settings.llm_timeout)
        except httpx.ConnectError as exc:
            raise LLMError(
                f"Can't reach Ollama at {self.url}. Start it with `ollama serve` "
                f"and pull the model with `ollama pull {self.model}`."
            ) from exc
        if r.status_code == 404:
            raise LLMError(f"Ollama doesn't have '{self.model}'. Run: ollama pull {self.model}")
        r.raise_for_status()
        return r.json()["message"]["content"]


class AnthropicLLM(BaseLLM):
    name = "anthropic"

    def __init__(self):
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set.")
        self.model = settings.anthropic_model

    def complete(self, system, user, json_mode=False, task=""):
        if json_mode:
            system += "\nRespond with a single JSON object and nothing else."
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1024,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=settings.llm_timeout,
        )
        if r.status_code >= 400:
            raise LLMError(f"Anthropic API error {r.status_code}: {r.text[:300]}")
        return "".join(b.get("text", "") for b in r.json()["content"])


class OpenAICompatLLM(BaseLLM):
    name = "openai"

    def __init__(self):
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set.")
        self.model = settings.openai_model
        self.url = settings.openai_base_url.rstrip("/")

    def complete(self, system, user, json_mode=False, task=""):
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = httpx.post(
            f"{self.url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=body,
            timeout=settings.llm_timeout,
        )
        if r.status_code >= 400:
            raise LLMError(f"API error {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]


class MockLLM(BaseLLM):
    """Predictable answers for tests: quotes the first sentence of source [1]."""

    name = "mock"
    model = "mock"

    def complete(self, system, user, json_mode=False, task=""):
        question = re.search(r"Question:\s*(.+)", user)
        q = question.group(1).strip() if question else user[:200]
        if task == "plan":
            return json.dumps({"search_query": q})
        if task == "reformulate":
            return json.dumps({"search_query": q + " total amount reported"})
        if task == "answer":
            m = re.search(r"\[1\][^\n]*\n(.+?)(?:\n\[2\]|\Z)", user, re.S)
            if not m:
                return "INSUFFICIENT_EVIDENCE"
            first = re.split(r"(?<=[.!?])\s+", m.group(1).strip().replace("\n", " "))[0]
            return f"{first[:300]} [1]"
        return ""


@lru_cache(maxsize=1)
def get_llm() -> BaseLLM:
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return OllamaLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider in {"openai", "groq", "openrouter"}:
        return OpenAICompatLLM()
    if provider == "mock":
        return MockLLM()
    raise LLMError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'")
