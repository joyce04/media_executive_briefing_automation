# PRD 0007 — Harden `.claude/hooks/*.sh` against sibling-path subversion

## Problem Statement

An automated security review of commit `7dbf811` (`Add CLAUDE.md and Claude Code tooling`) flagged three hook scripts that ship with the repository:

- **`.claude/hooks/post_edit_pytest.sh`** — `HIGH`: arbitrary code execution via attacker-influenced `project_root` (Under-validated sink arg / Sibling-path control). The script walks upward from the edited file's directory looking for a `pyproject.toml`, then `cd`'s into that directory and runs `uv run pytest tests/unit/`. If an ancestor of the edited file contains a hostile `pyproject.toml` (e.g. one with a `[project]` build hook that runs arbitrary code at install time, or one whose `.venv` is a poisoned interpreter), the hook will execute against it.
- **`.claude/hooks/post_edit_ruff.sh`** — `HIGH`: same root cause; same upward walk; same `uv run`-against-an-attacker-controlled `pyproject.toml` exposure.
- **`.claude/hooks/pre_commit_secret_scan.sh`** — `MEDIUM`: validator differential / substring bypass. The gate `case "$cmd" in *"git commit"*) ;;` matches the literal substring `git commit` anywhere in the command. Bypassable by, for example, prefixing with `: "skip git commit gate"; <actual command>` or by using non-trivial git invocations (e.g. `git -c key=val commit`, `python -c 'subprocess.run(["git", "commit", ...])'`) that route around the case match.

The hooks are useful — they enforce ruff formatting after every Python edit, run unit tests after every edit, and block commits with secret-shaped strings. The issue is **scope**: they trust their inputs more than they should. In a normal developer workspace this trust is fine; in any environment where the agent's edits could land in a directory whose ancestor has been tampered with (CI-managed worktrees, multi-tenant dev machines, agents operating on cloned repos from untrusted sources), the trust is exploitable.

## Solution

Constrain the project-root resolution to a known-safe set, and replace the substring-based secret-scan gate with a robust command parse.

Specifically:

- `post_edit_pytest.sh` and `post_edit_ruff.sh` accept `pyproject.toml` only when its directory is either `$CLAUDE_PROJECT_DIR` itself or a directory that was registered at session start. Refuse to traverse past `$CLAUDE_PROJECT_DIR` upward.
- `pre_commit_secret_scan.sh` runs the secret scan **unconditionally whenever the staged diff is non-empty**. The substring gate goes away.

These changes preserve the hooks' intended behavior for normal developer use (single-project workspace, `$CLAUDE_PROJECT_DIR` matches the project root) and tighten the trust boundary so attacker-influenced inputs can no longer redirect the hook to a different project tree or skip the secret check.

## User Stories

1. As a developer, I want `post_edit_pytest.sh` to refuse to run `uv run pytest` against any `pyproject.toml` outside `$CLAUDE_PROJECT_DIR`, so that a malicious ancestor directory cannot subvert the agent's test loop.
2. As a developer, I want `post_edit_ruff.sh` to refuse to run `uv run ruff` against any `pyproject.toml` outside `$CLAUDE_PROJECT_DIR`, so that a malicious ancestor directory cannot subvert the agent's lint loop.
3. As a developer, I want both edit hooks to continue working on every Python file inside `$CLAUDE_PROJECT_DIR`, regardless of nesting depth, so that the legitimate use case is unaffected.
4. As a developer, I want both edit hooks to exit cleanly (no error) when the edited file is outside `$CLAUDE_PROJECT_DIR`, so that an Edit on (say) a stray scratch file in `/tmp/` is silently ignored rather than failing loudly.
5. As a developer, I want `pre_commit_secret_scan.sh` to run the secret scan whenever `git diff --cached` is non-empty and the PreToolUse Bash command appears to invoke `git`, so that bypass via creative quoting / wrapping / Python subprocess no longer skips the scan.
6. As a developer, I want the secret-scan gate to be "is there a non-empty staged diff" rather than "does the command literally contain `git commit`," so that operationally the gate runs slightly more often (negligible cost) and is robust to syntactic variation.
7. As a developer, I want the secret-scan patterns kept as-is (`sk-or-v1-*`, `sk-ant-*`, `SMTP_PASSWORD=*`, `OPENROUTER_API_KEY=sk-*`, `ANTHROPIC_API_KEY=sk-*`), so that the false-positive profile does not change.
8. As a developer, I want the hooks to fail loudly and informatively (`>&2` with a clear "refused because X" message) when they refuse to run, so that I can diagnose why a hook is no-op'ing without digging into the script.
9. As a developer, I want a self-test fixture (e.g. `.claude/hooks/_tests/`) with `bats` or plain shell assertions that verifies the constrained behavior against representative edge cases, so that future hook edits do not silently reintroduce the vulnerabilities.
10. As a maintainer, I want the hardening applied in a single PR with a clear commit message referencing the security review IDs, so that the audit trail is traceable.
11. As a developer, I want `realpath` used to canonicalize paths before comparison (handles symlinks, `..` segments, trailing slashes), so that `..`-based escape attempts (`$CLAUDE_PROJECT_DIR/../sibling/pyproject.toml`) are blocked.
12. As a developer, I want the hardening to NOT add a new dependency (`realpath` and `jq` are already required; no new runtime), so that hooks remain trivially reviewable shell scripts.
13. As a developer, I want a follow-up PR (or commit on the same PR) that adds `realpath` and `jq` to a "required tools" check in each hook with a clear error if missing, so that the hooks fail loudly on a misconfigured machine instead of silently degrading.
14. As a contributor reading the hardened scripts, I want a short comment in each hook explaining the constraint and citing the security review IDs, so that the rationale is visible at the point of code.
15. As a developer, I want the substring `git commit` gate replaced with a more permissive but more reliable trigger: run on any PreToolUse Bash whose command contains the word `git` as a whole token, then gate the actual scan on `git diff --cached --name-only | head -1 | wc -l > 0` (non-empty staged diff). Bypass via subprocess (`python -c '...'`) is still possible but documented as an accepted residual risk; the alternative (a Python-level Bash-tool wrapper) is out of scope.

