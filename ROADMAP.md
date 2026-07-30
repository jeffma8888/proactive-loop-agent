# Enhancement Roadmap

A maturity/enhancement backlog layered on the shipped **v0.1.1**, grounded in
[`SPEC.md`](SPEC.md). The product is already complete and tested (over 120 tests
green, grown with iter-01); everything here is a small, self-contained increment
that raises the bar of an existing layer — L2 scout perception, L1 loop
execution, L0 resilience/observability, or CLI/DX — without breaking the public
contracts. Each iteration of the dev loop selects exactly one row.

Ordering is by leverage on the product's thesis ("a proactivity layer that is
resilient by design"), balanced against blast radius. Seeded from both PM scouts
(new-capability lens + hardening/DX lens) across iters 01–02 and a fresh read of
`SPEC.md`.

| # | Enhancement | Layer | Value | Risk | Source | Status |
|---|-------------|-------|-------|------|--------|--------|
| 1 | **Retry-wrap the L2 `synthesize` call** so `pla scan`/`pla run` survive a transient throttle/timeout the same way a dispatched goal does | L0×L2 | High | Low | Scout B C1 (iter-01) | **SHIPPED — iter-01** (`172d38f`) |
| 2 | **Top-level CLI error boundary in `main()`** — map foreseeable operator/environment faults (persistent throttle, bad `--provider`, missing/malformed scripted file, corrupted slate JSON) to a single `error: <msg>` line + exit 1 instead of a raw traceback. Direct follow-through to #1, which opened the persistent-throttle escape path | CLI/L0 | High | Low | Scout B C1 (iter-02) | **SELECTED — iter-02** |
| 3 | `pla explain --slate --goal-id` — print the score arithmetic + which gate rule fired + sources, making the autonomy contract auditable | CLI/L2 | High | Low | Scout A C1 (iter-02) | Planned (best after #2: crash-safe first) |
| 4 | GitHub Actions CI (`uv sync` + `uv run pytest` + `make demo`) + a "tests passing" README badge — first trust signal on a public repo; machine-verifies every future loop commit | DX/CI | High | Very Low | Scout B C2 (iter-02) | Planned |
| 5 | `DependencyCollector` — new L2 signal reading project manifests (`pyproject.toml`/`package.json`/…) so the scout proposes stack-appropriate goals | L2 | High | Low | Scout A C1 (iter-01) | Planned |
| 6 | Surface L0 retry telemetry into `RunState` + the run summary (wire the defined-but-unused `on_retry` hook) so self-healing is visible | L0×L1 | Med-High | Low | Scout B C2 (iter-01) | Planned (pairs with #1) |
| 7 | `pla --version` + a version-consistency guard test; also fix the stale `SPEC.md §2` `__version__ = "0.1.0"` comment (code is `0.1.1`) | CLI/DX | Med | Very Low | Scout B C3 (iter-02) | Planned |
| 8 | `WorkingTreeCollector` — new L2 signal for uncommitted/unpushed git work (`git status --porcelain`, `@{u}..HEAD`); complements `git_activity` (present vs. past) | L2 | Med | Low | Scout A C2 (iter-02) | Planned |
| 9 | Read-only `search_files(query, path)` sandbox tool for the L1 loop so it can *discover* code in a real workspace, not just read known paths | L1 | Med | Low-Med | Scout A C2 (iter-01) | Planned |
| 10 | `append_file(path, content)` sandbox tool — first-class incremental artifact authoring across loop iterations (vs. read-then-rewrite) | L1 | Med | Low | Scout A C3 (iter-02) | Planned |
| 11 | `pla scan --format {table,json,markdown}` — pipeable/shareable slate output (default `table`, backward compatible) | CLI/DX | Med | Very Low | Scout A C3 (iter-01) | Planned |
| 12 | Collectors robustness audit — a per-collector regression test that proves the SPEC §4.1 "never raises, degrade to `[]`" invariant on a hostile/missing input | L2/quality | Low-Med | Very Low | PM-lead (SPEC read) | Planned |
| 13 | Wire the already-declared `pytest-cov` into a `make cov` target + `[tool.coverage]` config (dead dev-dep → visible quality signal) | DX | Low-Med | Very Low | Scout B C3 (iter-01) | Planned |
| 14 | Ship a PEP 561 `src/proactive_loop/py.typed` marker so the fully type-hinted library exports as typed to downstream consumers | DX | Low | Very Low | Scout B C3 sibling | Planned |
| 15 | `pla scan --top N` to cap the printed slate for large workspaces (JSON write unchanged) | CLI/DX | Low | Very Low | PM-lead (SPEC read) | Planned |
| 16 | README section documenting the lazy-imported provider adapters (anthropic/openai/bedrock) with an env-var example | Docs | Low | None | PM-lead (SPEC read) | Planned |

_Roadmap owned by the PM-lead role; updated each iteration (mark shipped, re-order on learnings)._
