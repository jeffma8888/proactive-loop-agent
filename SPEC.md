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
│   └── cli.py                # argparse CLI: scan / dispatch / run / resume / runs / explain / trace / signals / watch / diff / policy
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
  Load-time shape contract (validated eagerly, shared by `from_file` and the
  direct constructor): a file-backed script must be a JSON list or an object
  carrying a list under `"responses"`, and every entry must be an object/dict;
  any violation raises a plain `ValueError` at load/construction (never a raw
  `KeyError`, and never a deferred `AttributeError` inside `complete`), so the
  CLI boundary maps it to one `error:` line + exit 1.
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
  Its `+inf` mirror is rejected too: a non-finite threshold is refused at
  construction (message contains `finite`) because `+inf` passes the `ge` bound yet
  silently *suppresses* the whole slate (every finite score is `< inf`, so the gate
  never resolves AUTO_DISPATCH while `pla run` still exits `0`). No upper bound is
  added — a large finite threshold merely approves less.
- The three upward-unbounded `RetryPolicy` floats (`base_backoff_sec`,
  `backoff_factor`, `max_backoff_sec`) likewise reject non-finite values at
  construction, since an `inf` backoff makes `_backoff_delay` compute `min(raw, inf)
  == inf` and a retry `sleep(inf)` hangs an unattended run forever. `jitter_frac` is
  already fully bounded (`ge=0.0, le=1.0`) and needs no such guard.

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
- `git_state.py: GitStateCollector(name="git_state", max_items=30)` —
  interrupted-operation git companion to `git_activity` (committed past) and
  `working_tree` (present diff/unpushed). Reads `.git` **marker files with
  `pathlib` only** (a genuinely different mechanism — NO `subprocess`, NO
  network, NO `git` invocation) for `root` and each direct child dir whose
  `.git` is a directory, surfacing dangling operations that block or corrupt
  the next action yet are invisible to the other two git collectors: an
  unfinished **merge** (`.git/MERGE_HEAD`), **rebase**
  (`.git/rebase-merge/` or `.git/rebase-apply/`), **cherry-pick**
  (`.git/CHERRY_PICK_HEAD`), **revert** (`.git/REVERT_HEAD`), and a
  **detached HEAD** (`.git/HEAD` holding a raw commit, not `ref: …`). Each
  detected state is independent (no cross-state suppression — a rebase may
  co-emit a detached-HEAD signal) and emits one `kind="git_state"` signal
  with `weight=0.8`, `path=None`; output is sorted by `summary` ascending and
  capped at `max_items`. A `.git` that is a *file* (worktree/submodule
  pointer) is skipped, not followed. Never raises → `[]`. Reports facts only
  (which interrupted state, in which repo dir); the synthesizer judges whether
  to propose finishing or aborting the operation. (Additive collector, exactly
  like iters 09/11/16 — a new `kind` flows into synthesis via `by_kind()` with
  zero synthesizer change, so no version bump.)
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
- `merge_conflict.py: MergeConflictCollector(name="merge_conflict", max_items=30)` —
  committed-conflict-marker companion to `git_state` (which reads `.git/MERGE_HEAD`
  for an *in-progress* merge — that marker vanishes at `git commit` while the
  `<<<<<<<`/`>>>>>>>` TEXT survives inside the committed file). Walk `root` (same
  skip rules as `RecentFilesCollector`, reusing `_SKIP_DIRS`/`_is_hidden`),
  content-scan each scanned-extension file for conflict-marker label lines and
  emit one `kind="merge_conflict"` signal per affected file. A marker line is a
  line whose raw text (no leading-whitespace strip) **starts with** the OPEN
  prefix `"<<<<<<< "` or CLOSE prefix `">>>>>>> "` (seven chevrons + one space at
  column 0); the ambiguous middle `=======` separator is **excluded** from both
  detection and the count (a bare run of `=` is a Markdown setext underline / ASCII
  rule → false positives). `N` = open-prefix lines + close-prefix lines; summary
  `"<relpath>: <N> conflict marker(s)"` (singular only at `N==1`), `detail=""`,
  `weight=0.9`, `path=<relpath>` (forward-slashed, relative to root). Scans a
  focused text/source extension set (case-insensitive; no `.lock`/binary/image
  types); output sorted by relpath ascending and capped at `max_items`. Pure
  stdlib (`os`/`pathlib`), never raises → `[]`. Reports facts only (which file,
  how many markers); the synthesizer judges whether to propose resolving them.
  (Additive collector, exactly like iters 09/11/16/20 — a new `kind` flows into
  synthesis via `by_kind()` with zero synthesizer change, so no version bump.)
