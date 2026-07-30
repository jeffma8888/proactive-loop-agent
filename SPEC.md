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
│   └── cli.py                # argparse CLI: scan / dispatch / run / resume / runs / explain
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

  Tools: `write_file(path, content)` → under `artifacts_dir` ONLY (reject `..` and
  absolute paths); `read_file(path)` → workspace_root or artifacts_dir, read-only;
  `list_files(path=".")`. Unknown tool → observation string starting `"error:"`
  (never raises — the loop feeds errors back to the model).

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
  `policy.max_attempts`; injectable `sleep` for tests.

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
  `{"done": bool, "reason": str}`. All LLM calls wrapped in `with_retry`. Append
  `LoopStep`s to `RunState`, checkpoint after every step. Stop: done=True → DONE;
  `iterations_used >= settings.max_iterations` or llm call budget hit →
  BUDGET_EXHAUSTED; unparseable PLAN/CHECK JSON → feed error observation back, count
  iteration, continue. `resume` continues from a loaded RunState.
- Tests: `tests/test_loop.py` — 2-iteration scripted run reaches DONE with artifact
  written; sandbox rejects `../evil`; throttle-twice-then-succeed asserts backoff
  sequence via injected sleep; budget exhaustion; checkpoint save→load→resume
  round-trip.

### 4.5 cli + scheduler + examples

- `cli.py` (argparse, `main(argv=None) -> int`, console script `pla`):
  - `pla scan --workspace W [--out slate.json]` — collect → synthesize → print ranked
    table (plain text) + gate decisions; write slate JSON.
  - `pla dispatch --slate slate.json --goal-id ID [--yes]` — re-gate; NEEDS_APPROVAL
    requires `--yes`; BLOCKED refuses; run GoalLoop; print summary + artifact paths.
  - `pla run --workspace W` — scan then auto-dispatch the top AUTO_DISPATCH goal
    (approval-gated goals are listed but never auto-run).
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
