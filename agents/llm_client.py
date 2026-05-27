"""LLM client - routes through Claude with subscription-first auth.

Backends, in priority order when LLM_BACKEND=auto:
  1. agent_sdk - claude-agent-sdk (spawns the claude CLI under the hood,
                 uses Claude Pro/Max OAuth credentials -- subscription-billed)
  2. cli       - raw claude -p subprocess (fallback if the SDK can't import)
  3. api_key   - anthropic.AsyncAnthropic with ANTHROPIC_API_KEY (escape hatch
                 for CI or when the subscription rate-limits)

All backends present the same async surface as langchain_openai.ChatOpenAI so the
existing agent nodes do not change:

    resp = await llm.ainvoke([SystemMessage(content=...), HumanMessage(content=...)])
    text = resp.content
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from config.settings import settings

Mode = Literal["fast", "smart"]

_MODEL_TIERS: dict[str, dict[Mode, str]] = {
    "starter": {"fast": settings.haiku_model, "smart": settings.haiku_model},
    "pro": {"fast": settings.haiku_model, "smart": settings.sonnet_model},
    "enterprise": {"fast": settings.sonnet_model, "smart": settings.opus_model},
}


@dataclass
class _Response:
    """Minimal AIMessage-compatible response object -- exposes .content."""

    content: str


def _split_messages(messages: list[BaseMessage]) -> tuple[str, str]:
    """Collapse LangChain messages into (system_prompt, user_prompt) strings."""
    systems = [str(m.content) for m in messages if isinstance(m, SystemMessage)]
    humans = [str(m.content) for m in messages if isinstance(m, HumanMessage)]
    return ("\n\n".join(systems).strip(), "\n\n".join(humans).strip())


# --- Backend 1: claude-agent-sdk ------------------------------------------


class _AgentSDKClient:
    def __init__(self, model: str):
        self.model = model

    async def ainvoke(self, messages: list[BaseMessage]) -> _Response:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )

        system_prompt, user_prompt = _split_messages(messages)
        options = ClaudeAgentOptions(
            system_prompt=system_prompt or None,
            model=self.model,
            max_turns=1,
        )
        parts: list[str] = []
        async for msg in query(prompt=user_prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
        return _Response(content="".join(parts).strip())


# --- Backend 2: raw claude -p subprocess (run in worker thread) -----------


class _CLIClient:
    def __init__(self, model: str):
        self.model = model

    async def ainvoke(self, messages: list[BaseMessage]) -> _Response:
        system_prompt, user_prompt = _split_messages(messages)
        prompt = f"{system_prompt}\n\n{user_prompt}".strip() if system_prompt else user_prompt
        args = ["claude", "-p", "--model", self.model, prompt]

        def _run() -> subprocess.CompletedProcess:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )

        result = await asyncio.to_thread(_run)
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr}")
        return _Response(content=result.stdout.strip())


# --- Backend 3: Anthropic API key -----------------------------------------


class _APIKeyClient:
    def __init__(self, model: str):
        from anthropic import AsyncAnthropic

        self.model = model
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key or None)

    async def ainvoke(self, messages: list[BaseMessage]) -> _Response:
        system_prompt, user_prompt = _split_messages(messages)
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0,
            system=system_prompt or "",
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _Response(content=text.strip())


# --- Backend selection ----------------------------------------------------

Backend = Literal["agent_sdk", "cli", "api_key"]


def _resolve_backend() -> Backend:
    choice = settings.llm_backend
    if choice != "auto":
        return choice  # type: ignore[return-value]

    sdk_importable = False
    try:
        import claude_agent_sdk  # noqa: F401

        sdk_importable = True
    except ImportError:
        pass

    has_cli = shutil.which("claude") is not None
    if sdk_importable and has_cli:
        return "agent_sdk"
    if has_cli:
        return "cli"
    if settings.anthropic_api_key:
        return "api_key"
    raise RuntimeError(
        "No Claude backend available. Either install the `claude` CLI and run "
        "`claude /login` (subscription), or set ANTHROPIC_API_KEY in .env."
    )


def _make_llm(model: str):
    backend = _resolve_backend()
    if backend == "agent_sdk":
        return _AgentSDKClient(model)
    if backend == "cli":
        return _CLIClient(model)
    if backend == "api_key":
        return _APIKeyClient(model)
    raise ValueError(f"Unknown LLM backend: {backend}")


def get_haiku():
    """Fast, cheap model -- used directly when no org context is available."""
    return _make_llm(settings.haiku_model)


def get_sonnet():
    """Powerful model -- used directly when no org context is available."""
    return _make_llm(settings.sonnet_model)


def get_org_llm(org: dict, mode: Mode):
    """Return the appropriate LLM for an org based on its model_tier subscription."""
    tier = org.get("model_tier", "starter")
    model = _MODEL_TIERS.get(tier, _MODEL_TIERS["starter"])[mode]
    return _make_llm(model)


def get_org_model_name(org: dict, mode: Mode) -> str:
    tier = org.get("model_tier", "starter")
    return _MODEL_TIERS.get(tier, _MODEL_TIERS["starter"])[mode]
