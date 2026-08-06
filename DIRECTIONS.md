# Foundry directions

foundry directions -- proactive-loop-agent
  iter-105
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Collapse the three copies of the collector directory-skip seam
    - Candidate A2 -- Delete the magic number `15` from six test modules; derive the verb count
    - Candidate A3 -- Extract the duplicated capped file read in the text collectors
    - Candidate B1 -- Make scan cost VISIBLE: per-collector timings
    - Candidate B2 -- Deduplicate the 333 redundant file reads (share BYTES, not text)
    - Candidate B3 -- Deterministic early-exit for the relpath-capped collectors
    winner: B1
    ship: unknown
  iter-104
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- Give the root package a public API: `__all__` re-exports + a README "Use as a library" section
    - Candidate A2 -- Publish each collector's emitted signal `kind` in `pla collectors` (+ `--kind` reverse lookup)
    - Candidate A3 -- Packaging-contract oracle: prove the installable artifact carries the `pla` entry point and the `py.typed` marker
    - Candidate B1 -- Delete the 2 divergent copies of `_SKIP_DIRS`/`_is_hidden`; one canonical definition + an AST single-definition guard
    - Candidates B2/B3 -- IN PROGRESS
    winner: A2
    ship: PUSHED b79c1aa
  iter-103
    lenses: HARDENING / DX, INTEGRATION AND ADOPTION
    winner: unknown
    ship: PUSHED 9cae927
  iter-102
    lenses: NEW CAPABILITY -- iteration 102, HARDENING / DX -- iteration 102
    winner: B2
    ship: PUSHED 407f3c0
  iter-101
    lenses: narrative-and-docs, new-capability
    winner: B1
    ship: PUSHED 268a588
  iter-100
    lenses: performance-and-throughput, narrative-and-docs
    winner: B1
    ship: PUSHED d3f97ec
  iter-99
    lenses: SIMPLIFICATION-AND-DELETION, performance-and-throughput
    winner: B1
    ship: PUSHED 83fa8e0
  iter-98
    lenses: NEW-CAPABILITY, HARDENING / DX
    winner: A1
    ship: unknown
  iter-97
    lenses: unknown
    winner: A1
    ship: PUSHED dc10934
  iter-96
    lenses: unknown
    - Candidates (3, deliberately cross-layer: L1 / L2 / CLI)
    - Candidates (3, one theme from two angles + a docs gap; all cheap, no tester-cap risk)
    winner: B1
    ship: PUSHED 52242cc
  iter-95
    lenses: unknown
    winner: B1
    ship: PUSHED 19ea19b
  iter-94
    lenses: unknown
    winner: A1
    ship: PUSHED 07d650f
  iter-93
    lenses: unknown
    - Candidate A1 -- `pla runs --summary` (per-status count rollup over past runs)
    - Candidate A2 -- `pla diff --only CLASS` (change-class filter on the change feed)
    - Candidate A3 -- `pla explain --summary` (per-gate-decision count rollup across a slate)
    - Candidate B1 -- `make setup` uses `uv sync --locked` (local/CI reproducibility parity)
    - Candidate B2 -- `make check` aggregate gate + a DRIFT-GUARD contract test (local CI parity)
    - Candidate B3 -- tighten the mypy oracle with the no-op-if-clean hygiene flags
    winner: B1
    ship: PUSHED 3e635f8
  iter-92
    lenses: NEW-CAPABILITY, HARDENING / DX
    - Candidate A1 — L2 collector: `PythonVersionDriftCollector`
    - Candidate A2 — CLI view: `pla signals --summary`
    - Candidate A3 — L1 ACT tool: `tail_file`
    - Candidate B1 — Tighten the mypy oracle: `warn_unused_ignores` + `warn_redundant_casts`
    - Candidate B2 — `make setup` should use `uv sync --locked` (match CI's env)
    - Candidate B3 — `make check`: one command that runs the full public gate locally
    winner: A2
    ship: PUSHED 1328d37
14 scouted iterations
