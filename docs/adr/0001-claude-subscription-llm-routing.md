# Route LLM calls through the Claude subscription, with API key as escape hatch

This repository is the development variant of the media-intelligence pipeline. The production sibling (`kfa_daily_media_intel/`) bills every LLM call through OpenRouter. To remove that meter during local development and experimentation, this variant routes calls through the developer's existing Claude Pro/Max subscription via OAuth.

## Decision

`agents/llm_client.py` resolves a backend per call using `LLM_BACKEND` from `.env`:

1. **`agent_sdk`** — `claude-agent-sdk` against subscription OAuth (preferred, subscription-billed).
2. **`cli`** — raw `claude -p` subprocess (fallback if the SDK import fails but the CLI is installed).
3. **`api_key`** — `anthropic.AsyncAnthropic` with `ANTHROPIC_API_KEY` (escape hatch when the subscription rate-limits, or for unattended CI).

When `LLM_BACKEND=auto` (the default), the resolver walks the chain top-to-bottom and picks the first usable backend.

## Why this is worth recording

Every other Claude-using project on the developer's machine uses one client, configured once. This one has three, with an auto-resolver between them. The first reader to open `agents/llm_client.py` will assume the complexity is accidental and try to simplify it — this ADR exists to stop that.

The auto-resolver is also surprising because it can silently switch backends between runs (e.g. CLI uninstalled → falls back to API key → cost goes from $0 to $X without a code change). That trade-off — convenience over predictability — was deliberate and is appropriate **only for the local variant**. The production sibling deliberately does not do this.

## Considered alternatives

- **API-key-only, matching production.** Rejected: defeats the purpose of the local variant, which exists specifically to eliminate per-call billing during dev.
- **Subscription-only, no fallback.** Rejected: when the subscription rate-limits, the pipeline becomes unrunnable, including from CI where OAuth is impractical.
- **Two separate client classes selected by the caller.** Rejected: every agent node would need to know which one to construct; the chokepoint pattern (`get_org_llm`) is more valuable.

## Consequences

- Touching `agents/llm_client.py` affects every node — no other file constructs LLM clients.
- The agent_sdk backend uses `query()` not `ChatAnthropic`, so a thin `_Response` shim adapts to the LangChain-message call shape every node uses (`await llm.ainvoke([SystemMessage, HumanMessage])`).
- Cost observability is weaker than in production — the subscription billing isn't per-call attributable.