- `large_file.py: LargeFileCollector(name="large_file", max_items=20, min_bytes=5_000_000)` — repo-hygiene companion to the other filesystem
  collectors: an oversized file in a workspace (a stray build artifact, an
  accidentally-saved dataset, a checked-in binary) is a classic pre-commit
  hazard that bloats git history the moment it is committed. Walk `root` (same
  skip rules as `RecentFilesCollector`, reusing `_SKIP_DIRS`/`_is_hidden`, and
  skipping hidden files too) and emit one `kind="large_file"` signal per file
  whose size is **at or above** `min_bytes` (inclusive `size >= min_bytes`: a
  file of exactly the threshold IS flagged). Summary
  `"<relpath>: <human> (large)"` where `<relpath>` is forward-slashed relative
  to `root` and `<human>` renders the raw byte size with SI (decimal) units at
  one decimal place (`n>=1_000_000`→`"5.0 MB"`, `1_000<=n<1_000_000`→`"2.5 KB"`,
  `n<1_000`→`"250 B"`); `detail=""`, `weight=0.6` (a fixed mid-range hygiene
  fact, mirroring `DependencyCollector`, not time-decaying), the absolute file
  path in `path`, `timestamp=None`. Output is ordered by descending byte size, ties
  broken by ascending relpath, then capped at `max_items` (the largest files
  are kept). `min_bytes`/`max_items` are ctor-overridable defaults only (no CLI
  flag, no `"5MB"` unit parsing). Reads **only `st_size` metadata and never
  opens file content** (SPEC Out of Scope: no line counting, no MIME sniffing,
  no git/.gitignore/git-lfs awareness), so it structurally cannot raise on
  binary/non-UTF-8 bytes. Pure stdlib (`os`/`pathlib`), never raises → `[]`.
  Reports facts only (which file, how large); the synthesizer judges whether to
  propose gitignoring/removing/LFS-tracking it. (Additive collector, exactly
  like iters 09/11/16/20/28 — a new `kind` flows into synthesis via `by_kind()`
  with zero synthesizer change, so no version bump.)
- `secret_file.py: SecretFileCollector(name="secret_file", max_items=20)` — security-hygiene companion to `large_file`/`merge_conflict`: a secret-shaped
  file committed to a (public) repo is the highest-stakes leak hazard. Walk
  `root` (same dir-prune rules as `RecentFilesCollector`, reusing
  `_SKIP_DIRS`/`_is_hidden` for the DIR prune only) and emit one
  `kind="secret_file"` signal per file whose **case-folded basename** MATCHES
  (exact name ∈ `{.env, .envrc, credentials, .netrc, .npmrc, .pypirc,
  .git-credentials, id_rsa, id_dsa, id_ecdsa, id_ed25519}`, OR starts with the
  `.env.` prefix, OR ends with a key/cert suffix ∈ `{.pem, .key, .p12, .pfx,
  .keystore, .jks}`) and is **not EXCLUDED** (case-folded basename ending in
  `{.example, .sample, .template, .dist, .md, .pub}` — public keys, docs,
  templates). Unlike `large_file`, hidden **files** ARE scanned (the flagship
  `.env`/`.netrc`/`.env.*` targets are hidden); only hidden/skip **dirs** are
  pruned. Files only, never dirs. Summary `"<relpath>: secret-shaped file"`
  where `<relpath>` is forward-slashed relative to `root`; `detail=""`,
  `weight=0.85` (a fixed, high, non-decaying hazard fact, above `large_file`'s
  0.6), the absolute file path in `path`, `timestamp=None`. Output is ordered
  by ascending forward-slashed relpath, then capped at `max_items` (only
  `max_items` is ctor-overridable; the match/exclusion sets are fixed
  constants). **Basename/metadata-only — NEVER opens file content** (no
  entropy/regex content scan, no MIME sniffing, no `.gitignore`/git-lfs
  awareness), so it structurally cannot raise on binary/non-UTF-8 bytes and a
  secret VALUE can never appear in a signal — only the filename can. Pure
  stdlib (`os`/`pathlib`), never raises → `[]`. Reports facts only (which
  file); the synthesizer judges whether to propose gitignoring/removing it.
  (Additive collector, exactly like iters 09/11/16/20/28/41 — a new `kind`
  flows into synthesis via `by_kind()` with zero synthesizer change, so no
  version bump.)
