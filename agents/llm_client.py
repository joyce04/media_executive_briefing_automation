from typing import Literal
from langchain_openai import ChatOpenAI
from config.settings import settings

_MODEL_TIERS: dict[str, dict[str, str]] = {
    "starter":    {"fast": settings.haiku_model,  "smart": settings.haiku_model},
    "pro":        {"fast": settings.haiku_model,  "smart": settings.sonnet_model},
    "enterprise": {"fast": settings.sonnet_model, "smart": settings.opus_model},
}


def _make_llm(model: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        temperature=0,
        max_retries=3,
        timeout=60,
    )


def get_haiku() -> ChatOpenAI:
    """Fast, cheap model — used directly when no org context is available."""
    return _make_llm(settings.haiku_model)


def get_sonnet() -> ChatOpenAI:
    """Powerful model — used directly when no org context is available."""
    return _make_llm(settings.sonnet_model)


def get_org_llm(org: dict, mode: Literal["fast", "smart"]) -> ChatOpenAI:
    """Return the appropriate LLM for an org based on its model_tier subscription."""
    tier = org.get("model_tier", "starter")
    model = _MODEL_TIERS.get(tier, _MODEL_TIERS["starter"])[mode]
    return _make_llm(model)


def get_org_model_name(org: dict, mode: Literal["fast", "smart"]) -> str:
    tier = org.get("model_tier", "starter")
    return _MODEL_TIERS.get(tier, _MODEL_TIERS["starter"])[mode]
