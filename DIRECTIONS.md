# Foundry directions

foundry directions -- proactive-loop-agent
  iter-111
    lenses: SIMPLIFICATION-AND-DELETION, PERFORMANCE-AND-THROUGHPUT
    - Candidate A1 -- Compact `SPEC.md` (90,573 chars) into an index + `SPEC_ARCHIVE.md`, and add the missing char-budget guard (roadmap row 109, QUEUED)
    - Candidate A2 -- Delete the verb-count magic number `15`, now pinned in 18 test modules
    - Candidate A3 -- Delete the verbatim second copy of `_has_source` and the third copy of the source-extension set (roadmap row 125, QUEUED)
    - Candidate B1 -- Make `--kind` an UPSTREAM collector allowlist, not a display-only post-filter
    - Candidate B2 -- Bound the WORK of the two collect-all-then-cap whole-tree collectors, not just their OUTPUT
    - Candidate B3 -- Cost visibility where the loop actually runs: `--timings` on `scan` (and the `watch` tick), not only on `signals`
    winner: B1
    ship: unknown
  iter-110
    lenses: integration-and-adoption, simplification-and-deletion
    winner: A1
    ship: PUSHED 193ac4d
  iter-109
    lenses: HARDENING / DX, INTEGRATION AND ADOPTION
    winner: unknown
    ship: PUSHED b83621f
  iter-108
    lenses: NEW CAPABILITY, HARDENING / DX
    - Candidates I checked and DROPPED (recorded so they are not re-proposed)
    winner: B1
    ship: PUSHED f5212e2
  iter-107
    lenses: narrative-and-docs (iteration 107), new-capability (iteration 107)
    - Candidate A1 -- SHOW the flagship output: an annotated `make demo` transcript in the README, asserted against a real run
    - Candidate A2 -- Un-cram the CLI reference: one table cell is 851 characters, and the drift guard actively rewards that
    - Candidate A3 -- Document the CLI exit-code contract (roadmap row #115, QUEUED): `dispatch` returns 3 vs 4 and the README says neither
    - Candidate B1 -- Make `proactive_loop` importable: root-package public API (roadmap row #116, QUEUED)
    - Candidate B2 -- `DebugArtifactCollector`: the 17th L2 collector (roadmap row #105, ABANDONED, explicitly re-proposable)
    - Candidate B3 -- `pla watch --json`: make the namesake proactive loop machine-consumable
    winner: B1
    ship: PUSHED 2bd44f7
  iter-106
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- Bounded worst case: sort-then-stop in the three relpath-capped body-reading collectors
    - Candidate A2 -- Push `--kind` upstream: run only the collector that can emit the requested kind
    - Candidate A3 -- Halve `working_tree`'s git spawns: one `status --porcelain --branch` instead of two commands
    - Candidate B1 -- The ACT-sandbox tool allowlist is mis-described, and the error understates MUTATION
    - Candidate B2 -- The perception vocabulary (16 collectors, 16 kinds) is documented nowhere, yet a wrong kind is now a hard exit 2
    - Candidate B3 -- The CLI reference is collapsing into mega-cells, and the drift guard rewards it
    winner: B1
    ship: PUSHED 1b4e265
  iter-105
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Collapse the three copies of the collector directory-skip seam
    - Candidate A2 -- Delete the magic number `15` from six test modules; derive the verb count
    - Candidate A3 -- Extract the duplicated capped file read in the text collectors
    - Candidate B1 -- Make scan cost VISIBLE: per-collector timings
    - Candidate B2 -- Deduplicate the 333 redundant file reads (share BYTES, not text)
    - Candidate B3 -- Deterministic early-exit for the relpath-capped collectors
    winner: B1
    ship: PUSHED bfbfe61
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
20 scouted iterations