- `__init__.py: def all_collectors() -> list[Collector]` returns one instance of each.
- Tests: `tests/test_collectors.py` — tmp_path fixtures per collector, incl. a real
  temp git repo (subprocess git init/commit; skip test if git unavailable) and
  graceful-degradation asserts.

### 4.2 llm/providers.py

```python
def create_client(settings: Settings) -> LLMClient: ...
```

- `VALID_PROVIDERS == ("scripted", "anthropic", "openai", "bedrock", "ollama")` —
  the single source of accepted provider names, reused verbatim in the
  unknown-provider `ValueError` message and every missing-SDK error path so the
  dispatch and the messages can never drift apart.
- `settings.provider`: `"scripted"` (default) → `ScriptedLLMClient.from_file(settings.scripted_responses_path)`
  (empty client with clear error message if path is None); `"anthropic"` / `"openai"` /
  `"bedrock"` / `"ollama"` → **lazy import** inside the branch, thin adapter class per
  provider mapping SDK throttle/timeout exceptions to `LLMThrottleError`/`LLMTimeoutError`.
- `"ollama"` is the LOCAL / offline runtime backend: a lazy `ollama.Client()` (no API
  key, no network egress; it talks to a model served on `localhost`), `model` defaults
  to `"llama3.1"`, and its throttle/timeout exception taxonomy is sourced from the
  `ollama` namespace ONLY (`ollama.ResponseError` → throttle, `ollama.RequestError` →
  timeout) so the branch depends on no second SDK and construction stays offline. It
  extends the offline-first thesis (section 5) from the scripted test double to real
  runtime execution. Additive, exactly like iter-23 — a new provider whose absence-guard
  and taxonomy reuse the existing machinery, so **no version bump**.
