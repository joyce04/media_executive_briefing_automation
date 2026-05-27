# PRDs

Each PRD captures a distinct deliverable surfaced during the May 2026 repo-consolidation work. PRDs are numbered sequentially; the number is stable once published.

| # | Title | Scope | Sequencing |
|---|---|---|---|
| 0001 | [Integrate the Tactics pipeline into the multi-tenant model](./0001-tactics-pipeline-multi-tenant.md) | Medium-large | Independent; benefits from 0002 landing first |
| 0002 | [Multi-tenant Organization CLI](./0002-multi-tenant-org-cli.md) | Medium | Independent; unblocks easy onboarding of test fixtures for 0001 and 0003 |
| 0003 | [Decouple football vocabulary from the core platform](./0003-decouple-football-vocabulary.md) | Medium-large; paired ADR-0003 | Independent; benefits from 0002 landing first |
| 0004 | [Resolve the fate of the auth / billing partial implementation](./0004-auth-billing-fate.md) | Decision PRD; tiny if "delete," large if "build" | Independent |
| 0005 | [CI for both `main` (OpenRouter) and `claude-subscription` branches](./0005-ci-matrix-both-branches.md) | Small-medium | Independent; ship any time |
| 0006 | [Time-based auto-resolution for dormant Stories](./0006-time-based-story-resolution.md) | Small | Independent; one-PR deliverable |
| 0007 | [Harden `.claude/hooks/*.sh` against sibling-path subversion](./0007-harden-claude-hooks.md) | Small | Independent; one-PR deliverable; addresses security-review findings |

Publish each PRD to the GitHub issue tracker (label: `ready-for-agent`) when `gh` is available. The `ready-for-agent` label does not yet exist on the repo — create it first.
