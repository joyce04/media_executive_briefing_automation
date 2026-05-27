# PRD 0004 — Resolve the fate of the auth / billing partial implementation

## Problem Statement

The repository contains an incomplete web-tier foundation that is neither finished nor deleted:

- **Schema present**: `users`, `user_orgs`, `refresh_tokens`, `plans`, `subscriptions`, `api_keys` tables in `database/schema_v2.sql`, with a seed of three default plans (`starter` / `pro` / `enterprise` at $0 / $49 / $199 per month).
- **Repositories present and substantial**: `database/repositories/user_repo.py` (138 LOC: password + Google OAuth user CRUD, refresh-token storage with SHA-256 hashing and 30-day expiry, user↔Org membership with roles), `database/repositories/billing_repo.py` (94 LOC: plan + subscription CRUD with Stripe customer/subscription/price-ID columns), and `org_repo.py::generate_api_key / get_org_by_api_key / list_api_keys / revoke_api_key` (key generation, SHA-256 hashing, last-used tracking).
- **Settings declared**: `config/settings.py` has `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `FRONTEND_URL` (CORS).
- **Service layer absent**: no FastAPI/Flask/Express endpoints; no JWT issuance or verification middleware; no Stripe webhook handler; no Google OAuth flow handler; no frontend; no `auth/`, `api/`, or `web/` directory anywhere in the tree.

CONTEXT.md flags this concisely as "dead schema inherited from a sibling web-tier that does not exist in this repository." That description is partially wrong — substantial repository code exists, not just tables — but the conclusion stands: there is no path today by which a `User` row, a `Subscription` row, or a JWT-protected API call enters or leaves this codebase. The CLI is the only operator surface; the pipeline is the only data writer.

This leaves operators and future contributors in a confused state. A new contributor reading `user_repo.py` plausibly assumes there is (or recently was) a web tier they can't find. The settings declare secrets nobody uses. CI tests do not cover these repositories. A future change to a `users`-touching schema migration could land without anyone noticing it isn't actually exercised.

## Solution

Make an explicit decision and execute it. This PRD presents three exhaustive options and recommends one; the implementation PR depends on which option is chosen.

**Option A — Remove (recommended unless there's a roadmap commitment to ship a web tier in the next quarter).** Delete the schema tables, the repositories, the settings, and the gitignored secret fields. Update CONTEXT.md to remove the "Flagged ambiguity" note. Keep the `api_keys` table and methods (they are useful for programmatic CLI access independent of any web tier).

**Option B — Quarantine.** Move the auth/billing repositories under a `_unused/` directory, mark the tables with a `-- UNUSED v2026.05` comment in the schema, and add a `pyproject.toml` `[tool.ruff.per-file-ignores]` block so the dead code does not trigger lints. Cheaper than delete; preserves the work for a future revival without leaving it indistinguishable from live code.

**Option C — Finish.** Build the web tier: a FastAPI service with JWT-based auth, Google OAuth login, Stripe webhook handling, per-Organization billing-status checks gating pipeline execution, an API surface for Organization management, and a minimal frontend (or "API-only — bring your own frontend" if scope is constrained). This is multiple PRDs of work; this PRD scopes the decision and a high-level breakdown of the follow-up PRDs that would be needed.

From the operator's perspective:

- **Option A**: the CLI is acknowledged as the sole operator surface; the repository's footprint and onboarding friction both shrink.
- **Option B**: same as A operationally, but the work isn't thrown away; a future "build the web tier" decision starts from a labeled, intact foundation.
- **Option C**: operators stop being the only entry point; Organizations can self-serve sign-up, billing, sources, recipients, and reports via a hosted dashboard.

## User Stories

(These are written from each option's perspective. Only the chosen option's stories ship.)

### Option A — Remove

1. As a new contributor, I want the repository to contain only code that runs in production, so that I do not waste time reading auth/billing modules that are never invoked.
2. As an operator, I want the `users`, `user_orgs`, `refresh_tokens`, `plans`, `subscriptions` tables removed from `schema_v2.sql`, so that the schema accurately reflects the platform's actual data model.
3. As an operator, I want `user_repo.py` and `billing_repo.py` deleted (plus their tests if any), so that there is no dead code to maintain.
4. As an operator, I want the unused settings (`JWT_SECRET`, `GOOGLE_CLIENT_*`, `STRIPE_*`, `FRONTEND_URL`) removed from `config/settings.py` and `.env.example`, so that operators stop being asked to provide values they do not need.
5. As an operator, I want the `api_keys` table and its repository methods retained, so that programmatic CLI access (e.g. a future cron service running under a service account) remains possible.
6. As an operator at KFA who has been running this pipeline, I want a migration that drops the auth/billing tables without prompting, since they are empty in production, so that the deletion is safe and one-step.
7. As a reader of CONTEXT.md, I want the "Flagged ambiguity" entry about dead schema deleted in the same PR, so that the docs and the code agree.
8. As a developer maintaining this repo, I want the deletion to be a single atomic PR with the title "Remove unused auth/billing scaffold," so that the rationale and scope are obvious in `git log`.

### Option B — Quarantine

9. As a contributor, I want unused auth/billing code clearly marked as such (directory, file headers, ruff ignores), so that I can tell at a glance what is and is not in use.
10. As an operator, I want the unused schema tables annotated in `schema_v2.sql` with a `-- UNUSED since v2026.05; revive via PRD-NNNN` comment so that schema readers know not to depend on them.
11. As a future contributor reviving the work, I want the quarantined code intact (no edits, no deletions) so that the revival starts from a working foundation rather than a reconstruction.
12. As an operator, I want the unused settings removed from `.env.example` even under Option B (the env vars stay declared in `settings.py` so the code compiles, but `.env.example` doesn't ask operators to supply them), so that the onboarding form is not misleading.

### Option C — Finish

13. As an Organization signing up via the hosted dashboard, I want to register with email + password or Google OAuth, so that I can create an account without operator intervention.
14. As an Organization owner, I want to invite users to my Organization with a role (owner / admin / member), so that I can share dashboard access with my team.
15. As an Organization owner, I want to choose a plan and pay via Stripe checkout, so that I can self-serve subscription onboarding.
16. As the platform, I want to refuse to run an Organization's pipeline if its `subscriptions.status` is `past_due` or `canceled` (with grace period), so that non-paying Organizations stop incurring LLM costs.
17. As an Organization admin, I want a dashboard view of the last 30 days of `pipeline_runs` for my Organization including cost, articles processed, and any error, so that I can verify the service is working.
18. As an Organization admin, I want to manage Sources, Entities, Recipients, and Prompt Overrides from the dashboard (the same operations the CLI exposes in PRD 0002), so that I do not need a developer to configure my pipeline.
19. As an Organization admin, I want to generate and revoke API keys from the dashboard, so that I can grant programmatic access to my internal systems.
20. As a Stripe webhook receiver, I want signed webhook events to update `subscriptions.status` and `current_period_end` atomically, so that the platform's view of billing stays in sync with Stripe's.
21. As an operator, I want a Stripe-CLI-based replay test that walks the platform through `trialing → active → past_due → canceled` for a fixture Organization, so that the webhook handler's edge cases are exercised.
22. As an operator, I want JWT access tokens with short TTL (15 min) and refresh tokens (30d, httpOnly cookie) following the existing `refresh_tokens` table contract, so that the token rotation pattern matches what is already in `user_repo.py`.
23. As a security reviewer, I want a documented threat model (in `docs/security/`) covering session fixation, CSRF, token replay, and Stripe webhook spoofing, so that the auth/billing surface has been thought through systematically.
24. As an operator, I want the FastAPI service deployable independently of the pipeline (separate process, shared DB), so that pipeline crashes do not take down the dashboard and vice-versa.
25. As an operator, I want the dashboard's API surface to be the same one the CLI uses internally (PRD 0002's helpers move into a shared service layer), so that there is one authoritative way to mutate an Organization's configuration.

## Implementation Decisions

**Recommendation: Option A (Remove)**, unless a roadmap commitment to ship a hosted web tier within ~one quarter exists. Rationale: the partial implementation is small enough to delete (~250 LOC across two files plus schema + settings), the secrets-asking is actively confusing, and a future revival from `git log` is straightforward thanks to the commit history. Quarantine (Option B) carries the cost of "explain the quarantine" forever without the benefit of working code.

If Option C is chosen, the work decomposes into at least these follow-up PRDs (each substantial):

- **PRD 0004a** — FastAPI service skeleton, JWT auth (access + refresh), Google OAuth login, session-management endpoints.
- **PRD 0004b** — Organization management API (the CRUD that PRD 0002 builds for CLI, exposed as authenticated HTTP endpoints).
- **PRD 0004c** — Stripe integration: Checkout sessions, customer-portal redirect, webhook handler, plan-gating middleware that refuses pipeline runs for non-paying Organizations.
- **PRD 0004d** — Dashboard frontend (React/Next.js or alternative): plan selection, sources/entities/recipients management, run history view, API-key management.
- **PRD 0004e** — Deployment topology: separate FastAPI service container, shared DB, secrets management, observability (Sentry/equivalent).
- **PRD 0004f** — Security review: threat model documentation, penetration test, third-party dependency audit, CSP/CORS hardening.

Each of these would be its own multi-week deliverable. The total scope is comfortably "one engineer for a quarter" or "two engineers for six weeks." This PRD does **not** pre-decide that scope; it asks for the call.

**Decision deliverable.** The owner of this PRD selects A, B, or C. The decision is recorded as ADR-0004 in the same PR. Implementation work begins only after the ADR is merged.

**For Option A specifically** (the recommendation):

- Schema migration drops `users`, `user_orgs`, `refresh_tokens`, `plans`, `subscriptions` (in that order — FK dependencies). Tables are confirmed empty in production by a `SELECT COUNT(*)` pre-check that aborts the migration if any row exists.
- `database/repositories/user_repo.py` and `database/repositories/billing_repo.py` deleted in full.
- `config/settings.py` loses `jwt_secret`, `google_client_id`, `google_client_secret`, `stripe_secret_key`, `stripe_webhook_secret`, `frontend_url`. `.env.example` removes the corresponding lines.
- `database/repositories/org_repo.py::generate_api_key / get_org_by_api_key / list_api_keys / revoke_api_key` are **retained**. API keys are useful for service-to-service access independent of any user/auth model.
- CONTEXT.md "Flagged ambiguities" loses the "Plan / Subscription / User / ApiKey" entry — though "ApiKey" stays in the "in scope" list as a programmatic-access concept worth defining.
- A migration smoke test asserts that running `scripts/db_init.py` against a fresh DB after this PR produces no `users`/`subscriptions`/etc. tables.

## Testing Decisions

A good test for an "Option A" deletion PR asserts the **absence** of the removed surfaces: `import database.repositories.user_repo` raises `ImportError`; `SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'subscriptions', ...)` returns empty after `db_init`; `settings.jwt_secret` raises `AttributeError`. These are cheap, definitive, and immediately diagnostic if a deletion is partial.

**Modules to test (Option A):**

- Schema migration — running `db_init.py` against the existing prod DB removes only the listed tables and leaves all pipeline tables intact. (Integration test against a copy of prod DB structure with seeded plan rows.)
- Repository module disappearance — the two `import` statements named above raise `ImportError`. (Trivial unit test.)
- Settings — the removed fields are no longer attributes of `settings`. (Trivial unit test.)
- API key methods — still present, still exercised. (No change to existing tests; add one if `org_repo` doesn't already test them.)

**For Option C**, testing is the testing strategy of each sub-PRD; no per-PRD-here testing call.

**Prior art:** none — this PRD doesn't fit the existing test patterns because it's primarily a removal. Closest analog is the schema-migration smoke test added by PRD 0001's tactics-to-multitenant migration.

## Out of Scope

For the decision PRD itself:

- The full design of any of the sub-PRDs Option C would spawn. Each one is its own PRD.
- A speculative cost/timeline estimate of Option C. The breakdown is here so the decision is informed; the estimate is the next step if C is chosen.
- A go/no-go on whether the platform should ever have a hosted web tier. That is a product decision separate from this PRD.

For Option A specifically:

- Removing the multi-tenant model itself. Multi-tenancy by `org_id` is platform-defining and stays even without users/plans.
- Removing API keys. They are independently useful for programmatic operator access.

## Further Notes

- The CONTEXT.md "dead schema" note was partially inaccurate when written — substantial repository code exists, not just tables. Fix CONTEXT.md in the same PR that resolves this decision.
- The `subscriptions.status` check the platform would gate on under Option C does not exist today, so adopting Option A does not regress anything. Adopting C is purely additive.
- If Option B is chosen and the work is revived later, the `_unused/` directory move plus the schema annotation give the future engineer a clean baseline. The risk is "dead code rot": a few schema migrations later, the quarantined tables may no longer match what their repos expect to read, and the revival cost approaches Option A's deletion-then-rebuild cost anyway. Quarantine pays off only if the revival happens within ~6 months.
- This PRD is intentionally short on the Option C implementation detail because it is a **decision** PRD, not an **implementation** PRD. Once a path is chosen, the chosen path's PR (or set of PRDs for C) gets written separately.
- ADR-0004 recording the decision (whichever it is) lives in the same PR as the executed work.
