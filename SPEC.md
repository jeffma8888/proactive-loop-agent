# proactive-loop-agent — Design & Module Contracts

> The implementation was built contract-first against this document. It records
> each module's public surface and the invariants the layers rely on.

## 1. Concept

A **proactivity layer (L2)** on top of goal-mode loop engineering (L1):

```
            ┌─────────────────────────────────────────────────┐
            │ L2  SCOUT (proactivity)                         │
            │  collectors ─▶ signals ─▶ synthesizer ─▶ slate  │
            │                       (LLM)      ranked goals   │
            │                 policy gate: AUTO / APPROVAL    │
            └───────────────────────┬─────────────────────────┘
                                    │ dispatch(goal)
            ┌───────────────────────▼─────────────────────────┐
            │ L1  GOAL LOOP (execution)                       │
            │  iterate: PLAN (LLM) ─▶ ACT (tool) ─▶ CHECK (LLM)│
            │  until done or budget exhausted                 │
            └───────────────────────┬─────────────────────────┘
            ┌───────────────────────▼─────────────────────────┐
            │ L0  RESILIENCE                                  │
            │  retry + exp backoff + jitter on throttle/timeout│
            │  atomic JSON checkpoints, resumable runs        │
            └─────────────────────────────────────────────────┘
```

Instead of the user handing the agent a goal, the agent **scans the user's working
context** (recent files, git activity, TODOs, notes), **synthesizes a ranked slate
of candidate goals**, gates them through an **autonomy contract** (sensitive
categories always need human approval), and **dispatches** approved goals into a
resilient plan→act→check execution loop.

## 2. Layout

```
proactive-loop-agent/
├── pyproject.toml            # uv-managed, src layout, console script `pla`
├── Makefile                  # setup / test / demo / clean targets
├── README.md
├── LICENSE                   # MIT
├── SPEC.md                   # this file
├── src/proactive_loop/
│   ├── __init__.py           # package metadata + __version__ (single source of truth)
│   ├── models.py             # pydantic domain models
│   ├── config.py             # Settings / RetryPolicy
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py         # LLMClient protocol, ScriptedLLMClient, errors
│   │   └── providers.py      # create_client(settings) provider switch, lazy imports
│   ├── collectors/
│   │   ├── __init__.py       # all_collectors() registry
│   │   ├── base.py           # Collector protocol
│   │   ├── filesystem.py     # RecentFilesCollector
│   │   ├── git_activity.py   # GitActivityCollector
│   │   ├── todos.py          # TodoCollector
│   │   └── notes.py          # NotesCollector
│   ├── scout/
│   │   ├── __init__.py
│   │   ├── synthesizer.py    # signals -> LLM -> GoalSlate (re-scored, deduped)
│   │   └── policy.py         # autonomy contract gate
│   ├── loop/
│   │   ├── __init__.py
│   │   ├── tools.py          # sandboxed ToolRegistry
│   │   ├── resilience.py     # with_retry(), Checkpoint
│   │   └── executor.py       # GoalLoop plan→act→check
│   ├── scheduler.py          # periodic scan trigger
│   └── cli.py                # argparse CLI: scan / dispatch / run / resume / runs / explain / trace / signals
├── examples/
│   ├── fixture_workspace/    # fake user workspace (no git repo inside)
│   └── scripted_responses.json
└── tests/                    # one test module per package
```

## 3. Foundation contracts

- `src/proactive_loop/models.py` — all domain models & enums.
- `src/proactive_loop/config.py` — `Settings.from_env()`, `RetryPolicy`.
- `src/proactive_loop/llm/client.py` — `LLMClient` protocol, `LLMResponse`,
  `ScriptedLLMClient`, `LLMThrottleError`, `LLMTimeoutError`, `ScriptExhaustedError`,
  `parse_json_block(text)`.

Key invariants the other layers rely on:

- `CandidateGoal.score` = computed field = `impact * urgency * confidence / effort_weight`.
- `GoalSlate.ranked()` sorts by `(appropriate_now desc, score desc)`.
- `ScriptedLLMClient` matches on `tag` (exact match, else entries with tag `""`
  match anything), consumes entries in order, supports scripted failures via
  `{"raise": "throttle"|"timeout"}`, raises `ScriptExhaustedError` when empty.
