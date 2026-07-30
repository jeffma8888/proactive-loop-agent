# Enhancement Roadmap

A maturity/enhancement backlog layered on the shipped **v0.1.1**, grounded in
[`SPEC.md`](SPEC.md). The product is already complete and tested (~115 tests
green); everything here is a small, self-contained increment that raises the
bar of an existing layer — L2 scout perception, L1 loop execution, L0
resilience/observability, or CLI/DX — without breaking the public contracts.
Each iteration of the dev loop selects exactly one row.

Ordering is by leverage on the product's thesis ("a proactivity layer that is
resilient by design"), balanced against blast radius. Seeded from both PM
scouts (new-capability lens + hardening/DX lens) and a fresh read of `SPEC.md`.

| # | Enhancement | Layer | Value | Risk | Source | Status |
|---|-------------|-------|-------|------|--------|--------|
| 1 | **Retry-wrap the L2 `synthesize` call** so `pla scan`/`pla run` survive a transient throttle/timeout the same way a dispatched goal does (makes README's "wraps *every* model call" literally true) | L0×L2 | High | Low | Scout B C1 | **SELECTED — iter-01** |
| 2 | `DependencyCollector` — new L2 signal that reads project manifests (`pyproject.toml`/`package.json`/…) so the scout proposes stack-appropriate goals | L2 | High | Low | Scout A C1 | Planned |
| 3 | Surface L0 retry telemetry into `RunState` + the run summary (wire the defined-but-unused `on_retry` hook) so self-healing is visible | L0×L1 | Med-High | Low | Scout B C2 | Planned (pairs with #1) |
| 4 | Read-only `search_files(query, path)` sandbox tool for the L1 loop so it can *discover* code in a real workspace, not just read known paths | L1 | Med | Low-Med | Scout A C2 | Planned |
| 5 | `pla scan --format {table,json,markdown}` — pipeable/shareable slate output (default `table`, backward compatible) | CLI/DX | Med | Very Low | Scout A C3 | Planned |
| 6 | Wire the already-declared `pytest-cov` into a `make cov` target + `[tool.coverage]` config (dead dev-dep → visible quality signal) | DX | Low-Med | Very Low | Scout B C3 | Planned |
| 7 | Ship a PEP 561 `src/proactive_loop/py.typed` marker so the fully type-hinted library exports as typed to downstream consumers | DX | Low | Very Low | Scout B C3 sibling | Planned |
| 8 | Collectors robustness audit — a per-collector regression test that proves the SPEC §4.1 "never raises, degrade to `[]`" invariant on a hostile/missing input | L2/quality | Low-Med | Very Low | PM-lead (SPEC read) | Planned |
| 9 | `pla scan --top N` to cap the printed slate for large workspaces (JSON write unchanged) | CLI/DX | Low | Very Low | PM-lead (SPEC read) | Planned |
| 10 | README section documenting the lazy-imported provider adapters (anthropic/openai/bedrock) with an env-var example, so the offline-vs-live seam is discoverable | Docs | Low | None | PM-lead (SPEC read) | Planned |

_Roadmap owned by the PM-lead role; updated each iteration (mark shipped, re-order on learnings)._
