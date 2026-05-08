"""Provider-agnostic LLM client for AirOS agents.

Uses the OpenAI Python SDK as the transport layer — every major provider
(Ollama, Groq, Together, OpenRouter, LM Studio, vLLM, …) exposes an
OpenAI-compatible /v1/chat/completions endpoint.

Tool-calling uses the standard OpenAI function-calling format, which is
supported by all major providers and local models (llama3.1+, qwen2.5,
mistral-nemo, etc.).

Usage
-----
    from urban_platform.agents.llm_client import LLMClient
    from urban_platform.agents.llm_config import load_config

    client = LLMClient(load_config())

    # Simple chat
    reply = client.chat([{"role": "user", "content": "Hello"}])
    print(reply.content)

    # Tool-calling loop (see H3ExpertAgent for full example)
    tools = [{"type": "function", "function": {"name": "...", ...}}]
    response = client.chat_with_tools(messages, tools, system="You are...")
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from urban_platform.agents.llm_config import LLMConfig, load_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response wrappers — thin, provider-agnostic
# ---------------------------------------------------------------------------

class ToolCall:
    """A single tool call requested by the model."""
    def __init__(self, id: str, name: str, arguments: dict):
        self.id        = id
        self.name      = name
        self.arguments = arguments   # already parsed dict, never raw JSON string

    def __repr__(self) -> str:
        return f"ToolCall(name={self.name!r}, args={list(self.arguments.keys())})"


class LLMResponse:
    """Normalised response from any provider."""
    def __init__(
        self,
        content: str | None,
        tool_calls: list[ToolCall],
        stop_reason: str,
        model: str,
        usage: dict,
    ):
        self.content    = content          # text content (may be None if only tool calls)
        self.tool_calls = tool_calls       # list of ToolCall objects
        self.stop_reason = stop_reason     # 'stop' | 'tool_calls' | 'length'
        self.model      = model
        self.usage      = usage            # {"prompt_tokens": ..., "completion_tokens": ...}

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def __repr__(self) -> str:
        return (
            f"LLMResponse(stop_reason={self.stop_reason!r}, "
            f"tool_calls={self.tool_calls}, "
            f"content={repr(self.content[:60]) if self.content else None})"
        )


# ---------------------------------------------------------------------------
# Message builder helpers
# ---------------------------------------------------------------------------

def user_msg(content: str) -> dict:
    return {"role": "user", "content": content}

def system_msg(content: str) -> dict:
    return {"role": "system", "content": content}

def assistant_msg(content: str | None = None, tool_calls: list[ToolCall] | None = None) -> dict:
    """Build an assistant message dict suitable for appending to the message history."""
    msg: dict = {"role": "assistant"}
    if content:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, default=str),
                },
            }
            for tc in tool_calls
        ]
    return msg

def tool_result_msg(tool_call_id: str, result: Any) -> dict:
    """Build a tool-result message for the next API call."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(result, default=str) if not isinstance(result, str) else result,
    }


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class LLMClient:
    """OpenAI-SDK-based client, works with any OpenAI-compatible endpoint.

    Parameters
    ----------
    config : LLMConfig
        Provider config (base_url, api_key, model, …).  Build with
        ``load_config()`` to read from env vars, or pass explicit overrides.
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._cfg = config or load_config()
        self._openai = self._build_client()

    def _build_client(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai package is not installed. Run: pip install openai"
            )
        return OpenAI(
            base_url=self._cfg.base_url,
            api_key=self._cfg.api_key,
            timeout=self._cfg.timeout,
        )

    @property
    def config(self) -> LLMConfig:
        return self._cfg

    # ------------------------------------------------------------------
    # Core API calls
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Single-turn chat without tool calling."""
        full_messages = self._prepend_system(messages, system)
        raw = self._openai.chat.completions.create(
            model=model or self._cfg.model,
            messages=full_messages,
            max_tokens=max_tokens or self._cfg.max_tokens,
            temperature=temperature if temperature is not None else self._cfg.temperature,
        )
        return self._parse_response(raw)

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Single API call with tool definitions.

        tools must be in OpenAI format:
            [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]
        """
        full_messages = self._prepend_system(messages, system)
        raw = self._openai.chat.completions.create(
            model=model or self._cfg.model,
            messages=full_messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens or self._cfg.max_tokens,
            temperature=temperature if temperature is not None else self._cfg.temperature,
        )
        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self) -> tuple[bool, str]:
        """Ping the provider with a minimal request.

        Returns (ok: bool, message: str).
        """
        try:
            resp = self.chat(
                [user_msg("Reply with exactly one word: ready")],
                max_tokens=10,
            )
            return True, f"OK — model={self._cfg.model}, reply='{(resp.content or '').strip()[:40]}'"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _prepend_system(self, messages: list[dict], system: str | None) -> list[dict]:
        if not system:
            return messages
        # If there's already a system message at position 0, don't duplicate
        if messages and messages[0].get("role") == "system":
            return messages
        return [system_msg(system)] + messages

    def _parse_response(self, raw) -> LLMResponse:
        choice = raw.choices[0]
        msg    = choice.message

        # Parse tool calls
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if raw.usage:
            usage = {
                "prompt_tokens":     raw.usage.prompt_tokens,
                "completion_tokens": raw.usage.completion_tokens,
                "total_tokens":      raw.usage.total_tokens,
            }

        stop = choice.finish_reason or "stop"

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            stop_reason=stop,
            model=raw.model,
            usage=usage,
        )


# ---------------------------------------------------------------------------
# Tool definition helpers — build OpenAI-format tool dicts
# ---------------------------------------------------------------------------

def make_tool(
    name: str,
    description: str,
    parameters: dict,  # JSON Schema object
) -> dict:
    """Build an OpenAI-format tool dict."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def make_parameters(
    properties: dict[str, dict],
    required: list[str] | None = None,
) -> dict:
    """Build a JSON Schema parameters object."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }
