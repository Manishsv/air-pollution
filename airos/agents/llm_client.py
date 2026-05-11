"""Provider-agnostic LLM client for AirOS agents.

Uses the OpenAI Python SDK as the transport layer for all OpenAI-compatible
providers (Ollama, Groq, Together, OpenRouter, LM Studio, vLLM, …).

For Anthropic (Claude), uses the native ``anthropic`` SDK with automatic
format translation so the rest of the agent code is unaffected.

Tool-calling throughout uses the OpenAI function-calling format; the Anthropic
backend translates to/from Anthropic's Messages API format transparently.

Usage
-----
    from airos.agents.llm_client import LLMClient
    from airos.agents.llm_config import load_config

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

from airos.agents.llm_config import LLMConfig, load_config

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
# Anthropic format translators
# ---------------------------------------------------------------------------

def _oai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI tool defs → Anthropic tool defs.

    OpenAI:     {"type": "function", "function": {"name": N, "description": D, "parameters": P}}
    Anthropic:  {"name": N, "description": D, "input_schema": P}
    """
    result = []
    for t in tools:
        fn = t.get("function", t)   # handle both wrapped and unwrapped
        result.append({
            "name":         fn["name"],
            "description":  fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _oai_tool_choice_to_anthropic(tool_choice) -> dict | None:
    """Convert OpenAI tool_choice → Anthropic tool_choice.

    OpenAI  "auto"                                    → Anthropic {"type": "auto"}
    OpenAI  "required" / "any"                        → Anthropic {"type": "any"}
    OpenAI  {"type":"function","function":{"name":N}} → Anthropic {"type":"tool","name":N}
    """
    if tool_choice is None or tool_choice == "auto":
        return {"type": "auto"}
    if tool_choice in ("required", "any"):
        return {"type": "any"}
    if isinstance(tool_choice, dict):
        fn_name = (tool_choice.get("function") or {}).get("name")
        if fn_name:
            return {"type": "tool", "name": fn_name}
    return {"type": "auto"}


def _oai_messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Split system prompt out and convert message history to Anthropic format.

    Returns (system_text, anthropic_messages).

    Translations:
      - system messages   → extracted as ``system_text`` (Anthropic takes it separately)
      - tool messages     → grouped into user messages with tool_result content blocks
      - assistant messages with tool_calls → assistant messages with tool_use content blocks
    """
    system_parts: list[str] = []
    out: list[dict] = []

    for msg in messages:
        role = msg.get("role")

        if role == "system":
            system_parts.append(msg.get("content", ""))
            continue

        if role == "tool":
            # OpenAI tool result: {"role":"tool","tool_call_id":id,"content":result}
            # Anthropic expects: {"role":"user","content":[{"type":"tool_result",...}]}
            # Consecutive tool results should be merged into ONE user message.
            block = {
                "type":        "tool_result",
                "tool_use_id": msg["tool_call_id"],
                "content":     msg.get("content", ""),
            }
            # Merge with previous user message if it already holds tool_results
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue

        if role == "assistant":
            content_blocks: list[dict] = []
            text = msg.get("content")
            if text:
                content_blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_raw": args}
                content_blocks.append({
                    "type":  "tool_use",
                    "id":    tc["id"],
                    "name":  fn.get("name", ""),
                    "input": args,
                })
            out.append({"role": "assistant", "content": content_blocks or (text or "")})
            continue

        # user message — pass through (content may be str or list)
        out.append({"role": role, "content": msg.get("content", "")})

    return "\n\n".join(system_parts), out


def _anthropic_response_to_llmresponse(msg) -> "LLMResponse":
    """Parse an ``anthropic.types.Message`` → ``LLMResponse``."""
    tool_calls: list[ToolCall] = []
    text_parts: list[str] = []

    for block in msg.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(
                id=block.id,
                name=block.name,
                arguments=block.input if isinstance(block.input, dict) else {},
            ))

    # stop_reason mapping
    stop_map = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length"}
    stop_reason = stop_map.get(msg.stop_reason or "end_turn", msg.stop_reason or "stop")

    usage = {}
    if msg.usage:
        usage = {
            "prompt_tokens":     msg.usage.input_tokens,
            "completion_tokens": msg.usage.output_tokens,
            "total_tokens":      msg.usage.input_tokens + msg.usage.output_tokens,
        }

    return LLMResponse(
        content="\n".join(text_parts) or None,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        model=msg.model,
        usage=usage,
    )


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
        self._is_anthropic = (self._cfg.provider == "anthropic")
        if self._is_anthropic:
            self._anthropic = self._build_anthropic_client()
            self._openai = None
        else:
            self._openai = self._build_openai_client()
            self._anthropic = None

    def _build_openai_client(self):
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

    def _build_anthropic_client(self):
        try:
            import anthropic as _anthropic_sdk
        except ImportError:
            raise ImportError(
                "anthropic package is not installed. Run: pip install anthropic"
            )
        return _anthropic_sdk.Anthropic(
            api_key=self._cfg.api_key,
            timeout=self._cfg.timeout,
        )

    # keep old attribute name for any direct _openai references in tests
    @property
    def _openai_client(self):
        return self._openai

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
        if self._is_anthropic:
            return self._anthropic_chat(messages, system=system, model=model,
                                        max_tokens=max_tokens, temperature=temperature)
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
        if self._is_anthropic:
            return self._anthropic_chat_with_tools(
                messages, tools, system=system, model=model,
                max_tokens=max_tokens, temperature=temperature,
                tool_choice=tool_choice,
            )
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
    # Anthropic-specific call paths
    # ------------------------------------------------------------------

    def _anthropic_chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        sys_from_msgs, ant_messages = _oai_messages_to_anthropic(messages)
        system_text = system or sys_from_msgs or ""
        kwargs: dict = dict(
            model=model or self._cfg.model,
            messages=ant_messages,
            max_tokens=max_tokens or self._cfg.max_tokens,
            temperature=temperature if temperature is not None else self._cfg.temperature,
        )
        if system_text:
            kwargs["system"] = system_text
        raw = self._anthropic.messages.create(**kwargs)
        return _anthropic_response_to_llmresponse(raw)

    def _anthropic_chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tool_choice: str | dict = "auto",
    ) -> LLMResponse:
        sys_from_msgs, ant_messages = _oai_messages_to_anthropic(messages)
        system_text = system or sys_from_msgs or ""
        ant_tools = _oai_tools_to_anthropic(tools)
        ant_tool_choice = _oai_tool_choice_to_anthropic(tool_choice)
        kwargs: dict = dict(
            model=model or self._cfg.model,
            messages=ant_messages,
            tools=ant_tools,
            tool_choice=ant_tool_choice,
            max_tokens=max_tokens or self._cfg.max_tokens,
            temperature=temperature if temperature is not None else self._cfg.temperature,
        )
        if system_text:
            kwargs["system"] = system_text
        raw = self._anthropic.messages.create(**kwargs)
        return _anthropic_response_to_llmresponse(raw)

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

        # Normalise content — reasoning models (e.g. gptoss family) emit an
        # empty content string and put their thinking in a separate `reasoning`
        # field.  Treat empty string as None so callers can use `if content`.
        content = msg.content or None

        # If content is empty, fall back to the `reasoning` field that some
        # providers (Ollama gptoss, DeepSeek-R1, etc.) include in the message.
        # This gives the agent the model's thinking as text for logging/fallback.
        if content is None:
            # Try standard attribute first (some SDK versions expose it)
            reasoning = getattr(msg, "reasoning", None)
            # Then try model_extra dict (Pydantic v2 extra fields)
            if not reasoning:
                reasoning = (getattr(msg, "model_extra", None) or {}).get("reasoning")
            # Then try the raw dict representation
            if not reasoning:
                try:
                    raw_dict = msg.model_dump() if hasattr(msg, "model_dump") else {}
                    reasoning = raw_dict.get("reasoning")
                except Exception:
                    pass
            if reasoning:
                logger.debug("Reasoning model — using 'reasoning' field as content (%d chars)", len(reasoning))
                content = reasoning   # surface thinking as content for fallback path

        return LLMResponse(
            content=content,
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
