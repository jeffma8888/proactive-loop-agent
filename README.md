# proactive-loop-agent

A **proactivity layer** for agentic systems. Instead of waiting for a person to
hand it a goal, the agent scans their working context, synthesizes a *ranked
slate* of candidate goals, gates each one through an autonomy contract, and
dispatches only the approved ones into a resilient execution loop.

The whole system runs **fully offline** by default: the LLM boundary is a
scripted, deterministic double, so the demo and tests need no network and no API
keys.

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
  cherry-pick / revert, detached HEAD), `TODO`/`FIXME` comments, notes,
  dependency manifests, untested source directories, leftover merge-conflict
  markers in committed files, large files past a size threshold) into a ranked list of
  candidate goals,
  then applies a policy
  gate. Sensitive categories (finance/legal, health/admin) *always* require
  human approval, no matter how high they score.
- **L1 goal loop** drives one approved goal through bounded plan/act/check
  iterations. The ACT phase can only touch a sandboxed artifacts directory.
- **L0 resilience** wraps every model call in retry-with-backoff and checkpoints
  the run state after every step, so a throttle blip or a crash never loses more
  than the in-flight step. Each recovered retry is counted on the run and shown
  in the run summary and the `pla trace` header, so the self-healing is visible.

## Quickstart

```bash
uv sync        # install the locked dependency set (pydantic + pytest)
make demo      # scan the fixture workspace and auto-dispatch the top goal
make test      # run the full offline test suite
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
| `scan`    | Collect context, synthesize + gate a slate, print it (`--format table\|json\|markdown\|csv`; `--top N` caps the printed rows, the written slate stays complete), write slate JSON.|
| `dispatch`| Re-gate one goal from a saved slate and run it (`--yes` confirms approval).|
| `run`     | Scan, then auto-dispatch only the single top AUTO_DISPATCH goal.          |
| `resume`  | Load a checkpoint from a run dir and continue the loop.                   |
| `runs`    | List past dispatched runs under the state dir (`--json` for a JSON array).|
| `explain` | Show one goal's score math, gate decision + reason, and provenance (`--json` for a JSON object; read-only, LLM-free).|
| `trace`   | Render one run's PLAN/ACT/CHECK step transcript from its checkpoint (`--json` for a full array; read-only).|
| `signals` | Print the raw context signals the collectors perceive for a workspace (`--json`; `--kind K` filters; read-only, LLM-free).|
| `watch`   | Repeatedly re-scan a workspace on an interval and re-print the slate (`--interval S`; `--max-scans N`; live monitor, writes no slate file).|
| `diff`    | Compare two saved slates and classify goals as added/removed/changed/unchanged (`--old A.json --new B.json`; `--json` for a JSON object; matched by normalized title; read-only, LLM-free).|
| `policy`  | Print the standing autonomy contract: the four ordered gate rules, the auto-dispatch threshold, and every category tagged sensitive/auto-eligible (`--json` for a JSON object; read-only, LLM-free, no workspace).|

Together these verbs form a transparency arc across the pipeline —
`signals` (what the collectors *see*) → `scan` (what the scout *proposes*) →
`explain` (why the gate *ruled*) → `trace` (what a run *did*). `signals`,
`explain`, `trace`, `runs`, `diff`, and `policy` are read-only and need no LLM call;
`scan` is the one synthesizing step — it calls the LLM and writes the slate.

`watch` turns that one-shot scan into the product's namesake proactive loop: it
re-runs the scan pipeline every `--interval` seconds (default 3600) and re-prints
the ranked, gated slate as your context changes, running until interrupted with
Ctrl-C unless `--max-scans N` bounds it. Both knobs are guarded at parse time
like `--top`: `--interval` must be a finite non-negative number (`>= 0`; `0` is legal so offline
runs need no real wait) and `--max-scans` must be a positive integer, so a bad
value fails fast with an exit-2 usage error before any scan runs. It is a live
monitor — unlike `scan` it writes no slate file and prints no `slate written:`
trailer.

`diff` is the comparative companion to `watch`: hand it two saved slates (`--old`/`--new`) and it classifies goals as added / removed / changed (the score moved past `1e-9` or the gate decision flipped) / unchanged, matched by normalized title (`title.strip().lower()`) rather than the random per-scan id — turning a stream of point-in-time slates into a change feed. It re-gates each side live, so a goal that crossed the autonomy threshold shows up in `changed`. `--json` emits one `{old, new, added, removed, changed, unchanged_count}` object. Like the other inspectors it builds no `LLMClient`, runs nothing, and writes no file.

`policy` sits at the *top* of that arc: it prints the standing autonomy contract itself — the four ordered gate rules (first match wins: a sensitive category always needs approval, then a not-appropriate goal is blocked, then a goal at/above the auto-dispatch threshold runs, else it needs approval), the resolved threshold, and every category tagged sensitive vs. auto-eligible — with **zero input**: no `--workspace`, no slate, no LLM call. It answers "how does this decide what to auto-run vs. gate for approval?" without first running a scan. It reflects env overrides through the same `_settings` seam every verb shares, so `PLA_AUTO_DISPATCH_MIN_SCORE=6 pla policy` shows the *effective* contract. `--json` emits one `{auto_dispatch_min_score, sensitive_categories, categories, rules}` object.

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

An invalid `--format` value is rejected by argparse as a usage error (exit 2).

`scan --top N` caps the STDOUT rendering to the N highest-ranked goals (across
all four `--format` values), while the slate file it writes always stays the
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
`openai`, `bedrock`, `ollama`) is a one-flag change and lazily imports only that
SDK. The `ollama` provider runs the full plan->act->check loop against a
locally-hosted model with **no API key and no network egress** -- extending
offline-first from the scripted test double to real runtime execution.

## License

MIT -- see [LICENSE](LICENSE).
