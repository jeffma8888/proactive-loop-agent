# proactive-loop-agent

> **A proactivity layer for AI agents.** Most agents wait for a human to hand them a goal. This one scans your working context, decides what's worth doing, gates it for safety, and executes it — fully offline, fully tested, fully auditable.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
[![CI](https://github.com/jeffma8888/proactive-loop-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jeffma8888/proactive-loop-agent/actions/workflows/ci.yml)
![Offline](https://img.shields.io/badge/runtime-offline--first-success)
![Typed](https://img.shields.io/badge/typing-PEP%20561-informational)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Most agentic systems are **reactive**: they sit idle until prompted, run the task, and stop. `proactive-loop-agent` inverts that. It is a reference implementation of a three-layer **proactivity stack** that turns raw working context into a *ranked slate of candidate goals*, gates each one through an **autonomy contract**, and dispatches only the approved goals into a resilient, sandboxed **plan → act → check** execution loop.

The whole system runs **fully offline and deterministically** by default — the LLM boundary is a single scripted seam, so the demo and all **1,800+ tests** run with no network and no API key. Point it at a live model (Anthropic / OpenAI / Bedrock / Ollama) with a single flag.

### What this project demonstrates

- **A 0→1 idea, not a prompt trick** — proactivity modeled as an explicit architectural layer (perceive → propose → gate → execute), with clear seams between deciding *what* to do and *how* to do it.
- **Safety by construction** — the autonomy gate is a hard rule engine: sensitive categories (finance, legal, health) *always* require human approval, no matter how high a goal scores. Autonomy comes from a sandbox, not from trust; the execution loop can only write inside a scratch directory through path-guarded tools.
- **Production-grade rigor on a portfolio codebase** — **1,800+ passing tests** (green in CI on Python 3.12 and 3.13), fully type-hinted (ships a PEP 561 `py.typed` marker), 15 context collectors, 14 CLI verbs, deterministic and offline end to end.
- **Auditability as a first-class feature** — a transparency arc of read-only, LLM-free inspector commands: see what the collectors *perceive* → what the scout *proposed* → *why* the gate ruled → exactly what a run *did*.

<!-- ============================================================================
     ▲ PORTFOLIO INTRO — human-owned. Automated contributors: do NOT rewrite or
     restructure anything ABOVE this marker. You MAY update the reference sections
     BELOW it (CLI table, config, providers) to document a shipped feature.
     NARROW CARVE-OUT: you MAY -- and must -- correct the NUMERIC COUNTS in the
     intro above (the collector count, the CLI-verb count, and the "N,N00+ tests"
     floor) when your change makes one stale. Numbers only; leave the prose alone.
     tests/test_readme_and_ci_contract.py fails the build if you skip it. ▼
     ============================================================================ -->

## The three layers

```
L2  SCOUT (proactivity)      collectors -> signals -> synthesizer (LLM) -> ranked slate
                             autonomy gate: AUTO_DISPATCH / NEEDS_APPROVAL / BLOCKED
        |  dispatch(goal)
L1  GOAL LOOP (execution)    iterate: PLAN (LLM) -> ACT (sandboxed tool) -> CHECK (LLM)
                             until done or budget exhausted
        |
L0  RESILIENCE               retry + exponential backoff + jitter on throttle/timeout
                             atomic JSON checkpoints -> resumable runs
```

- **L2 scout** turns raw context (recent files, git activity, uncommitted &
  unpushed working-tree changes, interrupted git operations (merge / rebase /
  cherry-pick / revert, detached HEAD), forgotten `git stash` entries,
  `TODO`/`FIXME` comments, notes (headings outside fenced code blocks),
  dependency manifests, untested source directories, leftover merge-conflict
  markers in committed files, large files past a size threshold,
  secret-shaped files (`.env`, private keys, credentials)) into a ranked list of
  candidate goals,
  then applies a policy
  gate. Sensitive categories (finance/legal, health/admin) *always* require
  human approval, no matter how high they score.
- **L1 goal loop** drives one approved goal through bounded plan/act/check
  iterations. The ACT phase can only touch a sandboxed artifacts directory,
  through a fixed set of path-guarded tools: write, append, read, relocate
  (`move_file`), and delete files, plus read-only discovery (list / search /
  find / stat / head / tail).
- **L0 resilience** wraps every model call in retry-with-backoff and checkpoints
  the run state after every step, so a throttle blip or a crash never loses more
  than the in-flight step. Each recovered retry is counted on the run and shown
  in the run summary and the `pla trace` header, so the self-healing is visible.

## Quickstart

```bash
uv sync        # install the locked dependency set (pydantic + pytest)
make demo      # scan the fixture workspace and auto-dispatch the top goal
make test      # run the full offline test suite
make cov       # run the suite with a coverage report (term-missing)
make typecheck # mypy-check the package (the "fully type-hinted" oracle; also in CI)
```

`make demo` runs:

```bash
uv run pla run \
  --workspace examples/fixture_workspace \
  --provider scripted \
  --scripted-responses examples/scripted_responses.json \
  --state-dir .pla_runs
```

It prints a ranked table with each goal's gate decision, writes the slate to
`.pla_runs/slate.json`, auto-dispatches the single top **AUTO_DISPATCH** goal,
and leaves its artifacts (`learning_plan.md`, `project_scaffold.md`) plus an
atomic checkpoint under `.pla_runs/run-<goal_id>/`. Approval-gated goals are
listed with a ready-to-paste `pla dispatch ... --yes` command but are never run
automatically.

## CLI

| Command   | What it does                                                              |
|-----------|---------------------------------------------------------------------------|
| `scan`    | Collect context, synthesize + gate a slate, print it (`--format table\|json\|markdown\|csv\|html`; `--top N` caps the printed rows, the written slate stays complete; `--collector NAME` repeatable, restricts which collectors feed synthesis), write slate JSON.|
| `dispatch`| Re-gate one goal from a saved slate and run it (`--yes` confirms approval).|
| `run`     | Scan, then auto-dispatch only the single top AUTO_DISPATCH goal.          |
| `resume`  | Load a checkpoint from a run dir and continue the loop.                   |
| `runs`    | List past dispatched runs under the state dir (`--status STATUS` narrows to runs of one status and composes with `--json`; `--json` for a JSON array).|
| `explain` | Audit gate decisions from a saved slate — score math, decision + reason, and provenance. `--goal-id ID` audits one goal (`--json` → one object); omit `--goal-id` to audit the whole slate in ranked order (`--json` → a JSON array). Read-only, LLM-free.|
| `trace`   | Render one run's PLAN/ACT/CHECK step transcript from its checkpoint (`--json` for a full array; read-only).|
| `signals` | Print the raw context signals the collectors perceive for a workspace (`--json`; `--kind K` filters; `--summary` prints a per-kind count rollup + total instead of the listing, composing with the filters; read-only, LLM-free).|
| `watch`   | Repeatedly re-scan a workspace on an interval and re-print the slate (`--interval S`; `--max-scans N`; live monitor, writes no slate file).|
| `diff`    | Compare two saved slates and classify goals as added/removed/changed/unchanged (`--old A.json --new B.json`; `--json` for a JSON object; matched by normalized title; read-only, LLM-free).|
| `policy`  | Print the standing autonomy contract: the four ordered gate rules, the auto-dispatch threshold, and every category tagged sensitive/auto-eligible (`--json` for a JSON object; read-only, LLM-free, no workspace).|
| `tools`   | Print the L1 sandbox tool surface: every registered tool, its access class (`read-only`/`create-update`/`move`/`delete`), and the sandbox read/write invariant (`--json` for a JSON object; read-only, LLM-free, no workspace).|
| `collectors`| Print the L2 perception surface: every registered context collector and a one-line description of what it perceives (`--json` for a JSON object; read-only, LLM-free, no workspace).|
| `providers`| Print the LLM provider backends: every accepted provider, its `offline`/`cloud` kind, and the pip package to install (`bedrock` ships in `boto3`) (`--json` for a JSON object of `{name, kind, package, description}`; read-only, LLM-free, no workspace).|

Together these verbs form a transparency arc across the pipeline —
`signals` (what the collectors *see*) → `scan` (what the scout *proposes*) →
`explain` (why the gate *ruled*) → `trace` (what a run *did*). `signals`,
`explain`, `trace`, `runs`, `diff`, `policy`, and `tools` are read-only and need no LLM call;
`scan` is the one synthesizing step — it calls the LLM and writes the slate.

`watch` turns that one-shot scan into the product's namesake proactive loop: it
re-runs the scan pipeline every `--interval` seconds (default 3600) and re-prints
the ranked, gated slate as your context changes, running until interrupted with
Ctrl-C unless `--max-scans N` bounds it. Both knobs are guarded at parse time
like `--top`: `--interval` must be a finite non-negative number (`>= 0`; `0` is legal so offline
runs need no real wait) and `--max-scans` must be a positive integer, so a bad
value fails fast with an exit-2 usage error before any scan runs. It is a live
monitor — unlike `scan` it writes no slate file and prints no `slate written:`
trailer. A single failed scan (an exhausted retry or a non-retryable model fault)
is logged to stderr as `scan <n> failed: …` and the watch rides on to the next
tick, so a transient outage never kills the long-lived loop.

`diff` is the comparative companion to `watch`: hand it two saved slates (`--old`/`--new`) and it classifies goals as added / removed / changed (the score moved past `1e-9` or the gate decision flipped) / unchanged, matched by normalized title (`title.strip().lower()`) rather than the random per-scan id — turning a stream of point-in-time slates into a change feed. It re-gates each side live, so a goal that crossed the autonomy threshold shows up in `changed`. `--json` emits one `{old, new, added, removed, changed, unchanged_count}` object. Like the other inspectors it builds no `LLMClient`, runs nothing, and writes no file.

`policy` sits at the *top* of that arc: it prints the standing autonomy contract itself — the four ordered gate rules (first match wins: a sensitive category always needs approval, then a not-appropriate goal is blocked, then a goal at/above the auto-dispatch threshold runs, else it needs approval), the resolved threshold, and every category tagged sensitive vs. auto-eligible — with **zero input**: no `--workspace`, no slate, no LLM call. It answers "how does this decide what to auto-run vs. gate for approval?" without first running a scan. It reflects env overrides through the same `_settings` seam every verb shares, so `PLA_AUTO_DISPATCH_MIN_SCORE=6 pla policy` shows the *effective* contract. `--json` emits one `{auto_dispatch_min_score, sensitive_categories, categories, rules}` object.

`tools` is the L1 action-surface window one layer below `policy`: where `policy` catalogs the autonomy *rules*, `tools` catalogs what a dispatched goal can actually *do* to the disk. It prints every registered sandbox tool with its access class (`read-only`/`create-update`/`move`/`delete`) and the standing sandbox invariant (writes are confined to `artifacts_dir`; `workspace_root` is read-only) — with the same **zero input** as `policy`: no `--workspace`, no slate, no LLM call. So a reviewer of this public repo can answer "what can a dispatched goal touch, and how dangerous is each door?" without running anything. `--json` emits one `{sandbox, tools[{name, access, description}]}` object whose tool-name set is drift-guarded to equal the live `ToolRegistry` so the catalog can never diverge from what actually dispatches. This completes the transparency arc across both layers: `policy` → `signals` → `tools` → `explain` → `trace`.

`collectors` is the L2-perception *front door* of that arc: it lists every registered context collector — the things the proactivity layer *looks at* — with a one-line description of what each perceives, with the same **zero input** as `policy`/`tools`: no `--workspace`, no slate, no LLM call. Where `signals` needs a `--workspace` and shows only the raw signals that fired *there*, `collectors` answers the prior, context-free question "what perceivers even exist?" against the static collector set — so a portfolio reader can see the whole perception surface with no repo checked out. `--json` emits one `{collectors[{name, description}]}` object whose name set is drift-guarded to equal the live collector registry (`all_collectors()`), the same anti-rot coupling `tools` uses against `ToolRegistry`. Read the arc front-to-back: `collectors` (what perceivers exist) → `signals` (raw output for a workspace) → `scan` (proposals) → `explain` (why this goal) → `trace` (what a run did).

Global flags: `--provider`, `--scripted-responses`, `--state-dir` (also settable
via `PLA_*` environment variables). Run `pla --version` to print the installed
version (sourced from `proactive_loop.__version__`).

Add `-v` (or `-vv`) after any subcommand to raise runtime log verbosity on
stderr: `-v` shows INFO, `-vv` shows DEBUG. This surfaces the L0 retry/backoff
self-healing as it happens (each recovered retry logs an `L0 retry N ...` line
from the executor) instead of only in the post-run summary. Logs go to stderr
only, so machine-readable output stays pipe-clean (`pla runs -v --json | jq`
still works). The default (no `-v`) is silent and attaches no handler.

`scan` and `run` validate `--workspace`: a missing or non-directory path fails
fast with `error: workspace not found: <path>` on stderr and exit code 2, rather
than silently producing an empty slate. A mistyped path is reported as the
problem instead of hiding behind an empty result.

`scan --format` picks the stdout rendering without changing the slate file it
writes (so `dispatch`/`explain`/`trace` behave identically no matter which format
printed it):

- `table` (default) — the human ranked table plus a `slate written: <path>`
  trailer. A bare `scan` is byte-identical to `scan --format table`.
- `json` — a single JSON object on stdout, `{"workspace_root": ..., "goals": [...]}`,
  goals in ranked order each carrying the live gate `decision`/`reason`, and **no**
  trailer, so `pla scan ... --format json | jq` sees one clean document.
- `markdown` — a paste-ready GitHub-flavored table
  (`| # | decision | score | category | title |`) plus the trailer — the
  most portfolio-friendly artifact: "here is what my agent proposed and how the
  autonomy gate ruled."
- `csv` — an RFC-4180 export (via the stdlib `csv` module) for spreadsheets /
  `pandas.read_csv` / `csvkit`: a header row `rank,decision,score,category,title`
  then one row per ranked goal, with **no** trailer (the whole stdout is one CSV
  document). RFC-4180 quoting preserves commas, quotes, and newlines inside a
  title, so a consumer recovers it exactly (unlike `markdown`, which collapses
  whitespace); an empty slate emits the header row only. Sort by score, filter to
  `needs_approval`, or pivot a slate by category in one `read_csv`.
- `html` — one self-contained, dependency-free HTML document (inline `<style>`
  only; no external stylesheet/font/script) for a stakeholder who is not at a
  shell: `pla scan --workspace W --format html > slate.html` opens directly in a
  browser or pastes into a wiki/PR. Same fixed 5-column table (`#`, `decision`,
  `score`, `category`, `title`), one row per ranked goal, every cell escaped via
  stdlib `html.escape` so a title's markup renders as text (never injects). Like
  `csv`/`json` it is a pure document (no trailer/note); like `table`/`markdown` an
  empty slate shows a single `(no candidate goals)` row.

An invalid `--format` value is rejected by argparse as a usage error (exit 2).

`scan --top N` caps the STDOUT rendering to the N highest-ranked goals (across
all five `--format` values), while the slate file it writes always stays the
**complete** record — stdout is a view, the file is the record, so
`dispatch`/`explain`/`diff`/`runs` still operate on every goal. `--top` slices
the existing ranked order (it never re-orders): `table`/`markdown` print a
`... showing top N of M` note after the rows only when the cap actually hides
goals (`N < M`), while `json` stays a pure single `{workspace_root, goals}` object
and `csv` stays a pure header-plus-rows CSV document — both with just a shortened
row set (no note, no trailer, no count key). A bare
`scan` — or `--top N` with `N ≥ M` — is byte-identical to the pre-flag output. A
non-positive or non-integer `--top` (`0`, `-1`, `abc`) is an argparse usage error
(exit 2), rejected before any collection runs or slate is written.

`scan --collector NAME` is the UPSTREAM twin of `--top`/`--format`: where those
shape the OUTPUT view, `--collector` restricts the perception INPUT — WHICH
collectors feed synthesis. It is repeatable
(`--collector git_state --collector todos`) and its accepted values are exactly
the live collector names (derived from the registry, so the allowlist can never
drift from it); an unknown name is an argparse usage error (exit 2), rejected
before any collection runs. Absent (the default) every collector runs, so a bare
`scan` is byte-identical to before. Use it to focus the scout ("only look at git
state, ignore TODOs and large files"), which shrinks the synthesis prompt and
narrows the proposed goals. `--collector` is also accepted by `signals` (the read-only perception inspector, where it restricts which collectors the raw-signals view inspects); `run`/`watch` do not accept it.

## Configuration (environment variables)

Every runtime knob is overridable from the environment with the `PLA_` prefix,
so the CLI, the test suite, and any embedding host can tune behavior without a
code change. Four settings also have a direct CLI flag (`--provider`,
`--scripted-responses`, `--state-dir`, and `--workspace`) and can be set either
way; the remaining ten are environment-only. **Precedence: an explicit CLI flag
(or `Settings.from_env(...)` override) always wins over the corresponding
environment variable, which in turn wins over the built-in default.** Every
default listed below is the single source of truth (the field default on
`Settings` / `RetryPolicy`), so `Settings.from_env()` with none of these set is
identical to a bare `Settings()`.

**Core**

| Variable | Flag equivalent | Default | Meaning |
|----------|-----------------|---------|---------|
| `PLA_PROVIDER` | `--provider` | `scripted` | LLM provider name; `scripted` is the offline default (a deterministic test double, no network and no API key). |
| `PLA_MODEL` | *(env-only)* | *(none)* | Model identifier handed to a live provider; unused by the scripted default. |
| `PLA_SCRIPTED_RESPONSES` | `--scripted-responses` | *(none)* | Path to the scripted-responses JSON that drives the offline `scripted` provider. |
| `PLA_WORKSPACE_ROOT` | `--workspace` | `.` | Workspace root the collectors scan for context signals. |
| `PLA_STATE_DIR` | `--state-dir` | `.pla_runs` | Directory where slates, run dirs, and atomic checkpoints are written. |

**Scout budget**

| Variable | Flag equivalent | Default | Meaning |
|----------|-----------------|---------|---------|
| `PLA_AUTO_DISPATCH_MIN_SCORE` | *(env-only)* | `4.0` | Gate threshold: a non-sensitive, appropriate goal scoring at or above this auto-dispatches; below it needs approval. |
| `PLA_SENSITIVE_CATEGORIES` | *(env-only)* | `health_admin,finance_legal` | Comma-separated `GoalCategory` values whose goals ALWAYS need human approval. REPLACES the default set (does not merge), so it can also narrow the gate. A blank or empty value keeps the default (the always-approve set can never be emptied via the environment). |
| `PLA_MAX_ITERATIONS` | *(env-only)* | `8` | Maximum PLAN/ACT/CHECK iterations for a single dispatched goal loop. |
| `PLA_MAX_LLM_CALLS` | *(env-only)* | `24` | Hard cap on total LLM calls per session, a backstop budget across the whole run. |

**L0 resilience (retry / backoff)**

The product's headline self-healing surface: every model call is wrapped in
retry-with-exponential-backoff, and all five knobs are tunable without editing
source (raise `PLA_RETRY_BASE_BACKOFF_SEC` substantially against a real
rate-limited API).

| Variable | Flag equivalent | Default | Meaning |
|----------|-----------------|---------|---------|
| `PLA_RETRY_MAX_ATTEMPTS` | *(env-only)* | `5` | Total attempts (including the first) before a throttled or timed-out call gives up. |
| `PLA_RETRY_BASE_BACKOFF_SEC` | *(env-only)* | `1.0` | Base delay in seconds for the first backoff. |
| `PLA_RETRY_BACKOFF_FACTOR` | *(env-only)* | `2.0` | Multiplier applied to the delay after each failed attempt (exponential growth). |
| `PLA_RETRY_MAX_BACKOFF_SEC` | *(env-only)* | `60.0` | Ceiling in seconds on any single backoff delay, so growth never runs away. |
| `PLA_RETRY_JITTER_FRAC` | *(env-only)* | `0.1` | Fractional random jitter (a fraction between 0 and 1) added to each delay to de-synchronize retries. |

For example, to make an unattended run more patient against a throttling API:

```bash
export PLA_RETRY_MAX_ATTEMPTS=8
export PLA_RETRY_BASE_BACKOFF_SEC=30
pla run --workspace .
```

## How the offline scripted provider works

Everything talks to models through one seam: `LLMClient.complete(system, prompt,
tag=...)`, where `tag` names the call site (`"synthesize"`, `"plan"`, `"check"`).
The default `scripted` provider is a `ScriptedLLMClient` loaded from a JSON file:

```json
{
  "responses": [
    {"tag": "synthesize", "text": "[ ...goal objects as JSON... ]"},
    {"tag": "plan",  "text": "{\"thought\": \"...\", \"action\": {\"tool\": \"write_file\", \"args\": {...}}}"},
    {"tag": "check", "text": "{\"done\": false, \"reason\": \"...\"}"}
  ]
}
```

Entries are consumed **in order**; a `complete(tag=X)` call takes the first
remaining entry whose tag is `X` (or the wildcard `""`). An entry may instead
carry `{"raise": "throttle"|"timeout"}` to exercise the L0 retry path. This
single seam is what makes the entire pipeline deterministic and testable end to
end without any network access. Swapping in a live provider (`anthropic`,
`openai`, `bedrock`, `ollama`, `groq`, `together`) is a one-flag change and lazily
imports only that SDK. The `ollama` provider runs the full plan->act->check loop against a
locally-hosted model with **no API key and no network egress** -- extending
offline-first from the scripted test double to real runtime execution.

## License

MIT -- see [LICENSE](LICENSE).