## Implementation Decisions

**`post_edit_pytest.sh` and `post_edit_ruff.sh`** — replace the upward walk:

```bash
# OLD (vulnerable):
dir="$(dirname "$file_path")"
project_root=""
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -f "$dir/pyproject.toml" ]; then
    project_root="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done

# NEW (hardened):
: "${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR not set; refusing to run}"
project_root="$(realpath "$CLAUDE_PROJECT_DIR")"
file_real="$(realpath "$file_path" 2>/dev/null || echo "")"

# Refuse if file_path is outside CLAUDE_PROJECT_DIR
case "$file_real" in
  "$project_root"|"$project_root"/*) ;;
  *) exit 0 ;;  # Silent ignore for out-of-tree edits
esac

# Refuse if CLAUDE_PROJECT_DIR doesn't itself have a pyproject.toml
[ ! -f "$project_root/pyproject.toml" ] && exit 0
```

Effect: `project_root` is always exactly `$CLAUDE_PROJECT_DIR`. No traversal. No discovery of ancestor `pyproject.toml`. The narrowing assumes one project per `$CLAUDE_PROJECT_DIR`, which is true for this repo and for every reasonable Claude Code session.

**`pre_commit_secret_scan.sh`** — drop the substring case; run scan whenever a staged diff exists:

```bash
# OLD (vulnerable):
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

# NEW (hardened):
# Trigger on any Bash command; the actual gate is "is there a staged diff to scan?"
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"
if [ -z "$(git diff --cached --name-only 2>/dev/null)" ]; then
  exit 0  # No staged diff -> nothing to scan
fi
# (rest of the secret-pattern check unchanged)
```

Effect: every Bash invocation triggers the scan **if** there's something to scan. The performance cost is one `git diff --cached --name-only` call per Bash tool use — negligible. Bypass via the substring approach no longer works; bypass via `python -c '...'` is still possible (subprocess routing around the hook) but is a known limitation of any PreToolUse-based defense and is documented in the script's header comment.

**New file: `.claude/hooks/_tests/test_hooks.sh`** (or `.bats` if `bats` is acceptable as a dev dep).

Each test exercises one hook with a constructed payload (JSON via stdin, mimicking what Claude Code sends) and asserts:

- Edit-hook tests:
  - Edit on a file inside `$CLAUDE_PROJECT_DIR` → runs the underlying command.
  - Edit on a file outside `$CLAUDE_PROJECT_DIR` (e.g. `/tmp/foo.py`) → exits 0 silently.
  - `$CLAUDE_PROJECT_DIR` set to a directory without `pyproject.toml` → exits 0 silently.
  - `$CLAUDE_PROJECT_DIR` unset → exits non-zero with a clear error.
  - Edit on a path whose `realpath` resolves outside `$CLAUDE_PROJECT_DIR` (symlink escape) → exits 0 silently.
