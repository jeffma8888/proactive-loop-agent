# proactive-loop-agent

> **A proactivity layer for AI agents.** Most agents wait for a human to hand them a goal. This one scans your working context, decides what's worth doing, gates it for safety, and executes it — fully offline, fully tested, fully auditable.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
[![CI](https://github.com/jeffma8888/proactive-loop-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jeffma8888/proactive-loop-agent/actions/workflows/ci.yml)
![Offline](https://img.shields.io/badge/runtime-offline--first-success)
![Typed](https://img.shields.io/badge/typing-PEP%20561-informational)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Most agentic systems are **reactive**: they sit idle until prompted, run the task, and stop. `proactive-loop-agent` inverts that. It is a reference implementation of a three-layer **proactivity stack** that turns raw working context into a *ranked slate of candidate goals*, gates each one through an **autonomy contract**, and dispatches only the approved goals into a resilient, sandboxed **plan → act → check** execution loop.

The whole system runs **fully offline and deterministically** by default — the LLM boundary is a single scripted seam, so the demo and all **4,300+ tests** run with no network and no API key. Point it at a live model (Anthropic / OpenAI / Bedrock / Ollama) with a single flag.

### What this project demonstrates

- **A 0→1 idea, not a prompt trick** — proactivity modeled as an explicit architectural layer (perceive → propose → gate → execute), with clear seams between deciding *what* to do and *how* to do it.
- **Safety by construction** — the autonomy gate is a hard rule engine: sensitive categories (finance, legal, health) *always* require human approval, no matter how high a goal scores. Autonomy comes from a sandbox, not from trust; the execution loop can only write inside a scratch directory through path-guarded tools.
- **Production-grade rigor on a portfolio codebase** — **4,300+ passing tests** (green in CI on Python 3.12 and 3.13), fully type-hinted (ships a PEP 561 `py.typed` marker), 17 context collectors, 16 CLI verbs, deterministic and offline end to end.
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

**Layer: harness plus policy, with a decision gate.** A proactivity harness that decides what is worth doing and gates it before acting; nothing here depends on model cooperation once launched.

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

- **L2 scout** turns raw context into a ranked list of candidate goals, then
  applies a policy gate. Every perceiver it draws that context from is named,
  with the signal `kind` it emits, in
  [L2 perception surface](#l2-perception-surface) below. Sensitive categories
  (finance/legal, health/admin) *always* require human approval, no matter how
  high they score.
- **L1 goal loop** drives one approved goal through bounded plan/act/check
  iterations. The ACT phase can only touch a sandboxed artifacts directory,
  and only through a closed allowlist of 14 path-guarded tools — creating,
  extending and in-place editing of files, one relocate, one delete, and
  read-only reading / ranged reading / diffing / discovery. Every one of them
  is named with its access class in
  [ACT sandbox tool allowlist](#act-sandbox-tool-allowlist) below.
- **L0 resilience** wraps every model call in retry-with-backoff and checkpoints
  the run state after every step, so a throttle blip or a crash never loses more
  than the in-flight step. Each recovered retry is counted on the run and shown
  in the run summary and the `pla trace` header, so the self-healing is visible.

### L2 perception surface

The scout's whole perception surface is this closed set of collectors: a scan
runs them over the workspace and each one emits signals of exactly one `kind`.
That `kind` is not always the collector's name, and it -- not the name -- is the
token `pla signals --kind` and `--fail-on-kind` accept, so the second column is
the vocabulary for filtering and gating on what was perceived. `pla collectors`
prints this same surface at runtime (`--json` for the machine-readable form), and
a drift guard binds every row below to the collector registry by name AND by
kind, so the table cannot fall behind the code.

| collector | kind | perceives |
|-----------|------|-----------|
| `broken_link` | `broken_link` | Markdown links whose relative target is missing from the workspace. |
| `ci_config` | `ci_config` | Continuous-integration posture: a recognized CI config, or source code with none. |
| `dependencies` | `dependency` | Dependency manifests declared in the workspace (pyproject, package.json, etc.). |
| `git_activity` | `git_commit` | Recent commits across the workspace's git repositories. |
| `git_stash` | `git_stash` | Forgotten entries sitting in the git stash reflog. |
| `git_state` | `git_state` | Interrupted or dangling git operations read from .git markers. |
| `large_file` | `large_file` | Files at or above a byte-size threshold worth a second look. |
| `license` | `license` | Open-source hygiene: a code-carrying workspace with no recognized root LICENSE file. |
| `lockfile_drift` | `lockfile_drift` | Manifest/lockfile drift: a manifest whose lockfile is missing or older than it. |
| `merge_conflict` | `merge_conflict` | Files still carrying unresolved conflict markers. |
| `notes` | `note` | Heading-and-paragraph blocks found in notes directories. |
| `recent_files` | `recent_file` | Files modified most recently under the workspace. |
| `secret_file` | `secret_file` | Secret-shaped files matched by basename (.env, credentials, keys). |
| `syntax_error` | `syntax_error` | Python files that fail to parse (stdlib compile, parse-only). |
| `test_posture` | `test_posture` | Top-level project directories that contain source files. |
| `todos` | `todo` | TODO/FIXME/XXX comments and unchecked Markdown checkboxes. |
| `working_tree` | `working_tree` | Present-state git signals: dirty paths and unpushed commits. |

One scan pays for each piece of filesystem work ONCE, not once per collector. The collectors above overlap heavily -- most of them walk the same workspace root, and the content collectors read the same files -- so the scan loop runs inside two scan-scoped providers: `collectors/text_source.py` shares one read+decode per file, and `collectors/dir_source.py` shares one pruned `os.walk` per directory root. Both caches live for exactly one scan and are emptied on entry and exit, so a long-lived `pla watch` process can never be served a stale listing or a stale file body from a previous tick, and both degrade to doing the work directly when no scope is active, so a collector used as a library still works on its own. The shared walk is served in `os.walk`'s own `(dirpath, dirnames, filenames)` shape with the noise/hidden-directory prune already applied and the order sorted, so what a collector perceives does not depend on platform enumeration order. `dependencies` and `lockfile_drift` are the collectors served by the shared walk today; the remaining walkers still traverse for themselves and are being converted incrementally.

### ACT sandbox tool allowlist

Every ACT step resolves the model's requested tool against this closed
allowlist before any path is touched: an unlisted name is refused outright,
and each listed tool re-checks that its path stays inside the sandbox — writes
are confined to the run's artifacts directory and the workspace is read-only.
`pla tools` prints this same surface at runtime (`--json` for the
machine-readable form), and a drift guard binds every row below to the CLI's
tool catalog by name AND by access class, so the table cannot fall behind the
code.

| tool | access | effect |
|------|--------|--------|
| `append_file` | `create-update` | Extend a file, creating it if it does not exist yet. |
| `diff_files` | `read-only` | Compare two files and return a bounded unified diff. |
| `find_files` | `read-only` | Find files by basename glob under a sandbox directory. |
| `head_file` | `read-only` | Return the first N lines of a file (a bounded top-of-file peek). |
| `list_files` | `read-only` | List the entries of one directory in the sandbox. |
| `move_file` | `move` | Atomically rename or relocate one file inside the sandbox. |
| `read_file` | `read-only` | Return the whole contents of one file. |
| `read_lines` | `read-only` | Return an inclusive 1-based line range (a bounded interior window). |
| `remove_file` | `delete` | Remove one file from the sandbox. |
| `replace_in_file` | `create-update` | Edit a file in place: substitute every literal occurrence of a substring in a file that must already exist. |
| `search_files` | `read-only` | Grep file contents for a substring across a sandbox directory. |
| `stat_file` | `read-only` | Describe one path in a line: type, byte size, line count, extension. |
| `tail_file` | `read-only` | Return the last N lines of a file (a bounded bottom-of-file peek). |
| `write_file` | `create-update` | Create a file or overwrite an existing one whole. |

## Quickstart

```bash
uv sync --locked # install the exact locked dependency set (pydantic + pytest, pytest-cov, pytest-xdist, mypy)
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

### Try it on your own repo

Everything above points at this repo's bundled fixture. To point the
*perception* half of the stack at your own checkout you need **no provider, no
API key, no config file and no network** -- eleven of the sixteen verbs never
construct an LLM client at all. **Seven** of those eleven -- `collectors`,
`config`, `policy`, `providers`, `runs`, `signals` and `tools` -- need nothing
but the checkout itself. The other **four** are inspectors of a run that
already happened, so they are not standalone. `diff` and `explain` read a slate
file, `trace` reads a run directory's checkpoint, and `verify` reads a slate
against the snapshot a prior `scan --snapshot` wrote, so each names the missing
artifact and exits `2` until you have produced one (`make demo` is enough).
The seven standalone verbs need only your checkout:

```bash
# every context signal the collectors perceive in this checkout
pla signals --workspace .

# the perceivers and the gate itself, context-free (no --workspace needed)
pla collectors
pla policy
```

Goal *synthesis* is the step that calls a model, so `scan`, `run`,
`dispatch`, `resume` and `watch` each require a provider -- either a live one
(`--provider anthropic`, `openai`, `bedrock`, `ollama`, `groq`, `together`) or
the offline `scripted` default together with a script for it to read
(`--scripted-responses PATH`, as `make demo` does above). Asked to synthesize
with neither, the CLI stops immediately with `error: provider is 'scripted' but
no scripted_responses_path was configured` instead of pretending to think.
Start with `signals` to see what the agent would be reasoning about; add a
provider when you want it to propose.

## CLI

| Command   | What it does                                                              |
|-----------|---------------------------------------------------------------------------|
| `scan`    | Collect context, synthesize + gate a slate, print it (`--format table\|json\|markdown\|csv\|html`; `--top N` caps the printed rows, the written slate stays complete; `--collector NAME` repeatable, restricts which collectors feed synthesis), write slate JSON to `--out PATH` (default `<state_dir>/slate.json`), `--snapshot FILE` also persists the collected snapshot as a `signals --json`-shaped document (usable as a `signals --baseline`).|
| `dispatch`| Re-gate one goal from a saved slate and run it (`--slate FILE` + `--goal-id ID` required; `--yes` confirms approval; `--json` publishes the finished run as one `{goal_id, run_id, status, run_dir, artifacts, iterations_used, llm_calls_used, retries, parse_errors}` object on stdout -- the same document `run --json` nests under `dispatched` -- and moves the human summary to stderr, leaving stdout EMPTY on a refusal).|
| `run`     | Scan, then auto-dispatch only the single top AUTO_DISPATCH goal (`--dry-run` previews the goal it WOULD dispatch, still writing the slate, then stops before any run dir or loop iteration; `--json` makes the whole invocation scriptable -- stdout becomes one `{workspace_root, slate_path, goal_count, needs_approval, top_goal, dispatched}` object and the human progress moves to stderr; `--snapshot FILE` also persists the snapshot this run perceived, the same `signals --json`-shaped document `scan --snapshot` writes, so the slate `run` produces -- the one `make demo` and CI publish -- is directly checkable with `pla verify --slate ... --snapshot FILE` instead of being a claim with no evidence).|
| `resume`  | Load a checkpoint from a run dir and continue the loop (`--run-dir DIR` required: a `run-<id>` dir as listed by `runs`; `--json` publishes the resumed run as the SAME `{goal_id, run_id, status, run_dir, artifacts, iterations_used, llm_calls_used, retries, parse_errors}` object `dispatch --json` does -- one document on stdout, human summary on stderr, stdout EMPTY when there is no checkpoint to resume).|
| `runs`    | List past dispatched runs under the state dir (`--status STATUS` narrows to runs of one status and composes with `--json`; `--json` for a JSON array). `--prune` turns the same selection into the product's retention operation: it reports the run dirs it would delete and **deletes nothing unless `--yes` is also given** (dry run is the default, exit 0 either way), selects with the *listing's own* `--status` filter so "what will be deleted" is answerable by a read-only command, is contained to direct `run-*` children of the state dir (a nested `run-*`, a plain file named `run-*`, and any other child are never touched), refuses a `run-*` **symlink** on one `refused:` stderr line rather than following it, and under `--json` emits one `{dry_run, status, selected, refused, deleted}` object.|
| `explain` | Audit gate decisions from a saved slate (`--slate FILE` required) — score math, decision + reason, and provenance. `--goal-id ID` audits one goal (`--json` → one object); omit `--goal-id` to audit the whole slate in ranked order (`--json` → a JSON array). Read-only, LLM-free.|
| `verify`  | Resolve every goal's cited `sources` against a saved scan snapshot and report the ones it cannot find (`--slate FILE` + `--snapshot FILE` both required -- the snapshot is the document `scan --snapshot FILE` wrote for that slate, so the comparison is against what the collectors actually perceived, never a fresh re-scan). A source resolves when it equals a recorded signal `path` or `summary`, exactly or once a trailing `:LINE` anchor is stripped from either side; each goal's block annotates every cited source `resolved:` or `UNRESOLVED:`, and the trailer counts goals, sources and unresolved. Deliberately **reporting-only by default: exit 0 even with unresolved sources**, because several collectors are mtime-driven so an unresolved source can mean staleness rather than fabrication; `--fail-on-unresolved` opts in to the shipped gate code **5** when the count is non-zero, for a caller that knows its pair is same-run (`run --snapshot` writes exactly that) -- stdout, the `--json` payload and every un-flagged invocation stay byte-identical, and the gate names itself on one `gate: fail-on-unresolved tripped -- unresolved=N` line on stderr. `--json` for one `{slate, snapshot, goals, source_count, unresolved_count}` object; read-only, LLM-free.|
| `trace`   | Render one run's PLAN/ACT/CHECK step transcript from its checkpoint (`--run-dir DIR` required; `--json` for a full array; read-only).|
| `signals` | Print the raw context signals the collectors perceive for a workspace (`--json`; `--kind K` filters by kind, validated against the live signal-kind registry so an unknown kind is a usage error (exit 2) at parse time rather than a silently empty listing — run `pla signals --help` for the full list of accepted kinds; `--kind` narrows **collection**, not just the view: only the collector that emits `K` runs, so a kind-filtered inspection costs what that one collector costs and `--timings` shows a single row; `--min-weight W` filters by relevance weight (>= W, inclusive); `--summary` prints a per-kind count rollup + total instead of the listing, composing with the filters; `--timings` additionally prints a per-collector cost table to **stderr** (collector name, elapsed ms, signal count, plus a `TOTAL` row, in registry order) so you can see which collector a scan spends its time in — opt-in, and stdout is byte-identical with or without it, so it is safe to add to a piped or `--json` invocation; `--fail-on-kind K` turns the inspector into a **gate** — repeatable, OR semantics, and exits **5** instead of `0` when the reported signals include at least one signal of kind `K`, naming the matched kinds and counts on one line on **stderr** while stdout stays byte-identical, so a pre-commit hook or CI step can branch on what the collectors found; it gates on what the view *reports*, so narrowing that hides the finding (`--min-weight` above its weight) exits `0`, and pairing `--kind K` with a different `--fail-on-kind V` is a usage error (exit 2) because that gate could never fire; arming it also makes the verb **fail closed** on a dead detector — if a collector that owns a gated kind crashes mid-scan (fail-open degrades it to no signals), the exit is **1** with one `error: ` line naming that collector and kind, never a green `0` over signals it never got to see; `--exclude-path GLOB` is the **location-aware escape hatch** for that gate and for the listing — repeatable with OR semantics, it hides signals whose path matches a case-insensitive glob, so one vendored, generated or fixture tree can be dropped without re-rooting `--workspace` (which would also throw away every repo-level, path-less signal). Matching is anchored at the start of the path and is tried against the whole path **and against every ancestor directory** of it, so the plainest spelling is a subtree exclusion: `vendor` hides `vendor/lib.js`, `vendor/a/b.js` and the bare `vendor` signal itself. `*` crosses `/`, so `sub/*` hides that subtree too but keeps the bare `sub` signal (a top-level path has no ancestors), and neither spelling reaches a same-named directory nested elsewhere, so `top/sub/b.py` survives both and an any-depth exclusion still needs a leading `*` (`'*node_modules'`); a trailing `:LINE` suffix does not defeat it, so `*.md` still hides a TODO reported at `notes.md:12`; a signal with **no** path is never excluded, not even by `*`; and because it is a downstream display filter it narrows every surface and the `--fail-on-kind` gate identically while leaving `--timings` untouched (an empty pattern is a usage error, exit 2); `--baseline FILE` is the **instance-aware ratchet** that makes the gate usable on a repo that already has findings — point it at a document you saved earlier with `pla signals --json` and every signal recorded there is hidden, so the listing and the gate report only what is **new** since that snapshot (record today's 30 TODOs once, then fail on the 31st). A signal's identity is the six published keys (`source`, `kind`, `summary`, `detail`, `path`, `weight`), extra keys are ignored and differing in any one of them makes it a different signal; suppression is set-based, so one entry hides every live signal matching it. Like `--exclude-path` it is a downstream display filter, so it narrows every surface *and* the `--fail-on-kind` gate identically while leaving `--timings` untouched, and it composes as a logical AND with all the filters above — the two are complements, not substitutes (one suppresses by **location**, the other by **instance**). Staleness fails toward *reporting*: an entry that no longer matches is noise, never a missed finding. An empty `signals` array is valid and hides nothing, while a missing or malformed baseline (not JSON, not an object, no `signals` array — what a `--summary --json` document looks like — or an entry missing one of the six keys) is a usage error (exit 2) reported before anything is scanned. `signals` never writes the file: you produce it yourself, so the verb stays read-only; `--fail-over N` is the **count budget** and the third ratchet -- the only one with nothing to keep fresh: it exits **5** when the number of reported signals is *strictly greater* than the non-negative integer `N`, so a count equal to `N` exits `0` and only `N` + 1 fails, and it reports the overrun on one `gate: fail-over tripped -- count=<count> budget=<N>` line on **stderr** while stdout stays byte-identical. It is the flag for a budget like *the TODO count must not exceed 30*, with no snapshot for anybody to refresh, and `--fail-over 0` is a strict mode that fails on any reported signal at all. Like the two filters above it counts what the view *reports*, so it composes as a logical AND with every one of them and a narrowing that hides signals lowers the count; a negative or non-integer budget is a usage error (exit 2) reported before anything is scanned. Unlike `--fail-on-kind`, pairing it with `--kind K` is **not** a usage error -- an unreachable *kind* gate is statically provable, an unreachable *count* budget is not -- and when both gates are armed and both would trip, exactly one line prints and it is the `--fail-on-kind` one, because it names which kind; read-only, LLM-free).|
| `watch`   | Repeatedly re-scan a workspace on an interval and re-print the slate (`--interval S`; `--max-scans N`; a live monitor that writes no slate file unless `--out-dir DIR` opts in, persisting each tick as `DIR/slate-<NNN>.json` so the stream feeds `diff`).|
| `diff`    | Compare two saved slates and classify goals as added/removed/changed/unchanged (`--old A.json --new B.json`, or `--dir DIR` to diff the two newest `slate-<NNN>.json` ticks in a `watch --out-dir` stream directory — mutually exclusive with `--old`/`--new`; `--json` for a JSON object; matched by normalized title; read-only, LLM-free).|
| `policy`  | Print the standing autonomy contract: the four ordered gate rules, the auto-dispatch threshold, and every category tagged sensitive/auto-eligible (`--json` for a JSON object; read-only, LLM-free, no workspace).|
| `tools`   | Print the L1 sandbox tool surface: every registered tool, its access class (`read-only`/`create-update`/`move`/`delete`), and the sandbox read/write invariant (`--json` for a JSON object; read-only, LLM-free, no workspace).|
| `collectors`| Print the L2 perception surface: every registered context collector, the signal `kind` it emits and a one-line description of what it perceives (`--json` for a JSON object; `--kind K` is the reverse lookup — prints the single collector emitting kind `K`, validated against the same live signal-kind registry `signals --kind` uses so an unknown kind is a usage error (exit 2) at parse time; read-only, LLM-free, no workspace).|
| `providers`| Print the LLM provider backends: every accepted provider, its `offline`/`cloud` kind, and the pip package to install (`bedrock` ships in `boto3`) (`--json` for a JSON object of `{name, kind, package, description}`; read-only, LLM-free, no workspace).|
| `config`  | Print the fully-resolved effective `Settings` after `PLA_*` env vars and CLI-global flags are applied (`--json` for one JSON object; read-only, LLM-free, no workspace).|

Together these verbs form a transparency arc across the pipeline —
`signals` (what the collectors *see*) → `scan` (what the scout *proposes*) →
`explain` (why the gate *ruled*) → `trace` (what a run *did*). `signals`,
`explain`, `trace`, `runs`, `diff`, `policy`, and `tools` need no LLM call, and all of them are
read-only with exactly one opted-in exception: `runs --prune --yes` (and only that combination) deletes
the run dirs it lists;
`scan` is the one synthesizing step — it calls the LLM and writes the slate.

Every signal whose location is resolved against the scanned workspace publishes
its `path` in **one namespace**, whatever you pass for `--workspace`: the POSIX
path *relative to the scanned workspace*, with the workspace directory itself
spelled `.` and any trailing `:LINE` suffix preserved
(`src/proactive_loop/cli.py:617`). A signal with no location keeps `path: null`,
and a path that is not under the workspace at all is published unchanged rather
than as a `../` escape. Each collector still builds whatever is natural for it —
an absolute path, for an absolute root — and the single `_collect` seam re-spells
it, which is what makes the two location-aware filters portable: an
`--exclude-path` glob narrows those kinds the same way, and a `--baseline`
document recorded on your laptop still suppresses those findings in CI instead of
reporting them all again because the checkout lives at a different absolute path.

Two exemptions, both deliberate. `workspace_root` echoes the workspace exactly as
you typed it, because its job is to say what was scanned. And `working_tree`
takes its paths from git's porcelain status output, which reports them relative
to the **repository root** rather than to the scanned directory: the same
namespace when you scan a whole repo (the default), but not when you scan a
sub-directory of one, where a `working_tree` path can still carry the
sub-directory prefix and so stays invocation-dependent. Roadmap row #158 tracks
re-rooting the git kinds; until then prefer a whole-repo workspace when you rely
on `--exclude-path` or `--baseline` for that one kind.

`watch` turns that one-shot scan into the product's namesake proactive loop: it
re-runs the scan pipeline every `--interval` seconds (default 3600) and re-prints
the ranked, gated slate as your context changes, running until interrupted with
Ctrl-C unless `--max-scans N` bounds it. Both knobs are guarded at parse time
like `--top`: `--interval` must be a finite non-negative number (`>= 0`; `0` is legal so offline
runs need no real wait) and `--max-scans` must be a positive integer, so a bad
value fails fast with an exit-2 usage error before any scan runs. By default it
is a live monitor — unlike `scan` it writes no slate file and prints no
`slate written:` trailer unless you opt in with `--out-dir DIR`. A single failed
scan (an exhausted retry or a non-retryable model fault) is logged to stderr as
`scan <n> failed: …` and the watch rides on to the next tick, so a transient
outage never kills the long-lived loop.

`--out-dir DIR` makes the monitor the *producer* of a slate stream: each tick's
slate is persisted as `DIR/slate-<NNN>.json` (1-based tick index, zero-padded to
3, so up to 999 ticks sort chronologically) and that tick prints its own
`slate written: <path>` trailer. Missing parent directories are created on
demand; an existing non-directory at `DIR` — or anywhere on its path — is a
usage error (exit 2) reported before the first scan runs. The names are
index-keyed, never timestamped, so two identical runs produce identical
filenames. Only a tick whose scan completed persists anything: a failed tick
leaves no file and the watch rides on. Retention stays yours — a long-lived
watch grows the directory and this flag makes no pruning promise.

`diff` is the comparative companion to `watch`: hand it two saved slates (`--old`/`--new`) and it classifies goals as added / removed / changed (the score moved past `1e-9` or the gate decision flipped) / unchanged, matched by normalized title (`title.strip().lower()`) rather than the random per-scan id — turning a stream of point-in-time slates into a change feed. `pla watch --out-dir DIR` is what produces that stream (one `slate-<NNN>.json` per tick), so the pair composes with no `scan --out` invocation at all. `--dir DIR` is what makes that composition one command instead of filename arithmetic: point it at the stream directory and `diff` resolves the pair itself — `--new` binds to the highest tick index present and `--old` to the second-highest, ordered by the *parsed integer* (so `slate-1000.json` beats `slate-999.json`, which a lexicographic sort would invert), and directory entries that are not stream files are ignored rather than treated as errors. It is a selector only: once the pair is resolved both modes share one load/gate/render tail, so `--dir` cannot drift from the explicit-path contract, and under `--json` the `old`/`new` fields echo the two RESOLVED paths so a machine consumer can tell which ticks were compared. `--dir` is mutually exclusive with `--old`/`--new`, and a `DIR` that does not exist, is not a directory, or holds fewer than two stream slates is a usage error (exit 2) reported before any slate is loaded. It re-gates each side live, so a goal that crossed the autonomy threshold shows up in `changed`. `--json` emits one `{old, new, added, removed, changed, unchanged_count}` object. Like the other inspectors it builds no `LLMClient`, runs nothing, and writes no file.

That whole chain is runnable OFFLINE with no API key, because the bundled driver `examples/scripted_responses.json` ships **two** `synthesize` responses — the minimum a change feed needs, one tick per side: a two-tick `watch` produces a real stream for `diff --dir` to resolve.

```bash
uv run pla watch --workspace examples/fixture_workspace \
  --provider scripted \
  --scripted-responses examples/scripted_responses.json \
  --max-scans 2 --interval 0 --out-dir .pla_runs/stream

uv run pla diff --dir .pla_runs/stream
```

The second tick is deliberately not a replay of the first: one goal is re-scored (`18.00` → `22.50`), one is dropped and one new one is proposed, so the change feed exercises all four classifications (1 added / 1 removed / 1 changed / 2 unchanged) instead of printing an empty diff. The script is a fixed-length tape, not a generator, so a *third* tick finds no `synthesize` entry left: it logs `scan 3 failed: no scripted response left …` to stderr, persists no third slate, and the watch still exits 0 — the resilient-by-design contract above, demonstrated rather than described.

`policy` sits at the *top* of that arc: it prints the standing autonomy contract itself — the four ordered gate rules (first match wins: a sensitive category always needs approval, then a not-appropriate goal is blocked, then a goal at/above the auto-dispatch threshold runs, else it needs approval), the resolved threshold, and every category tagged sensitive vs. auto-eligible — with **zero input**: no `--workspace`, no slate, no LLM call. It answers "how does this decide what to auto-run vs. gate for approval?" without first running a scan. It reflects env overrides through the same `_settings` seam every verb shares, so `PLA_AUTO_DISPATCH_MIN_SCORE=6 pla policy` shows the *effective* contract. `--json` emits one `{auto_dispatch_min_score, sensitive_categories, categories, rules}` object.

`tools` is the L1 action-surface window one layer below `policy`: where `policy` catalogs the autonomy *rules*, `tools` catalogs what a dispatched goal can actually *do* to the disk. It prints every registered sandbox tool with its access class (`read-only`/`create-update`/`move`/`delete`) and the standing sandbox invariant (writes are confined to `artifacts_dir`; `workspace_root` is read-only) — with the same **zero input** as `policy`: no `--workspace`, no slate, no LLM call. So a reviewer of this public repo can answer "what can a dispatched goal touch, and how dangerous is each door?" without running anything. `--json` emits one `{sandbox, tools[{name, access, description}]}` object whose tool-name set is drift-guarded to equal the live `ToolRegistry` so the catalog can never diverge from what actually dispatches. This completes the transparency arc across both layers: `policy` → `signals` → `tools` → `explain` → `trace`.

`collectors` is the L2-perception *front door* of that arc: it lists every registered context collector — the things the proactivity layer *looks at* — with a one-line description of what each perceives, with the same **zero input** as `policy`/`tools`: no `--workspace`, no slate, no LLM call. Where `signals` needs a `--workspace` and shows only the raw signals that fired *there*, `collectors` answers the prior, context-free question "what perceivers even exist?" against the static collector set — so a portfolio reader can see the whole perception surface with no repo checked out. `--json` emits one `{collectors[{name, kind, description}]}` object whose name set is drift-guarded to equal the live collector registry (`all_collectors()`), the same anti-rot coupling `tools` uses against `ToolRegistry`. `kind` is the `ContextSignal.kind` that collector emits — i.e. the token to hand `pla signals --kind` — which is **not** always the collector's name (`todos` emits `todo`, `git_activity` emits `git_commit`), so the front door now publishes a value the next command in the arc actually accepts; the published mapping is drift-guarded as a bijection onto the live signal-kind registry and against the `kind=` literal each collector's own module emits. `--kind K` inverts it ("which collector emits this?") over that same closed vocabulary. Read the arc front-to-back: `collectors` (what perceivers exist) → `signals` (raw output for a workspace) → `scan` (proposals) → `explain` (why this goal) → `trace` (what a run did).

Two of those perceivers are **relational** — they report a contradiction *between* two artifacts rather than a fact about one. `lockfile_drift` pairs a dependency manifest with its sibling lockfile (missing, or older than the manifest). `broken_link` pairs a relative Markdown link with the filesystem that disproves it: for every `*.md` file under the workspace it emits one `kind="broken_link"` signal per inline `[text](target)` link or `![alt](target)` image whose target does not exist, resolved relative to the *containing file's* directory the way a renderer resolves it, with the line number in the summary and the containing file in `path`. It stays deliberately quiet where a finding would be noise: a fragment/query is stripped before the existence test (`real.md#heading` tests `real.md`), links inside a fenced block or a backtick inline-code span are code samples and are skipped, and any target that is not a workspace path — a URL scheme, a protocol-relative `//host`, a site-root `/path`, or a bare `#anchor` — is ignored rather than fetched, so the runtime stays offline-first. Reference-style links and raw HTML `<a href>` tags are out of scope.

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

`run --json` publishes what an invocation of the sole autonomous verb actually
produced, so a script never has to re-glob the state dir and guess at `run-*`
names. Stdout becomes exactly one JSON object with six always-present keys ---
`workspace_root`, `slate_path`, `goal_count` (how many goals the slate holds),
`needs_approval` (`[{id, title}]`, the goals the L2 gate withheld), `top_goal`
(`{id, title}`, or `null` when the slate has no auto-dispatchable goal) and
`dispatched` --- and everything the default run prints to stdout goes to
**stderr** instead, verbatim, so a `--json` run is still watchable while
`pla run ... --json | jq` sees one clean document. On a real dispatch
`dispatched` is `{goal_id, run_id, status, run_dir, artifacts, iterations_used,
llm_calls_used, retries, parse_errors}` --- the machine-readable twin of the
`dispatched :` summary, reporting the same run dir and the same artifact paths,
with `run_id`/`status` matching that run dir's `checkpoint.json`. Under
`--dry-run` it is `null` while `top_goal` still names the goal a real run would
have dispatched, so the preview reports its intent and never a run that
happened. The count key is `goal_count`, not `goals`, because `scan --format
json` already publishes `goals` as an array of goal objects and one key name
must not mean two types across the CLI. A failed invocation emits no JSON at
all: `run --json` against a missing `--workspace` still exits 2 with
`error: workspace not found: <path>` on stderr and leaves stdout **empty**,
rather than a half-formed document a consumer might parse.

`dispatch --json` publishes that same `dispatched` document at the *top* level ---
the identical nine keys, built by one shared function so the two verbs cannot drift
into two dialects of one fact --- with the human summary on **stderr**. That makes
the approval-gated path scriptable, which matters more than it does on `run`: the
autonomy contract makes human approval MANDATORY for a sensitive goal, so `dispatch`
is the verb an orchestrator must use for exactly the goals a human just approved. The
gate is untouched, so stdout stays **empty** on every refusal --- a BLOCKED goal still
exits 3 and an approval-needing goal without `--yes` still exits 4, each with its
message on stderr.

`resume --json` closes that contract on the RECOVERY path, and it is the one place
it matters most: `resume` is the verb a supervising script re-invokes after a budget
exhaustion or an interrupted run, so without it a machine could read the run that
*failed* (`run --json`, `dispatch --json`, `runs --json`) but had to parse English to
learn what the *retry* produced. Stdout becomes the same nine-key document at top
level --- built by that one shared function, from a third call site rather than a
copied literal, so the key set is equal to `dispatch --json`'s by construction --- with
the human run summary on **stderr**. It adds no exit code and no key: a run dir with
no loadable checkpoint still exits 2 with `error: no checkpoint found in <dir>` on
stderr and leaves stdout **empty**, never a half-formed document, and a bare
`pla resume --run-dir DIR` is byte-identical to before.

`examples/check_run.py` is the committed *consumer* of that shared document, and it
exists because a published contract nobody executes is a guess: the paragraphs above
sell `pla run ... --json | jq`, but `jq` cannot be a dependency of an offline-first
project, so nothing outside `tests/` ever read one of these documents. Pipe any of the
three verbs into it -- `pla run ... --json | python examples/check_run.py` -- and it
prints one `ok: ` summary line naming the run id and status, exiting **0** only when
the dispatched run reached the terminal `done` status. It exits **1** when the document
parsed and the run did not succeed (a non-success status, or nothing dispatched at all,
which is what `--dry-run` publishes) and **2** when stdin was not one JSON object, so a
caller can tell a bad pipe from a bad run. One consumer serves all three verbs because
a top-level `status` key discriminates the two shapes: `dispatch --json` and
`resume --json` publish the nine keys at top level, while `run --json` nests them under
`dispatched`. The success value is imported from `proactive_loop.models.RunStatus`,
never typed as a literal --- this consumer's own first draft guessed `completed` ---
so renaming that enum member fails the example loudly instead of leaving a stranger's
script reporting failure on every successful run. Standard library only: no `jq`, no
network, no new dependency.

### What the state directory contains

Every dispatched goal leaves an audit trail on disk, and `--state-dir` (default
`.pla_runs`) is its root. The slate sits at the top of that directory; each
dispatched goal then gets a directory of its own named `run-<goal_id>`, and that
run dir is the unit `runs` lists, `runs --prune` retires, and `resume`/`trace`
take as `--run-dir`:

| Path | Written when | Contents |
|------|--------------|----------|
| `slate.json` — top of the state dir | every `scan` (unless `--out` points elsewhere) and every `run`, including `run --dry-run` | The whole slate as the synthesizer produced it — `{created_at, workspace_root, goals}` — in storage order, not display order (`ranked()` sorts on read), and with no gate verdicts, which are printed but never persisted. The record `dispatch`, `explain` and `diff` read back. |
| `meta.json` — in the run dir | once, as the run dir is created | Exactly two keys, `{workspace_root, artifacts_dir}`. The workspace path is the one a later `resume` can get nowhere else: the checkpoint records the artifacts dir, but not the workspace the run was scanned from. |
| `checkpoint.json` — in the run dir | rewritten atomically after **every step** | The whole run state: run id, goal, status, every PLAN/ACT/CHECK step, iterations and LLM calls used, retries, parse errors, artifacts dir, creation time. What `resume` continues from and `trace` renders. |
| `artifacts/` — in the run dir | when the run starts, before its first tool call | The ACT sandbox's only writable root, so it holds everything the goal actually produced. `runs` reports its recursive file count per run. |

`checkpoint.json` is what makes the L0 durability promise checkable rather than a
claim: the executor appends one step and saves immediately, and the save lands in
a temp sibling that is then moved into place, so an interrupted run leaves either
the previous snapshot or the new one — never a truncated file — and loses at most
one step. `artifacts/` is the other half of the sandbox invariant `tools` prints:
writes are confined there while the workspace stays read-only, so auditing a run
is "read its `checkpoint.json`, then list its `artifacts/`".

### Exit codes

`pla` distinguishes a *deliberate refusal* from a *fault*, so a wrapper script
should branch on the exit code rather than treat every non-zero exit as a
failure. The contract lives in the docstring of `proactive_loop.cli.main`.

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | Operational fault — a foreseeable operator or environment error (an unknown `--provider`, a **malformed** slate or `checkpoint.json`, a missing `--scripted-responses` script, a model-boundary failure once the retry budget is spent, or a collector that owns a `signals --fail-on-kind` gated kind crashing mid-scan, which fails the gate closed rather than reporting a green `0` it cannot prove). Reported as one `error: ...` line on stderr, never a traceback. |
| 2 | Nothing to act on, or the invocation was wrong — a path you passed does not **exist** (`--workspace`, `--slate`, `--old`/`--new`, or a `--run-dir` holding no `checkpoint.json`), a `diff --dir` stream directory is missing, is not a directory, or holds fewer than two `slate-<NNN>.json` ticks, the two `diff` selector modes are combined (`--dir` alongside `--old`/`--new`) or neither is given, an output target is unusable (`--out` or `--state-dir` is not a directory), or a goal id is not in the slate. argparse also exits `2` on a usage error (an unknown flag, or an invalid `--format` / `--kind` / `--collector` / `--status` value). |
| 3 | BLOCKED by the autonomy contract — the goal is refused as a policy decision, so `--yes` does not help and re-running it changes nothing. Rewrite or drop the goal. |
| 4 | NEEDS_APPROVAL — the goal is legitimate but sensitive, so it stops and waits for a person. Once a human has approved it, re-run the same command with `--yes`. |
| 5 | A gate you armed tripped on a **finding** — the command itself succeeded and printed its normal output, but a gate you armed refused the result: a `--fail-on-kind` gate matched at least one reported signal (`pla signals --workspace . --fail-on-kind secret_file`), a `--fail-over N` budget saw **more** reported signals than `N` (`pla signals --workspace . --fail-over 30`), or `verify --fail-on-unresolved` could not resolve a cited source against the snapshot (`pla verify --slate slate.json --snapshot snap.json --fail-on-unresolved`). Not a fault (`1`) and not an empty result (`2`): this is the channel a pre-commit hook or a CI step branches on. Whichever gate tripped names itself on one `gate: ...` line on stderr; stdout is unchanged. |

## Use as a library

`pla` is the primary interface, but the layers underneath it are an importable,
fully typed package. The root `proactive_loop` namespace re-exports the **data
contract** every layer speaks: what a collector perceives (`ContextSignal`,
`WorkspaceSnapshot`), what the scout proposes (`CandidateGoal`, `GoalSlate`,
`GoalCategory`), how the gate rules (`DispatchDecision`, `AutonomyDecision`),
what a run records (`RunState`, `RunStatus`, `LoopStep`, `StepKind`), and how it
is all configured (`Settings`, `RetryPolicy`). That promised surface is exactly
**13 names**, enumerated in `proactive_loop.__all__`.

Behavior entry points are deliberately **not** re-exported at the root — they
keep their sub-package paths (`proactive_loop.collectors`, `proactive_loop.scout`,
`proactive_loop.loop`, `proactive_loop.llm`). Two consequences worth knowing: the
compatibility promise stays small (the re-exported types are the persisted JSON
schema, so they are already frozen, while the internals stay free to move), and
`import proactive_loop` never drags in the CLI, so importing the library costs no
argparse setup.

```python
from proactive_loop import CandidateGoal, ContextSignal, GoalCategory, GoalSlate, Settings
from proactive_loop.scout import gate_slate

signal = ContextSignal(
    source="notes",
    kind="note",
    summary="the importable API is undocumented",
)
goal = CandidateGoal(
    title="Document the library surface",
    rationale=signal.summary,
    sources=[signal.summary],
    category=GoalCategory.PROJECT,
)
slate = GoalSlate(workspace_root=".", goals=[goal])

# The autonomy gate is a pure function of the slate plus settings — no I/O and no
# network — so a host can rule on candidates before deciding to run anything.
for decision in gate_slate(slate, Settings()):
    print(decision.goal_id, decision.decision.value, decision.reason)

# Every promised type is a pydantic model, so a slate round-trips through JSON:
# this is the same schema the artifacts under the state dir already hold.
restored = GoalSlate.model_validate_json(slate.model_dump_json())
for candidate in restored.ranked():
    print(candidate.title, candidate.score, candidate.category.value)
```

Because the package ships a `py.typed` marker, a downstream project type-checks
against these models directly — no stub package, and no reaching into private
module paths. Two names that are public in their own modules stay out of the root
promise on purpose: `ensure_dir` and `sanitize_validation_error` are internal
helpers rather than part of the data contract, and remain importable from
`proactive_loop.models`.

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
pla run \
  --workspace examples/fixture_workspace \
  --provider scripted \
  --scripted-responses examples/scripted_responses.json
```

That form is runnable as printed from a fresh clone with no credentials --
it tunes L0 against the bundled offline fixture, where the scripted provider
can be told to `{"raise": "throttle"}` and you can watch the backoff with
`-vv`. The same five retry knobs in the table above apply unchanged to a live
provider (swap in `--provider anthropic` and drop `--scripted-responses`),
which is where throttling actually happens.

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

## Pre-commit hook (opt-in)

`hooks/pre-commit` points the `signals` gate at your own commits: it runs `pla signals --workspace .`
in gate mode over the working tree and lets git abort the commit when the gate exits **5**. It is a
plain POSIX-sh git hook -- no hook framework, no network, no dependency beyond this project's own CLI
-- and cloning does **not** install it. Opt in per clone with one line (unset `core.hooksPath` again
to uninstall):

```bash
git config core.hooksPath hooks
```

It arms **the same four kinds the CI self-scan arms** -- `merge_conflict`, `syntax_error`,
`secret_file`, `broken_link` -- and the suite parses both files and fails the build if the two ever
diverge, so the local and CI gates cannot drift apart. That set is deliberately the
state-*independent*, must-never-appear subset: a conflict marker, unparseable Python, a secret-shaped
file or a Markdown link pointing at a path the filesystem disproves breaks the tree for everyone who
checks it out, whereas signals about uncommitted work or a fresh TODO are red for any developer
mid-edit and arming them would just teach you to bypass the hook every time.

The CLI's exit status passes through unchanged (**5** = a gate you armed tripped on a finding, **2** =
usage error), and git aborts the commit on any non-zero value. The hook adds nothing to stdout on any
path -- whatever the CLI printed is reproduced byte-identically -- and explains itself on stderr. If
neither `pla` nor `uv` is on `PATH` it fails **closed** (exit 1) rather than reporting success on a
machine where it never ran. To commit anyway, use `git commit --no-verify`.

Two limits worth knowing: it inspects the **working tree**, not the staged index, so an unstaged
finding still blocks the commit; and it is not wired into `make check`, which runs the same gate as
its own last step.

## License

MIT -- see [LICENSE](LICENSE).