- Unknown provider → `ValueError` listing valid options (all five, incl. `ollama`).
- A live provider (`anthropic`/`openai`/`bedrock`/`ollama`) selected while its optional
  SDK is not installed → an actionable `LLMError` naming the pip package (e.g. `pip
  install boto3` for `bedrock`, whose package name differs from the label; `pip install
  ollama` for `ollama`) and the `--provider scripted` fallback — NOT a raw
  `ModuleNotFoundError` traceback — so the fault routes through `main()`'s narrow
  `except (LLMError, ValueError, OSError)` boundary as a one-line `error: ...` + exit 1
  like every other environment fault.
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
  version bump**, mirroring iter-08's additive `RunState.retries`);
  `find_files(pattern, path=".")` → recursive basename **glob** file discovery over
  `workspace_root` first (then `artifacts_dir`), matching each file's final path
  component against a stdlib `fnmatch` shell glob (`*`/`?`/`[seq]`) case-folded on
  BOTH sides for cross-platform determinism, read-only (matches on name only, never
  reads content), deterministic order (relpath ascending, POSIX `/` separators),
  bounded to 50 hits — the find-by-name third of the discovery triad (list one dir /
  grep content / find by name); a pattern with `/` matches nothing (basename-only
  boundary), directories/symlink-escapes/skip-dirs/hidden entries are never returned
  (additive tool added in iter-21 — existing tool contracts unchanged, so **no
  version bump**, mirroring iter-13's `search_files`); `stat_file(path)` → describe
  ONE path in a single bounded line: a file as `type=file  bytes=<st_size>
  lines=<byte-level splitlines() count>  ext=<suffix|(none)>` and a directory as
  `type=dir  entries=<direct-child count>` (all direct children incl. hidden entries and
  skip-dirs, non-recursive) — the *describe* primitive that triages a path before a full
  `read_file`, completing the discovery family as find / list / grep / describe / read.
  Resolves `artifacts_dir` FIRST then `workspace_root` — the SAME precedence as `read_file`
  (deliberately the OPPOSITE of `list_files`/`search_files`/`find_files`), so `stat_file(x)`
  and `read_file(x)` resolve the same copy and the reported bytes/lines match. Read-only
  (never writes; `artifacts()` unaffected), deterministic (NO mtime / timestamp /
  permission field; the byte-level line count never decodes, so a binary file cannot fault
  it and the count is OS-independent), refuses `..`/absolute/symlink-escape paths, and
  returns `error: no such path: '<p>'` for a path in neither root (additive tool added in
  iter-26 — existing tool contracts unchanged, so **no version bump**, mirroring iter-13's
  `search_files`); `head_file(path, max_lines=40)` → the first `max_lines` lines of a file —
  a bounded top-of-file **peek** so a goal can judge relevance BEFORE committing context to a
  full `read_file` (the sandbox's only unbounded reader). Resolves `artifacts_dir` FIRST then
  `workspace_root` — the SAME precedence as `read_file`/`stat_file`, so `head_file(x)` and
  `read_file(x)` read the same copy. For a file with `<= max_lines` lines the return is
  **byte-identical** to `read_file` (no trailer, original terminators preserved via
  `read_text` + `splitlines(keepends=True)`); a longer file returns its first `max_lines`
  lines plus a single trailer line `... (showing first {max_lines} of {total} lines)`, emitted
  ONLY when truncated (`total > max_lines`). `max_lines` defaults to 40 and accepts an int or
  an integer-valued string; a non-positive/non-integer value → `error: head_file 'max_lines'
  must be a positive integer` (nothing read). Path-safety errors (empty/`..`/absolute) are
  reported BEFORE `max_lines` validation; a symlink escaping both roots and a
  directory/missing target → `error: file not found under artifacts or workspace: '<p>'`
  (mirroring `read_file`). Read-only (never writes; `artifacts()` unaffected), and an
  undecodable (binary) file degrades to an `"error:"` via `execute()`'s never-raise wrapper.
  It completes the bounded-observation family as find / list / grep / describe / PEEK / read
  (additive tool added in iter-29 — existing tool contracts unchanged, so **no version bump**,
  mirroring iter-13's `search_files`); `remove_file(path)` → **deletes** a file under
  `artifacts_dir` ONLY (the first destructive-mutation tool, completing the write-side CRUD
  story create/update/read/**delete**). Refuses `..`/absolute/symlink-escape paths with the
  SAME error strings as `write_file` (via the shared `_reject_unsafe` + a resolved `_within`
  gate that fires BEFORE any `unlink`, so a symlink escaping the sandbox returns `error:
  refusing to remove outside artifacts dir: <p>` and never deletes through the link);
  refuses a directory (`error: refusing to remove a directory: <p>`, dir survives) and a
  missing target (`error: no such artifact: <p>`) with observable errors. It resolves ONLY
  against `artifacts_dir` — never against, and never deleting anything under, the read-only
  `workspace_root` (a workspace-only path degrades to `no such artifact`) — and on success
  returns `removed artifacts/<relpath>`, dropping the relpath from `artifacts()` when tracked
  (the drop is conditional on membership, so an untracked on-disk artifact is still removable).
  Never `move_file`/`rmdir`/recursive delete (out of scope). (Additive tool added in iter-33 —
  existing tool contracts unchanged, so **no version bump**, mirroring iter-13's
  `search_files`.) Unknown tool →
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
  - `pla scan --workspace W [--out slate.json] [--format {table,json,markdown,csv}]
    [--top N]` —
    collect → synthesize → gate → render the ranked slate + gate decisions to
    stdout; write slate JSON. `--format` (default `table`, backward compatible)
    selects stdout rendering ONLY and never changes the persisted slate file:
    `table` = the human plain-text table + a `slate written: <path>` trailer (a
    bare `scan` is byte-identical to `--format table`); `json` = one JSON object on
    stdout (`{workspace_root, goals[...]}`, goals in `ranked()` order, each with the
    live gate `decision`/`reason`) and NO trailer, so it pipes cleanly into `jq`;
    `markdown` = a paste-ready GitHub-flavored table (`| # | decision | score |
    category | title |`) plus the same trailer. `csv` = an RFC-4180 data stream via
    the stdlib `csv` module (`QUOTE_MINIMAL`), a header row `rank,decision,score,
    category,title` then one row per ranked goal (score `:.2f`, enums as `.value`,
    title verbatim so a comma/quote/newline round-trips), with NO `slate written:`
    trailer and NO truncation note like `json` (the whole stdout is one CSV document
    for `pandas.read_csv`/a spreadsheet); an empty slate emits the header row only,
    and `--top` caps the emitted rows while `_write_slate` still persists the complete
    slate. An invalid `--format` is an argparse usage error (exit 2). `--top N` (default: all) caps the STDOUT rendering to the
    N highest-ranked goals UNIFORMLY across all four formats — stdout is a VIEW,
    the persisted slate file is always the COMPLETE record (`_write_slate` writes
    all goals regardless of `--top`), so every downstream verb still operates on the
    full slate. `--top` never re-orders (it slices the existing `ranked()` order);
    for `table`/`markdown` a `... showing top N of M` note prints after the rows and
    before the trailer ONLY when `N < M` (a cap hiding nothing is byte-identical to
    no flag); `json` stays a pure single `{workspace_root, goals}` object and `csv`
    stays a pure header-plus-rows CSV document, both with no note/trailer and only a
    shortened row set (no count key/row added). A
    non-positive or non-integer `--top` (`0`, `-1`, `abc`) is an argparse usage
    error (exit 2) at PARSE time, before any client/collect/slate-write. A missing
    or non-directory `--workspace` fails fast with
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
    `--json` emits one object of exactly the 12 keys `id, title, category, score,
    score_components{impact,urgency,confidence,effort_weight}, auto_dispatch_threshold,
    decision, reason, appropriate_now, rationale, sources, suggested_first_steps` —
    built from an explicit allowlist (never `model_dump`; the iter-08 schema-leak
    discipline), with `category`/`decision` as their str-Enum `.value`, `score`
    echoing the computed field, and `sources`/`suggested_first_steps` as JSON arrays
    (`[]` when empty, not the human `(none)` marker), so it pipes cleanly into `jq`.
    Missing slate or unknown id → exit 2; a corrupt slate → exit 1 via the
    `main()` boundary (all before any rendering, so the exit contract is
    `--json`-independent). Builds no `LLMClient`.
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
  - `pla watch --workspace W [--interval S] [--max-scans N]` — the proactive
    watch loop: re-run the SAME `scan` pipeline (collect → synthesize → gate →
    render the ranked slate + gate decisions to stdout) every `--interval`
    seconds via `scheduler.run_periodic`, prefixing each tick with a
    `=== scan <n> ===` header (1-based). `--interval` is a float, default `3600.0`,
    validated **finite and non-negative at parse time** (`>= 0`; `0` stays legal so offline
    tests can drive `watch` with a bounded `--max-scans` and no real wait);
    `--max-scans` is a **positive int** (`>= 1`), default `None` = run forever
    (production "watch until Ctrl-C"), a positive int bounds the run for
    tests/one-offs. A non-finite (`nan`/`inf`), negative, or non-numeric `--interval` or a zero/negative/
    non-integer `--max-scans` is an argparse usage error (exit 2) BEFORE any
    client/collect/render — matching the `--top` parse-time-guard clause, so the
    namesake loop can neither half-run then leak `time.sleep`'s builtin errno
    string nor silently no-op with exit 0. Unlike `scan` it is
    a LIVE monitor: it writes NO slate file and prints no `slate written:` trailer
    (a tick's output is ephemeral, not an artifact). The LLM client is built ONCE
    before the loop and reused every tick. A missing/non-directory `--workspace`
    fails fast with `error: workspace not found: <path>` on stderr + exit 2 (the
    verbatim iter-10 guard, before any client/collect and before consuming a
    scripted response). Explicitly returns 0 (never `run_periodic`'s scan count).
    No `--out`/`--format`; no slate-file writing (that is `scan`'s job).
  - `pla diff --old A.json --new B.json [--json]` — read-only, LLM-free
    slate-delta inspector: the comparative companion to `watch`, turning a stream
    of point-in-time slates into a change feed (every other saved artifact already
    has a viewer — `runs`/`trace`/`explain`/`signals` — but the slate itself had no
    *comparative* one). It matches goals across the two saved slates by NORMALIZED
    TITLE (`title.strip().lower()` — the synthesizer's own dedup key, NEVER the
    random per-scan `CandidateGoal.id`, which would report every goal as both added
    and removed each scan; within one slate first-occurrence-wins on a duplicate
    title), re-gates each side LIVE with the SAME `gate(goal, settings)` (via the
    shared `_settings(args)` seam, so a decision flip reflects the goal's OWN
    score/appropriateness/category change, not a settings change — proving it
    re-gates rather than comparing stored decisions, which a slate does not persist),
    and classifies each goal as **added** (title in NEW only), **removed** (in OLD
    only), **changed** (in BOTH, with `abs(new_score - old_score) > 1e-9` OR a
    flipped gate decision), or **unchanged** (count only). Human form prints only
    the non-empty `+ added (N)` / `- removed (N)` / `~ changed (N)` sections (rows
    title-ascending; `<title>` un-normalized, from NEW for added/changed and OLD for
    removed; scores `:.2f`; decisions as the gate `.value`) then ALWAYS an
    `unchanged: <N>` trailer, degrading to the single `(no differences)` line when
    the three delta buckets are empty. `--json` emits one object of EXACTLY six
    top-level keys `old, new, added, removed, changed, unchanged_count` — an explicit
    allowlist (never `model_dump`; the iter-08 schema-leak discipline): `old`/`new`
    echo the path strings as passed, the three arrays are ALWAYS present (`[]` when
    empty, not the human marker) and title-ascending, `added`/`removed` items are
    `{title, score, decision}` and `changed` items are `{title, old_score, new_score,
    old_decision, new_decision}` with scores as raw numbers and decisions as `.value`.
    A missing/non-file `--old` (checked FIRST) or `--new` → `error: slate file not
    found: <path>` on stderr + exit 2; a corrupt/schema-invalid slate → exit 1 via
    the `main()` boundary (both before any rendering, so the exit contract is
    `--json`-independent). Builds no `LLMClient`, runs no collector/subprocess, and
    writes no file.
  - `pla policy [--json]` — read-only, LLM-free, zero-input catalog of the STANDING
    autonomy contract itself: the product's headline safety mechanism, surfaced
    PROACTIVELY rather than only reactively through a gated `scan`/`explain` (both of
    which need a synthesized slate). Takes NO `--workspace` (the contract is
    context-free) and builds no `LLMClient` (an inert/nonexistent `--scripted-responses`
    is never opened → exit 0, unlike a client-building verb's eager-load exit 1), runs
    no collector, and touches no filesystem — so it structurally cannot regress any
    existing behavior. It resolves `settings` through the shared `_settings(args)` seam
    so a `PLA_AUTO_DISPATCH_MIN_SCORE` override shows the EFFECTIVE threshold. Human form
    prints the threshold (`:.2f`, e.g. `4.00`), every `GoalCategory` `.value` (one line
    each, sorted, driven from `list(GoalCategory)` so a future category cannot drop out)
    with a `(sensitive)` annotation on the sensitive ones only, and the four ordered
    `policy.gate` rules (first match wins). `--json` emits one object of EXACTLY the four
    keys `auto_dispatch_min_score, sensitive_categories, categories, rules` — an explicit
    allowlist (never `model_dump`; the iter-08 schema-leak discipline): `categories` is a
    sorted list of `{category, sensitive}`, `sensitive_categories` a sorted list of
    enum `.value` strings, `auto_dispatch_min_score` the raw resolved number, and `rules`
    a four-element ordered narration of the gate branches (the one small hand-maintained
    doc-vs-code coupling; only the category/threshold/sensitive parts are source-driven).
    Always exits 0 (no input to fail on). It is the top of the decision arc policy (the
    rules) → scan (proposals) → explain (why THIS goal) → trace (what a run did).
  - Global flags: `--provider`, `--scripted-responses`, `--state-dir`, `-v`/`--verbose`
    (repeatable `count`: absent -> silent, `-v` -> INFO, `-vv` -> DEBUG; configures the
    `proactive_loop` package logger once via a single guarded `StreamHandler(sys.stderr)`,
    so the L0 retry/backoff self-healing is visible on stderr as it happens while stdout
    stays untouched -- level 0 is a strict no-op).
  - `_collect(workspace) -> WorkspaceSnapshot` — the shared collector-orchestration
    seam behind `scan`/`run`/`signals`/`watch`. It ENFORCES the §4.1 "collectors
    never raise → `[]`" invariant (belt-and-suspenders over the per-collector
    contract): each `collect()` is isolated in a `try/except Exception`, so one
    collector that raises is logged at WARNING (naming its `name`) and contributes
    `[]` while the surviving collectors' signals are preserved — a buggy collector
    degrades the scan, never aborts it.
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
- `SecretFileCollector` is **basename/metadata-only**: it never opens file content, does no entropy/regex content scan, and has no `.gitignore`/git-lfs awareness (out of scope — this hard line keeps it binary-safe and prevents it from becoming the vetoed iter-31 content scanner).
