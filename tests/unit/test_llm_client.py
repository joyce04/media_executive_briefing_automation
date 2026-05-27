"""Tests for the three-backend LLM client shim.

The shim must present a single `ainvoke([SystemMessage, HumanMessage]) -> obj.content`
surface regardless of which underlying backend (claude-agent-sdk / claude CLI /
anthropic API) is configured. These tests mock each backend and verify the shim
contract.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm_client import (
    _MODEL_TIERS,
    _AgentSDKClient,
    _APIKeyClient,
    _CLIClient,
    _resolve_backend,
    _split_messages,
    get_org_llm,
    get_org_model_name,
)


# --- pure helpers ---------------------------------------------------------


def test_split_messages_separates_roles():
    sys_p, user_p = _split_messages(
        [
            SystemMessage(content="be terse"),
            HumanMessage(content="hello"),
        ]
    )
    assert sys_p == "be terse"
    assert user_p == "hello"


def test_split_messages_joins_multiple_systems():
    sys_p, _ = _split_messages(
        [
            SystemMessage(content="rule 1"),
            SystemMessage(content="rule 2"),
            HumanMessage(content="go"),
        ]
    )
    assert "rule 1" in sys_p and "rule 2" in sys_p


def test_split_messages_handles_empty_lists():
    assert _split_messages([]) == ("", "")


# --- model tier routing ---------------------------------------------------


def test_get_org_model_name_starter():
    assert get_org_model_name({"model_tier": "starter"}, "fast") == _MODEL_TIERS["starter"]["fast"]
    assert (
        get_org_model_name({"model_tier": "starter"}, "smart") == _MODEL_TIERS["starter"]["smart"]
    )


def test_get_org_model_name_enterprise_smart_is_opus():
    name = get_org_model_name({"model_tier": "enterprise"}, "smart")
    assert "opus" in name.lower()


def test_get_org_model_name_unknown_tier_falls_back_to_starter():
    assert get_org_model_name({"model_tier": "made-up"}, "fast") == _MODEL_TIERS["starter"]["fast"]


def test_get_org_model_name_missing_tier_falls_back_to_starter():
    assert get_org_model_name({}, "fast") == _MODEL_TIERS["starter"]["fast"]


# --- backend resolution ---------------------------------------------------


def test_resolve_backend_explicit_choice_wins(monkeypatch):
    monkeypatch.setattr("agents.llm_client.settings.llm_backend", "api_key")
    assert _resolve_backend() == "api_key"


def test_resolve_backend_auto_prefers_sdk_when_available(monkeypatch):
    monkeypatch.setattr("agents.llm_client.settings.llm_backend", "auto")
    monkeypatch.setattr("agents.llm_client.shutil.which", lambda _: "/usr/local/bin/claude")
    # claude_agent_sdk is imported lazily — if it imports, we get agent_sdk
    with patch.dict("sys.modules", {"claude_agent_sdk": MagicMock()}):
        assert _resolve_backend() == "agent_sdk"


def test_resolve_backend_auto_falls_back_to_cli_when_sdk_missing(monkeypatch):
    monkeypatch.setattr("agents.llm_client.settings.llm_backend", "auto")
    monkeypatch.setattr("agents.llm_client.shutil.which", lambda _: "/usr/local/bin/claude")
    # Simulate ImportError for claude_agent_sdk
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "claude_agent_sdk":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _resolve_backend() == "cli"


def test_resolve_backend_auto_falls_back_to_api_key_when_no_cli(monkeypatch):
    monkeypatch.setattr("agents.llm_client.settings.llm_backend", "auto")
    monkeypatch.setattr("agents.llm_client.shutil.which", lambda _: None)
    monkeypatch.setattr("agents.llm_client.settings.anthropic_api_key", "sk-ant-test")
    assert _resolve_backend() == "api_key"


def test_resolve_backend_auto_raises_when_nothing_configured(monkeypatch):
    monkeypatch.setattr("agents.llm_client.settings.llm_backend", "auto")
    monkeypatch.setattr("agents.llm_client.shutil.which", lambda _: None)
    monkeypatch.setattr("agents.llm_client.settings.anthropic_api_key", "")
    with pytest.raises(RuntimeError, match="No Claude backend"):
        _resolve_backend()


# --- backend ainvoke behavior --------------------------------------------


async def test_agent_sdk_client_aggregates_text_blocks():
    # Use real classes so isinstance() checks behave deterministically.
    class TextBlock:
        def __init__(self, text: str):
            self.text = text

    class AssistantMessage:
        def __init__(self, content):
            self.content = content

    assistant_msg = AssistantMessage([TextBlock("hello "), TextBlock("world")])

    async def fake_query(prompt, options):
        yield assistant_msg

    fake_sdk = MagicMock()
    fake_sdk.AssistantMessage = AssistantMessage
    fake_sdk.TextBlock = TextBlock
    fake_sdk.ClaudeAgentOptions = MagicMock
    fake_sdk.query = fake_query

    with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
        client = _AgentSDKClient(model="claude-haiku-4-5")
        resp = await client.ainvoke(
            [
                SystemMessage(content="terse"),
                HumanMessage(content="hi"),
            ]
        )
    assert resp.content == "hello world"


async def test_cli_client_returns_stdout_on_success(monkeypatch):
    fake_completed = MagicMock(returncode=0, stdout="cli answer\n", stderr="")
    monkeypatch.setattr(
        "agents.llm_client.subprocess.run",
        lambda *a, **kw: fake_completed,
    )

    client = _CLIClient(model="claude-haiku-4-5")
    resp = await client.ainvoke([HumanMessage(content="hi")])
    assert resp.content == "cli answer"


async def test_cli_client_raises_on_nonzero_exit(monkeypatch):
    fake_completed = MagicMock(returncode=1, stdout="", stderr="boom")
    monkeypatch.setattr(
        "agents.llm_client.subprocess.run",
        lambda *a, **kw: fake_completed,
    )
    client = _CLIClient(model="claude-haiku-4-5")
    with pytest.raises(RuntimeError, match="claude CLI exited 1"):
        await client.ainvoke([HumanMessage(content="hi")])


async def test_api_key_client_extracts_text_blocks():
    text_block = MagicMock(type="text", text="api answer")
    fake_response = MagicMock(content=[text_block])

    fake_messages = MagicMock()
    fake_messages.create = AsyncMock(return_value=fake_response)

    fake_anthropic_client = MagicMock(messages=fake_messages)

    with patch("anthropic.AsyncAnthropic", return_value=fake_anthropic_client):
        client = _APIKeyClient(model="claude-haiku-4-5")
        resp = await client.ainvoke(
            [
                SystemMessage(content="sys"),
                HumanMessage(content="user"),
            ]
        )
    assert resp.content == "api answer"
    fake_messages.create.assert_awaited_once()


# --- factory integration --------------------------------------------------


def test_get_org_llm_returns_a_client_with_ainvoke(monkeypatch):
    """Smoke test -- get_org_llm() must return something whose ainvoke is callable."""
    monkeypatch.setattr("agents.llm_client.settings.llm_backend", "api_key")
    monkeypatch.setattr("agents.llm_client.settings.anthropic_api_key", "sk-ant-test")
    with patch("anthropic.AsyncAnthropic"):
        llm = get_org_llm({"model_tier": "pro"}, "smart")
    assert hasattr(llm, "ainvoke")
    assert callable(llm.ainvoke)