- Secret-scan-hook tests:
  - Bash command `git commit -m "msg"` with no staged diff → exits 0.
  - Bash command `git commit -m "msg"` with a staged diff containing `sk-ant-xxxxxxxxxxxxxxxx` → exits 2.
  - Bash command `: "skip git commit"; echo hi` with a secret-laden staged diff → STILL exits 2 (no bypass).
  - Bash command `python -c 'import subprocess; subprocess.run(["git","commit","-m","x"])'` with a secret-laden staged diff → documented as residual risk (test asserts exit 0 today; comment notes the limitation).

Tests run via a `.claude/hooks/_tests/run.sh` driver invoked manually or in CI.

**Comment headers on hardened scripts.** Each hook gets a 3-4 line top-of-file comment naming the constraint and the security-review reference (`see PRD 0007 / commit <sha>`).

**No new runtime dependencies.** `realpath` is present on macOS (`coreutils`-installed via Homebrew) and standard on Linux; `jq` is already required by the existing hooks. Both can be checked at the top of each script with a `command -v ... >/dev/null || { echo ...; exit 1; }` guard.

**What does NOT change.**

- The set of files the hooks operate on (`*.py` only; specific directory allow-list in `post_edit_pytest.sh`).
- The secret-pattern regex.
- The hooks' exit-code contract (0 = success, 1 = test warning, 2 = blocked commit).
- The `.claude/settings.json` registration of the hooks.

## Testing Decisions

A good test of these shell hooks asserts the **observable exit code and stderr** for a given input payload. The mechanism is: pipe a constructed JSON payload to the hook, set the env (`CLAUDE_PROJECT_DIR`, `pwd`), assert exit code and grep stderr for the expected message. No mocking; the hooks are tiny and pure functions of their inputs.

**Modules to test:**

- `post_edit_pytest.sh` — 5 cases listed above.
- `post_edit_ruff.sh` — same 5 cases (the hook differs in what it runs, not in how it resolves project_root).
- `pre_commit_secret_scan.sh` — 4 cases listed above, plus a regression test that the existing secret patterns still match.

**Prior art:** none in this repo; this is the first hook test infrastructure. The convention can be borrowed from the upstream Claude Code plugin marketplace's hook test patterns if those are documented; otherwise `bats-core` is the standard.

## Out of Scope

- Defending against `python -c 'import subprocess; subprocess.run(["git","commit", ...])'` bypass of the secret-scan hook. Any PreToolUse-based gate runs *before* the tool, and the agent can route around it via subprocess. The only mechanism that would close this is a server-side / pre-receive git hook, which is outside the Claude Code hook surface.
- Defending against the agent rewriting the hook files themselves to disable the gate. The agent can do this; protecting against it requires repo-level controls (CODEOWNERS, branch protection, required reviews on `.claude/`) that are configured outside this repo's tree.
- Restructuring the hook surface (e.g. moving from per-file shell scripts to a single Python module). Larger refactor; defer until there are 5+ hooks.
- Re-doing the secret-pattern set. The current patterns are conservative; broadening them (e.g. AWS keys, GitHub tokens) is a separate decision.
- Hardening hook scripts that exist in other repos. This PRD is scoped to the three files in this repo's `.claude/hooks/`.

## Further Notes

- The security review (commit `7dbf811`, three findings as recorded in the conversation log) is the authoritative reference for this PRD. The review IDs (`UNDER_VALIDATED_SINK_ARG / Sibling-path control` for the two edit hooks, `Validator differential` for the secret scan) should be cited verbatim in the hardening PR's commit message so future audits can match.
- Sibling-path control sounds theoretical but is a real attack pattern. The mechanism: an attacker convinces the agent to edit a file under a directory whose parent contains a hostile `pyproject.toml`. With `uv run`, the venv resolution runs the project's build hooks; with `[tool.poetry.scripts]` or `[project.entry-points]` shenanigans, arbitrary code executes. The constraint to `$CLAUDE_PROJECT_DIR` blocks this entire class.
- This PRD is independent of the others and is the smallest of the seven by implementation surface (~30 LOC across three files, plus the test fixtures). Ship in a single PR.
- A future PRD might add a "session-start snapshot" mechanism: at session start, the hook reads a list of known-good project roots from `.claude/settings.json` and treats only those as valid. This generalizes beyond `$CLAUDE_PROJECT_DIR` for power users with multiple project subdirectories. Not needed today.
