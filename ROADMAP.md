# Enhancement Roadmap

A maturity/enhancement backlog layered on the shipped **v0.1.1**, grounded in
[`SPEC.md`](SPEC.md). The product is already complete and tested (134 tests
green through iter-02); everything here is a small, self-contained increment
that raises the bar of an existing layer — L2 scout perception, L1 loop
execution, L0 resilience/observability, or CLI/DX — without breaking the public
contracts. Each iteration of the dev loop selects exactly one row.

Ordering is by leverage on the product's thesis ("a proactivity layer that is
resilient by design"), balanced against blast radius. Seeded from both PM scouts
(new-capability lens + hardening/DX lens) across iters 01–03 and a fresh read of
`SPEC.md`. Net-new rows (#17+) surfaced mid-loop by a scout may jump the queued
backlog when they close a docs-vs-code honesty gap on a public repo (the standing
iter-01 tie-break rule: an integrity fix outranks a net-new capability). Applied
iters 01, 03, and 05; iter-04 went net-new (`pla runs`) because no live 30s-
falsifiable contradiction existed that iteration.

| # | Enhancement | Layer | Value | Risk | Source | Status |
|---|-------------|-------|-------|------|--------|--------|
| 1 | **Retry-wrap the L2 `synthesize` call** so `pla scan`/`pla run` survive a transient throttle/timeout the same way a dispatched goal does | L0×L2 | High | Low | Scout B C1 (iter-01) | **SHIPPED — iter-01** (`172d38f`) |
| 2 | **Top-level CLI error boundary in `main()`** — map foreseeable operator/environment faults (persistent throttle, bad `--provider`, missing/malformed scripted file, corrupted slate JSON) to a single `error: <msg>` line + exit 1 instead of a raw traceback. Direct follow-through to #1, which opened the persistent-throttle escape path | CLI/L0 | High | Low | Scout B C1 (iter-02) | **SELECTED — iter-02** |
| 3 | `pla explain --slate --goal-id` — print the score arithmetic + which gate rule fired + sources, making the autonomy contract auditable | CLI/L2 | High | Low | Scout A C1 (iter-02) | Planned (best after #2: crash-safe first) |
| 4 | GitHub Actions CI (`uv sync` + `uv run pytest` + `make demo`) + a "tests passing" README badge — first trust signal on a public repo; machine-verifies every future loop commit | DX/CI | High | Very Low | Scout B C2 (iter-02) | Planned |
| 5 | `DependencyCollector` — new L2 signal reading project manifests (`pyproject.toml`/`package.json`/…) so the scout proposes stack-appropriate goals | L2 | High | Low | Scout A C1 (iter-01) | Planned |
| 6 | Surface L0 retry telemetry into `RunState` + the run summary (wire the defined-but-unused `on_retry` hook) so self-healing is visible | L0×L1 | Med-High | Low | Scout B C2 (iter-01) | Planned (pairs with #1) |
| 7 | `pla --version` + a version-consistency guard test; also fix the stale `SPEC.md §2` `__version__ = "0.1.0"` comment (code is `0.1.1`) | CLI/DX | Med | Very Low | Scout B C3 (iter-02) | **SELECTED — iter-05** (integrity tie-break: only live 30s-falsifiable docs-vs-code gap in the tree; ships `--version` + drift-guard, not a bare doc edit) |
| 8 | `WorkingTreeCollector` — new L2 signal for uncommitted/unpushed git work (`git status --porcelain`, `@{u}..HEAD`); complements `git_activity` (present vs. past) | L2 | Med | Low | Scout A C2 (iter-02) | Planned |
| 9 | Read-only `search_files(query, path)` sandbox tool for the L1 loop so it can *discover* code in a real workspace, not just read known paths | L1 | Med | Low-Med | Scout A C2 (iter-01) | Planned |
| 10 | `append_file(path, content)` sandbox tool — first-class incremental artifact authoring across loop iterations (vs. read-then-rewrite) | L1 | Med | Low | Scout A C3 (iter-02) | Planned |
| 11 | `pla scan --format {table,json,markdown}` — pipeable/shareable slate output (default `table`, backward compatible) | CLI/DX | Med | Very Low | Scout A C3 (iter-01) | Planned |
| 12 | Collectors robustness audit — a per-collector regression test that proves the SPEC §4.1 "never raises, degrade to `[]`" invariant on a hostile/missing input | L2/quality | Low-Med | Very Low | PM-lead (SPEC read) | Planned |
| 13 | Wire the already-declared `pytest-cov` into a `make cov` target + `[tool.coverage]` config (dead dev-dep → visible quality signal) | DX | Low-Med | Very Low | Scout B C3 (iter-01) | Planned |
| 14 | Ship a PEP 561 `src/proactive_loop/py.typed` marker so the fully type-hinted library exports as typed to downstream consumers | DX | Low | Very Low | Scout B C3 sibling | Planned |
| 15 | `pla scan --top N` to cap the printed slate for large workspaces (JSON write unchanged) | CLI/DX | Low | Very Low | PM-lead (SPEC read) | Planned |
| 16 | README section documenting the lazy-imported provider adapters (anthropic/openai/bedrock) with an env-var example | Docs | Low | None | PM-lead (SPEC read) | Planned |
| 17 | **Wire `PLA_RETRY_*` env vars into `Settings.from_env`** — the five `RetryPolicy` knobs (max_attempts, base_backoff_sec, backoff_factor, max_backoff_sec, jitter_frac) are the product's headline L0 resilience controls, yet `from_env` reads none of them while `config.py`'s docstring promises "everything overridable via PLA_*". Makes the claim true; purely additive (no path changes unless a new env var is set); pydantic validates ranges and bad values compose with iter-02's CLI error boundary | L0/config | High | Very Low | Scout B C1 (iter-03) | **SHIPPED — iter-03** (`d4fb593`; net-new, jumped queue on integrity grounds) |
| 18 | **`pla runs` — list & inspect past dispatched runs** (read-only CLI verb over `state_dir/run-*`; loads each `Checkpoint` + `meta.json`, prints a table of run id · status · iterations · #artifacts · goal, with `--json`). Makes the headline L0 resumable/checkpointed-run machinery legible and turns the advertised `resume --run-dir` from a hand-typed opaque path into a lookup. Zero-config, constructs NO `LLMClient` — the 2nd offline runnable command | CLI/L0×L1 | High | Low | Scout A C1 (iter-04) | **SELECTED — iter-04** (net-new) |
| 19 | **Adversarial regression suite for the ACT sandbox** — prove the documented `_within` symlink-escape defense in `tools.py` (currently zero symlink tests) + `list_files` traversal/absolute-path parity + hostile-input-never-crashes; test-only, skips cleanly where symlinks are unavailable. On a public repo a *proven* security boundary beats an asserted one; a refactor could silently delete the guard today and the suite stays green | L1/security | High | Very Low | Scout B C1 (iter-04) | Planned (net-new; strongest iter-04 alternative) |

_Roadmap owned by the PM-lead role; updated each iteration (mark shipped, re-order on learnings)._