- `parse_json_block` tolerates ```json fences, leading/trailing prose, and
  trailing junk after a valid value (e.g. a stray brace) via `raw_decode`.
- `RunState.retries` is a non-negative int counter (default `0`) of the L0
  backoff-retries the L1 executor recovered from during a run. Defaulted so a
  pre-existing checkpoint written without the key still deserializes cleanly as
  `retries == 0` (a non-breaking, non-versioned foundation-contract addition).
- `Settings.auto_dispatch_min_score` is a non-negative float (`Field(ge=0.0)`,
  default `4.0`); a negative threshold is rejected at construction to prevent a
  silent whole-slate auto-dispatch (all score operands are bounded `>= 0`, so a
  negative threshold would auto-fire the gate for every non-sensitive goal).

## 4. Module contracts

### 4.1 collectors

```python
# base.py
class Collector(Protocol):
    name: str
    def collect(self, root: Path) -> list[ContextSignal]: ...
```

- Every collector is **pure stdlib + deterministic**, never raises on a missing
  dir/tool — degrade to `[]`.
- `filesystem.py: RecentFilesCollector(name="recent_files", max_files=20, within_days=14)`
  — walk `root`, skip hidden dirs / `node_modules` / `.venv` / `__pycache__`,
  emit one signal per recently-modified file, `kind="recent_file"`, weight by recency.
- `git_activity.py: GitActivityCollector(name="git_activity", max_commits=15)` —
  `git -C <dir> log --pretty=...` via subprocess for `root` and each direct child dir
  that has `.git`; `kind="git_commit"`; return `[]` if git missing/not a repo.
- `todos.py: TodoCollector(name="todos", max_items=30)` — scan `*.py,*.ts,*.js,*.md`
  for `TODO|FIXME|XXX` comments and markdown `- [ ]` checkboxes; `kind="todo"`.
- `notes.py: NotesCollector(name="notes", max_items=20)` — scan `*.md` under dirs
  named `notes|journal|docs`; emit heading (`# ...`) + first paragraph signals,
  `kind="note"`.
- `dependencies.py: DependencyCollector(name="dependencies", max_manifests=20)` —
  walk `root` (same skip rules as `RecentFilesCollector`) and emit one signal per
  `pyproject.toml` / `requirements.txt` / `package.json`, `kind="dependency"`;
  stdlib-only parse (`tomllib`/`json`/line-split), never raises → `[]`. Reports
  facts (ecosystem, manifest, declared-dep count) only; the synthesizer judges.
- `working_tree.py: WorkingTreeCollector(name="working_tree", max_items=30)` —
  present-state git companion to `git_activity` (which sees only the committed
  past). `git -C <dir> status --porcelain` via subprocess for `root` and each
  direct child dir that has `.git`; emits one `kind="working_tree"` signal per
  changed path (tracked change or untracked file; per-path signals capped at
  `max_items`) plus at most one summary signal counting unpushed local commits.
  Unpushed detection reads ONLY the local tracking ref (`git rev-list --count
  @{u}..HEAD`) — it NEVER runs `git fetch`/`ls-remote` or any network op (see
  section 5); never raises → `[]`. Reports facts only; the synthesizer judges.
  (Additive, non-breaking foundation-contract addition.)
- `test_posture.py: TestPostureCollector(name="test_posture", max_items=20)` —
  walk `root` (same skip rules as `RecentFilesCollector`, reusing `_SKIP_DIRS`/
  `_is_hidden`) and emit one `kind="test_posture"` signal per top-level project
  dir (direct child of `root`, or `"."` for files in `root`) that contains at
  least one *source* file. A candidate file (`.py`/`.ts`/`.js`/`.go`/`.rs`) is a
  *test* file when its name starts with `test_`, its stem ends with `_test`, it
  contains `.test.`/`.spec.`, or it lives under a `tests`/`test`/`__tests__`
  dir; anything else is source. Summary `"<project>: <S> src, <T> test files"`
  with ` (untested)` appended iff `T == 0`; weight `0.7` untested else `0.4`.
  Stdlib-only (`os`/`pathlib`), never raises → `[]`. Reports the raw `(src,
  test)` counts only; the synthesizer judges whether to propose adding tests.
  (Additive collector, exactly like iters 09/11 — no version bump.)
- `__init__.py: def all_collectors() -> list[Collector]` returns one instance of each.
- Tests: `tests/test_collectors.py` — tmp_path fixtures per collector, incl. a real
  temp git repo (subprocess git init/commit; skip test if git unavailable) and
  graceful-degradation asserts.

### 4.2 llm/providers.py

```python
def create_client(settings: Settings) -> LLMClient: ...
```

- `settings.provider`: `"scripted"` (default) → `ScriptedLLMClient.from_file(settings.scripted_responses_path)`
  (empty client with clear error message if path is None); `"anthropic"` / `"openai"` /
  `"bedrock"` → **lazy import** inside the branch, thin adapter class per provider
  mapping SDK throttle/timeout exceptions to `LLMThrottleError`/`LLMTimeoutError`.
