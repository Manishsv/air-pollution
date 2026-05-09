"""LLM provider configuration for AirOS agents.

All agent LLM calls go through this config — no provider SDK is imported
anywhere else.  Switch providers by changing .env variables, no code changes.

Environment variables
---------------------
LLM_PROVIDER     — Provider preset name (default: ollama)
                   One of: ollama | openai | groq | together | openrouter | custom
LLM_BASE_URL     — Override the provider's default base URL
LLM_API_KEY      — API key (use 'ollama' for local Ollama, not needed)
LLM_MODEL        — Model name (overrides provider default)
LLM_MAX_TOKENS   — Max tokens for agent responses (default: 4096)
LLM_TEMPERATURE  — Sampling temperature (default: 0.1 — deterministic for analysis)
LLM_TIMEOUT      — HTTP timeout in seconds (default: 120)

Supported providers and their defaults
---------------------------------------
ollama      base_url=http://localhost:11434/v1   model=gpt-oss:20b-cloud
            Local inference, no API key needed.
            Tool-calling models: gpt-oss:20b-cloud, gpt-oss:120b-cloud, llama3.1, qwen2.5, mistral-nemo
            Note: gpt-oss cloud variants are reasoning models (content="" but tool_calls work)

openai      base_url=https://api.openai.com/v1   model=gpt-4o-mini
            Set LLM_API_KEY=sk-...

groq        base_url=https://api.groq.com/openai/v1   model=llama-3.3-70b-versatile
            Very fast inference. Set LLM_API_KEY=gsk_...

together    base_url=https://api.together.xyz/v1   model=meta-llama/Llama-3.3-70B-Instruct-Turbo
            Set LLM_API_KEY=...

openrouter  base_url=https://openrouter.ai/api/v1   model=google/gemini-flash-1.5
            Access any model via one key. Set LLM_API_KEY=sk-or-...

lmstudio    base_url=http://localhost:1234/v1   model=<loaded-in-ui>
            Local LM Studio server.

custom      Use LLM_BASE_URL + LLM_API_KEY + LLM_MODEL directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Provider presets
# ---------------------------------------------------------------------------

PROVIDER_PRESETS: dict[str, dict] = {
    "ollama": {
        "base_url":      "http://localhost:11434/v1",
        "api_key":       "ollama",           # Ollama ignores the key
        "default_model": "gpt-oss:20b-cloud",
        "label":         "Ollama (local)",
        "notes":         "Tool-calling models: gpt-oss:20b-cloud, gpt-oss:120b-cloud, llama3.1, qwen2.5, mistral-nemo  |  run: ollama list",
    },
    "openai": {
        "base_url":      "https://api.openai.com/v1",
        "api_key_env":   "LLM_API_KEY",
        "default_model": "gpt-4o-mini",
        "label":         "OpenAI",
        "notes":         "Models: gpt-4o, gpt-4o-mini, gpt-4-turbo",
    },
    "groq": {
        "base_url":      "https://api.groq.com/openai/v1",
        "api_key_env":   "LLM_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "label":         "Groq (fast inference)",
        "notes":         "Free tier available. Models: llama-3.3-70b-versatile, mixtral-8x7b-32768",
    },
    "together": {
        "base_url":      "https://api.together.xyz/v1",
        "api_key_env":   "LLM_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "label":         "Together AI",
        "notes":         "Open models at scale. Tool-calling: Llama-3.1-70B+",
    },
    "openrouter": {
        "base_url":      "https://openrouter.ai/api/v1",
        "api_key_env":   "LLM_API_KEY",
        "default_model": "google/gemini-flash-1.5",
        "label":         "OpenRouter (multi-model)",
        "notes":         "Access 200+ models with one key. Supports claude, gpt, gemini, llama etc.",
    },
    "lmstudio": {
        "base_url":      "http://localhost:1234/v1",
        "api_key":       "lmstudio",
        "default_model": "local-model",
        "label":         "LM Studio (local)",
        "notes":         "Start LM Studio → Local Server tab → Start Server",
    },
    "custom": {
        "base_url":      "",
        "api_key_env":   "LLM_API_KEY",
        "default_model": "",
        "label":         "Custom (OpenAI-compatible)",
        "notes":         "Any server exposing /v1/chat/completions (vLLM, text-generation-webui, etc.)",
    },
}

ALL_PROVIDERS = list(PROVIDER_PRESETS.keys())


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class LLMConfig:
    provider:     str
    base_url:     str
    api_key:      str
    model:        str
    max_tokens:   int   = 4096
    temperature:  float = 0.1
    timeout:      int   = 120

    @property
    def label(self) -> str:
        return PROVIDER_PRESETS.get(self.provider, {}).get("label", self.provider)

    def to_dict(self) -> dict:
        return {
            "provider":    self.provider,
            "base_url":    self.base_url,
            "model":       self.model,
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
        }


# ---------------------------------------------------------------------------
# Config loader — env vars → LLMConfig
# ---------------------------------------------------------------------------

def load_config(overrides: Optional[dict] = None) -> LLMConfig:
    """Load LLM config from environment variables, with optional dict overrides.

    Priority: overrides dict > env vars > provider preset defaults.
    """
    ov = overrides or {}

    provider = ov.get("provider") or os.environ.get("LLM_PROVIDER", "ollama").lower()
    preset   = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])

    # Base URL: override → env → preset
    base_url = (
        ov.get("base_url")
        or os.environ.get("LLM_BASE_URL")
        or preset["base_url"]
    )

    # API key: override → env → preset default
    api_key = (
        ov.get("api_key")
        or os.environ.get("LLM_API_KEY", "")
        or preset.get("api_key", "")
    )

    # Model: override → env → preset default
    model = (
        ov.get("model")
        or os.environ.get("LLM_MODEL", "")
        or preset["default_model"]
    )

    return LLMConfig(
        provider=provider,
        base_url=base_url,
        api_key=api_key or "no-key",   # openai SDK requires non-empty string
        model=model,
        max_tokens=int(ov.get("max_tokens") or os.environ.get("LLM_MAX_TOKENS", 4096)),
        temperature=float(ov.get("temperature") or os.environ.get("LLM_TEMPERATURE", 0.1)),
        timeout=int(ov.get("timeout") or os.environ.get("LLM_TIMEOUT", 120)),
    )