- Unknown provider → `ValueError` listing valid options.
- Tests: `tests/test_providers.py` — scripted path works from file; unknown provider
  raises; **prove no `anthropic`/`openai`/`boto3` import leak** when provider=scripted
  (assert not in `sys.modules` after create).

### 4.3 scout

```python
# synthesizer.py
class GoalSynthesizer:
    def __init__(self, client: LLMClient, settings: Settings,
                 *, sleep: Callable[[float], object] = time.sleep): ...
    def synthesize(self, snapshot: WorkspaceSnapshot) -> GoalSlate: ...
SYNTHESIZE_TAG = "synthesize"
```

- Builds a compact prompt from signals (grouped by kind, capped length), calls
  `client.complete(system=..., prompt=..., tag=SYNTHESIZE_TAG)`, parses a JSON array
  of goal dicts via `parse_json_block`, validates into `CandidateGoal`
  (invalid entries are skipped, not fatal), **re-computes nothing** (score is a
  computed field), dedupes by normalized title, returns `GoalSlate`.
- The single `client.complete(...)` call is wrapped in
  `with_retry(_call, settings.retry, sleep=self._sleep)` (an L2 → L0 dependency;
  the arrow points inward), mirroring the L1 executor so a transient
  throttle/timeout on the scout's front-door model call recovers with backoff
  instead of crashing the scan. `sleep` is an optional keyword-only ctor arg
  (default `time.sleep`), injected for deterministic, wait-free tests; only
  `LLMThrottleError`/`LLMTimeoutError` are retried, so non-transient errors
  still surface immediately.
- LLM JSON contract (documented in module docstring):
  `[{"title","rationale","category","impact","urgency","confidence","effort_weight","appropriate_now","sources","suggested_first_steps"}]`
- `policy.py`:

```python
def gate(goal: CandidateGoal, settings: Settings) -> DispatchDecision: ...
def gate_slate(slate: GoalSlate, settings: Settings) -> list[DispatchDecision]: ...
```

  Rules, in order: category in `settings.sensitive_categories` → NEEDS_APPROVAL
  ("sensitive category"); `not appropriate_now` → BLOCKED; `score >=
  settings.auto_dispatch_min_score` → AUTO_DISPATCH; else NEEDS_APPROVAL ("below
  auto-dispatch threshold").
- Tests: `tests/test_scout.py` — synthesizer happy path w/ ScriptedLLMClient, malformed
  entry skipped, dedup, ranking order; policy: sensitive NEVER auto-dispatches even at
  max score; threshold boundary; blocked when not appropriate_now.

### 4.4 loop

```python
# tools.py
class ToolRegistry:
    def __init__(self, workspace_root: Path, artifacts_dir: Path): ...
    def execute(self, tool: str, args: dict) -> str: ...   # returns observation text
    def artifacts(self) -> list[str]: ...                  # relpaths written so far
```

  Tools: `write_file(path, content)` → overwrites under `artifacts_dir` ONLY (reject
  `..` and absolute paths); `append_file(path, content)` → *extends* (append mode)
  under `artifacts_dir` ONLY, creating the file (and parents) if absent, with the same
  `..`/absolute/symlink refusals as `write_file` — the incremental-authoring primitive
  so a multi-step goal grows an artifact without a read-then-rewrite (additive tool
  added in iter-17 — existing tool contracts unchanged, so **no version bump**,
  mirroring iter-13's `search_files`); `read_file(path)` → workspace_root or
  artifacts_dir, read-only; `list_files(path=".")`; `search_files(query, path=".")` →
  case-insensitive substring grep over `workspace_root` first (then `artifacts_dir`),
  recursive, read-only, deterministic order (relpath asc, then line no.), bounded to 50
  hits (additive tool added in iter-13 — existing tool contracts unchanged, so **no
  version bump**, mirroring iter-08's additive `RunState.retries`). Unknown tool →
  observation string starting `"error:"` (never raises — the loop feeds errors
  back to the model).

```python
# resilience.py
def with_retry(fn: Callable[[], T], policy: RetryPolicy,
               *, sleep=time.sleep, on_retry: Callable[[int, float, Exception], None] | None = None) -> T
class Checkpoint:
    def __init__(self, path: Path): ...
    def save(self, state: RunState) -> None:   # atomic: tmp file + os.replace
    def load(self) -> RunState | None: ...
```

  `with_retry` retries ONLY `LLMThrottleError`/`LLMTimeoutError`; backoff =
  `min(base * factor**(attempt-1), max) * (1 ± jitter)`; re-raises after
  `policy.max_attempts`; injectable `sleep` for tests. The optional
  `on_retry(attempt, delay, exc)` hook fires once per recovered backoff-retry
  (the L1 executor passes it to increment `RunState.retries`).

```python
# executor.py
class GoalLoop:
    def __init__(self, client: LLMClient, settings: Settings, tools: ToolRegistry,
                 checkpoint: Checkpoint | None = None): ...
    def run(self, goal: CandidateGoal, *, resume: RunState | None = None) -> RunState: ...
GoalLoop.PLAN_TAG, GoalLoop.CHECK_TAG = "plan", "check"
```

  Per iteration: PLAN — LLM returns JSON `{"thought": str, "action": {"tool": str,
  "args": dict}}`; ACT — `tools.execute`; CHECK — LLM sees observation, returns JSON
  `{"done": bool, "reason": str}`. All LLM calls wrapped in `with_retry`, with an
  `on_retry` hook that increments `RunState.retries` on every recovered
  backoff-retry (PLAN and CHECK alike, since both route through the one wrapped
  call site). Append `LoopStep`s to `RunState`, checkpoint after every step. Stop: done=True → DONE;
  `iterations_used >= settings.max_iterations` or llm call budget hit →
  BUDGET_EXHAUSTED; unparseable PLAN/CHECK JSON → feed error observation back, count
  iteration, continue. `resume` continues from a loaded RunState.
- Tests: `tests/test_loop.py` — 2-iteration scripted run reaches DONE with artifact
  written; sandbox rejects `../evil`; throttle-twice-then-succeed asserts backoff
  sequence via injected sleep; budget exhaustion; checkpoint save→load→resume
  round-trip.

### 4.5 cli + scheduler + examples

- `cli.py` (argparse, `main(argv=None) -> int`, console script `pla`):
  - `pla scan --workspace W [--out slate.json] [--format {table,json,markdown}]` —
    collect → synthesize → gate → render the ranked slate + gate decisions to
    stdout; write slate JSON. `--format` (default `table`, backward compatible)
    selects stdout rendering ONLY and never changes the persisted slate file:
    `table` = the human plain-text table + a `slate written: <path>` trailer (a
    bare `scan` is byte-identical to `--format table`); `json` = one JSON object on
    stdout (`{workspace_root, goals[...]}`, goals in `ranked()` order, each with the
    live gate `decision`/`reason`) and NO trailer, so it pipes cleanly into `jq`;
    `markdown` = a paste-ready GitHub-flavored table (`| # | decision | score |
    category | title |`) plus the same trailer. An invalid `--format` is an argparse
    usage error (exit 2). A missing or non-directory `--workspace` fails fast with
    `error: workspace not found: <path>` on stderr and exit 2 (before any
    client/collect, regardless of `--format`), rather than degrading to an empty
    slate + exit 0.
  - `pla dispatch --slate slate.json --goal-id ID [--yes]` — re-gate; NEEDS_APPROVAL
    requires `--yes`; BLOCKED refuses; run GoalLoop; print summary (status,
    iteration/llm-call budget use, and the run's retry count) + artifact paths.
  - `pla run --workspace W` — scan then auto-dispatch the top AUTO_DISPATCH goal
    (approval-gated goals are listed but never auto-run). Same `--workspace`
    guard as `scan`: a missing/non-directory path -> `error: workspace not found: <path>`
    on stderr + exit 2 (no slate written, no run dir created).
  - `pla resume --run-dir DIR` — load checkpoint, continue.
  - `pla runs [--json]` — read-only, LLM-free lister of past dispatched runs
    under `--state-dir`: one row per `run-<goal_id>/` (run id, status, iterations,
    artifact count, goal title, workspace), id-sorted and deterministic; a run
    dir with no loadable checkpoint degrades to a `(no checkpoint)` row rather
    than aborting. Makes `resume --run-dir DIR`'s argument discoverable. `--json`
    emits a parseable array (`[]` when empty). Builds no `LLMClient`.
  - `pla explain --slate slate.json --goal-id ID` — read-only, LLM-free auditor
    of ONE goal in a saved slate: prints its score arithmetic
    (`impact * urgency * confidence / effort_weight = score`, echoing the model's
    computed `score`), the live `gate(goal, settings)` decision + the rule that
    fired + the auto-dispatch threshold it was compared against (so `explain` and
    a later `dispatch` agree), and the goal's rationale/sources/first-steps.
    Missing slate or unknown id → exit 2; a corrupt slate → exit 1 via the
    `main()` boundary. Builds no `LLMClient`.
  - `pla trace --run-dir DIR [--json]` — read-only, LLM-free renderer of ONE
    dispatched run's persisted PLAN→ACT→CHECK transcript, loaded from its
    `checkpoint.json` (`RunState.steps`). Human form prints a header (run dir,
    goal title+id, status, step/iteration/llm-call counts, and the run's retry
    count) then one single-line entry per step — `[index] kind …output…` with `done=true`/`done=false`
    appended on `check` steps — collapsing embedded newlines and width-truncating
    long output so the block never breaks; empty `steps` degrade to a
    `(no steps recorded)` line. `--json` emits a parseable array (one object per
    step: `index`, `kind`, `output` full/untruncated, `done`, `artifacts`; `[]`
    when empty). `_render_trace` is a pure function of `(state, run_dir)` — it
    reads no `meta.json` (the transcript is fully derivable from the checkpoint,
    dropping a corrupt-meta edge). Missing/absent checkpoint → exit 2 (mirrors
    `resume`); a corrupt checkpoint → exit 1 via the `main()` boundary. Builds
    no `LLMClient`. Completes the run-lifecycle triad runs (find) → trace
    (inspect) → resume (continue).
  - `pla signals --workspace W [--json] [--kind K]` — read-only, LLM-free
    inspector of the FIRST pipeline stage: the raw `ContextSignal`s the collectors
    perceive for a workspace, printed WITHOUT synthesizing (builds no `LLMClient`),
    so `scan`'s question "what does the scout actually see?" is answerable with
    zero provider config and no LLM call. Human form groups signals under a
    `## <kind> (<count>)` header per distinct kind (kinds sorted ascending;
    signals within a kind ordered by `(source, summary, path or "")`), one
    two-space-indented line per signal — `  <source>  w<weight:.2f>  <summary>`
    with ` -> <path>` appended only when the signal carries a path — and an empty
    selection degrades to a single `(no signals collected)` line. `--json` emits
    one object `{workspace_root, signals[...]}` where each signal is an explicit
    dict of exactly the six keys `source, kind, summary, detail, path, weight`
    (no `timestamp`; the iter-08 schema-leak discipline), the flat `signals` array
    ordered by `(kind, source, summary, path or "")`, degrading to `[]` (not the
    human marker) when a `--kind` matches nothing, so it pipes cleanly into `jq`.
    `--kind K` narrows to one collector-defined kind (dynamic; not validated
    against a fixed enum — an unknown kind is just an empty selection). A
    missing/non-directory `--workspace` fails fast with
    `error: workspace not found: <path>` on stderr + exit 2 (the verbatim iter-10
    guard, before any collection), regardless of `--json`/`--kind`. Completes the
    transparency arc signals (see) → scan (propose) → explain (gate) → trace (did).
  - Global flags: `--provider`, `--scripted-responses`, `--state-dir`.
- `scheduler.py`: `run_periodic(scan_fn, interval_sec, *, iterations=None, sleep=time.sleep)`
  — calls scan_fn every interval; iterations=None → forever; injectable for tests.
- `examples/fixture_workspace/`: `projects/ai-experiments/{agent.py,eval_harness.py}`
  (realistic code w/ TODO/FIXME), `projects/api-gateway/server.py`, `notes/journal.md`
  (AI-learning + job-search-flavored entries, personal-project voice, NO real names/
  employers), stray `README.md`. NO `.git` inside.
- `examples/scripted_responses.json`: full end-to-end script — 1 synthesize response
  (4 goals: one high-score AI-learning project goal that auto-dispatches, one career
  goal below threshold, one sensitive-category goal, one not-appropriate-now) + plan/
  check pairs for a 3-iteration loop that writes `learning_plan.md` +
  `project_scaffold.md` artifacts, then done.
- `Makefile`: `setup` (uv sync), `test` (uv run pytest), `demo`
  (uv run pla run --workspace examples/fixture_workspace --provider scripted
  --scripted-responses examples/scripted_responses.json --state-dir .pla_runs),
  `clean`.
- Tests: `tests/test_cli_integration.py` — end-to-end `main([...])` offline demo run
  asserts exit 0, slate file written, artifacts exist, sensitive goal NOT auto-run;
  `tests/test_scheduler.py` — injectable-sleep periodicity.

## 5. Non-negotiables

- Python ≥3.12, pydantic v2 only runtime dep. Tests: pytest. NO other deps.
- Fully offline: NEVER require network/API keys in tests or demo.
- No references to Amazon, internal tools, employers, or real people anywhere.
- Type hints everywhere; docstrings explain WHY; small functions.
- Every module ships with tests; `uv run pytest` must pass from a clean checkout.
