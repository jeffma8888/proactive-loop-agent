# Foundry directions

foundry directions -- proactive-loop-agent
  iter-135
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- finish row #165: fold the 3 remaining inline relative-path idioms onto `BaseCollector._relative` (and correct the row's false premise)
    - Candidate A2 -- collapse the three near-duplicate path-target guards into one parameterized guard
    - Candidate A3 -- table-drive the five static-info `_cmd_*` handlers
    - Candidate B1 -- Parallelize the suite: `pytest-xdist` + `-n auto` in `addopts`
    - Candidate B2 -- The `todos` cold-scan prefilter (roadmap row #129, already QUEUED with a settled shape)
    - Candidate B3 -- Cut the fresh-process startup tax on the CLI critical path
    winner: B1
    ship: unknown
  iter-134
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- Put the `watch` -> `diff` change feed inside the graded gate (roadmap row #137, gate-step half)
    - Candidate A2 -- Give `signals --baseline` its first consumer: commit a one-entry baseline and arm `ci_config` (roadmap row #161)
    - Candidate A3 -- Make the shipped `hooks/pre-commit` something a person would keep installed: quiet on success, plus a `make hooks` on-ramp
    - Candidate B1 -- Delete 5 of the 6 verbatim `_relative` copies by inheriting one from `BaseCollector`
    - Candidate B2 -- Collapse the "root + direct children" repo walk that four collectors each hand-maintain
    - Candidate B3 -- Fold the 3 identical OpenAI-wire `_complete` closures into the `_SdkAdapter` seam that already exists
    winner: B1
    ship: PUSHED e368632
  iter-133
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- Make the README suite-size guard prove the floor, and bump the 511-test-stale number
    - Candidate A2 -- Row #155: the root-Markdown table guard audits the WORKING DIR, not the tracked set
    - Candidate A3 -- Retire the tautology in the iter-73 reference oracle (premise CORRECTED, value lower than reported)
    - Candidate B1 -- Wire the `watch --out-dir` -> `diff --dir` change feed into the graded gate (row #137)
    - Candidate B2 -- Give `--baseline` its first consumer: commit a baseline and arm `ci_config`, the one of three "red on arrival" kinds measurement says is safe
    - Candidate B3 -- Ship the pre-commit hook the README already sells (the missing half of the exit-5 claim)
    winner: B3
    ship: PUSHED 86a0d7f
  iter-132
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `signals --path GLOB`, the positive half of the location axis
    - Candidate A2 -- `signals --baseline FILE` also reports what was RESOLVED
    - Candidate A3 -- `PythonVersionDriftCollector` (`kind="python_version_drift"`), the 17th collector
    - Candidate B1 -- Normalize `ContextSignal.path` to ONE namespace at the publication seam
    - Candidate B2 -- Root-Markdown table guard keys on the git-TRACKED set, not the working dir (row #155)
    - Candidate B3 -- Compact `ROADMAP.md` under its operator budget and ratchet it with a size guard (rows #138 + #109)
    winner: B1
    ship: PUSHED a7be482
  iter-131
    lenses: narrative-and-docs, NEW CAPABILITY
    - Candidate A1 -- the guard named "every root markdown file" audits the WORKING DIRECTORY, not the repo, and the roadmap row describing it names two files a fresh clone does not have
    - Candidate A2 -- the four shipped caching mechanisms are documented nowhere a reader looks, and the library and CLI entry points differ in a way no artifact records
    - Candidate A3 -- two collector docstrings publish absolute millisecond breakdowns that iter-136 invalidated, one of them undated
    winner: B1
    ship: PUSHED 59c4032
  iter-130
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- collapse `working_tree`'s 2 git spawns into 1 via `git status --porcelain --branch`
    - Candidate A2 -- (in progress: suite wall-clock / repeatedly-paid cost) -- see refinement
    - Candidate A3 -- (in progress) -- see refinement
    - Candidate B1 -- the README Quickstart never names `make check`, the one command that reproduces the public gate
    - Candidate B2 -- README declares the NARROWER of the two exit-code surfaces canonical
    - Candidate B3 -- three shipped caching mechanisms are documented nowhere a reader will look
    winner: A1
    ship: unknown
  iter-129
    lenses: simplification-and-deletion, performance-and-throughput (iteration 129)
    - Candidate A1 -- collapse the two copy-pasted content-digest memoizers into one shared bounded memo
    - Candidate A2 -- delete the two shadow copies of the directory-skip policy (a proven drift, currently masked)
    - Candidate A3 -- replace the three sibling path guards with the one general rule
    - Candidate B1 (primary) -- read each file ONCE per scan: a shared text+digest provider for the three content collectors
    - Candidate B2 -- close the one-shot hole: an opt-in cross-invocation cache for the parse verdict
    - Candidate B3 -- stop re-spawning `git log`: memoize `git_activity` on the resolved HEAD sha
    winner: B1
    ship: PUSHED 0d00b5d
  iter-128
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- make the bundled example script drive a real 2-tick `watch`, so the stream -> `diff` change feed has a runnable on-ramp
    - Candidate A2 -- `scan --json` as the scripting-parity alias for `--format json`
    - Candidate A3 -- `signals --baseline FILE`: the adoption ratchet the shipped exit-5 gate needs (roadmap row #150)
    - Candidate B1 -- Collapse the 3 structurally IDENTICAL OpenAI-shaped provider factories into one parameterized builder
    - Candidate B2 -- Replace `create_client`'s 7-arm if/elif chain with the data-driven map its own docstring already claims exists
    - Candidate B3 -- Extract the twice-copied ancestor walk out of the CLI path guards, and delete the paragraph explaining why they could not be shared
    winner: A1
    ship: PUSHED 9363fae
  iter-127
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- Finish the atomic-write idiom: `Checkpoint.save` temp cleanup + the `meta.json` writer
    - Candidate A2 -- Close the last deferred mypy ratchet: flip `disallow_any_generics` and annotate the 35 `type-arg` sites
    - Candidate A3 -- Oracle the 2 unguarded `_out_dir_guard` messages
    - Candidate B1 -- Put the `watch --out-dir` -> `diff --dir` change feed inside the graded gate (roadmap row #137), prerequisite discharged by execution
    - Candidate B2 -- Make the demo-artifact gate assertions dogfood the product's own listing verb
    - Candidate B3 -- `pla runs --json` cannot be ordered: no consumer can tell which run is newest
    winner: A1
    ship: PUSHED 4e48072
  iter-126
    lenses: NEW CAPABILITY, hardening/DX
    - Candidate A1 -- `signals --baseline FILE`: turn the exit-5 gate from "no findings" into "no NEW findings"
    - Candidate A2 -- 17th collector: `DebugArtifactCollector` (`kind="debug_artifact"`), re-proposed with a new premise
    - Candidate A3 -- user-tunable per-kind perception weights (`PLA_KIND_WEIGHTS="license=2,todo=0.5"`)
    - Candidate B1 -- Repair `ROADMAP_ARCHIVE.md`'s broken table, whose two defects must be fixed in ONE commit
    - Candidate B2 -- Close the atomic-write asymmetry: `Checkpoint.save` lacks the `try/finally` its own documented twin has
    - Candidate B3 -- Oracle the 2 unguarded `--out-dir` path-guard messages
    winner: B1
    ship: PUSHED ebc4ff3
  iter-125
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- the published suite-size floor is stale AND the guard cannot tell truth from fiction
    - Candidate A2 -- guard-then-fix the 30 in-table blank lines that break `ROADMAP_ARCHIVE.md` rendering
    - Candidate A3 -- the repo ships an unexplained, unlinked decision log; link it from the README behind a link-integrity guard
    - Candidate B1 -- `signals --exclude-path GLOB`: the product has no way to scope perception by LOCATION
    - Candidate B2 -- `PythonVersionDriftCollector` (roadmap row #122): the 17th collector, and only the 2nd RELATIONAL one
    - Candidate B3 -- `signals --baseline <file>`: report only findings NOT present in a saved baseline
    winner: B1
    ship: PUSHED 808eb16
  iter-124
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- sound file-level prefilter before the todos per-line regex loop (+18.78 ms, 35% of that pass)
    - Candidate A2 -- stop decoding the same .py file two-to-three times per scan (~34 ms redundant, ~7% of the scan)
    - Candidate A3 -- cut the graded gate's own wall-clock: measure and fix the slowest tests
    - Candidate B1 -- guard-then-fix the 30 confirmed in-table blank lines breaking `ROADMAP_ARCHIVE.md`
    - Candidate B2 -- publish the run-dir artifact layout, guarded against cli.py's 4 filename constants
    - Candidate B3 -- make the published suite-size floor self-correcting instead of silently rotting
    winner: B2
    ship: PUSHED d8ed387
  iter-123
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- collapse the three divergent copies of the noise-directory vocabulary into one
    - Candidate A2 -- host the pruned `os.walk` preamble once instead of eleven hand-copies
    - Candidate A3 -- replace the five copy-pasted read-only inspector handlers with one table-driven rule
    - Candidate B1 -- extend the proven digest memo to the two remaining content scanners
    - Candidate B2 -- collapse the two `working_tree` git invocations into one porcelain-v2 call
    - Candidate B3 -- persist the digest->verdict memo so a one-shot scan stops re-parsing
    winner: B1
    ship: PUSHED 1a80355
  iter-122
    lenses: integration-and-adoption, simplification-and-deletion (iteration 122)
    - Candidate A1 -- Ship the pre-commit hook on-ramp the exit-5 gate advertises ten times and never provides
    - Candidate A2 -- `pla scan --out-dir DIR`: give the advertised change feed a producer that is not `watch`
    - Candidate A3 -- Make the graded gate consume the change feed (roadmap row #137), prerequisite discharged in the same commit
    - Candidate B1 -- Host the fail-open `collect()` wrapper once in `base.py`, delete 16 hand-rolled copies
    - Candidate B2 -- One shared bounded walk; retire the 9 private cross-module `_SKIP_DIRS`/`_is_hidden` imports
    - Candidate B3 -- One reader-resolution rule in the sandbox `ToolRegistry`
    winner: B1
    ship: PUSHED 5393347
  iter-121
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- Char-size budget guard for ROADMAP.md (roadmap row #138), with a measured ~2-iteration runway
    - Candidate A2 -- Finish the atomic-write idiom: `Checkpoint.save` temp cleanup + the `meta.json` writer (roadmap row #134)
    - Candidate A3 -- Adopt warnings-as-errors in the pytest config, measured at ZERO fallout
    - Candidate B1 -- Dogfood the enforcement gate: make the repo's own graded gate the first consumer of `signals --fail-on-kind` (exit 5)
    - Candidate B2 -- Close the demo round-trip: prove the gate's own artifacts are readable by the three consumer verbs
    - Candidate B3 -- Oracle the install-time on-ramp: the `pla` console script and the `py.typed` marker (roadmap row #117, with a measured correction)
    winner: B1
    ship: PUSHED 6af2321
  iter-120
    lenses: NEW-CAPABILITY (iteration 120), HARDENING / DX (iteration 120)
    - Candidate A1 -- 17th collector: `PythonVersionDriftCollector` (kind `python_version_drift`)
    - Candidate A2 -- `signals --fail-on-kind K`: let a detection FAIL a build (the first enforcement mode)
    - Candidate A3 -- `pla doctor`: an offline preflight that turns settings into verdicts
    - Candidate B1 -- registry-driven `--json` purity oracle over all 10 `--json` verbs, fail-closed on verb 11
    - Candidate B2 -- finish the atomic-write idiom: `Checkpoint.save` temp cleanup + an atomic `meta.json` (roadmap row #134)
    - Candidate B3 -- oracle the packaging contract: `[project.scripts] pla` must resolve to a real callable (checkable half of roadmap row #117)
    winner: A2
    ship: PUSHED ac917e6
  iter-119
    lenses: narrative-and-docs (iteration 119), new-capability (iteration 119)
    - Candidate A1 -- Bump the README intro's stale test floor (published 2,200+, live 2,719) and give the floor a real oracle
    - Candidate A2 -- A committed DECISIONS record for the load-bearing "why" that currently exists nowhere in the repo
    - Candidate A3 -- Fix ROADMAP.md's own stale self-description and oracle its archive-boundary claim
    - Candidate B1 -- `pla runs --prune`: the product's first state-dir lifecycle capability (roadmap row #123)
    - Candidate B2 -- `PythonVersionDriftCollector`: the 17th collector and only the 2nd RELATIONAL one (roadmap row #122)
    - Candidate B3 -- `pla trend --dir DIR`: turn a watch stream into goal persistence, not just a pairwise delta
    winner: B1
    ship: PUSHED 5d23443
  iter-118
    lenses: performance-and-throughput, narrative-and-docs
    winner: B1
    ship: PUSHED c1d1a37
  iter-117
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Collapse the 16 hand-copied never-raises `collect()` wrappers into one typed decorator
    - Candidate A2 -- Delete the duplicated `_has_source` walk and single-source the code-extension set (roadmap row #125, with a premise correction)
    - Candidate A3 -- Collapse the three AST-identical OpenAI-shaped provider branches into one parameterized factory
    - Candidate B1 -- content-digest parse memo so a watch tick never re-parses unchanged source (roadmap row #130, with the blocking premise corrected)
    - Candidate B2 -- one shared pruned tree walk for the three hottest file-scanning collectors
    - Candidate B3 -- phase-level cost attribution for a scan/watch tick
    winner: B1
    ship: PUSHED 385a840
  iter-116
    lenses: integration-and-adoption (iteration 116), simplification-and-deletion
    - Candidate A1 -- `pla diff --dir DIR`: let `diff` consume the slate stream `watch` produces
    - Candidate A2 -- put the `watch` -> `diff` change feed inside the graded gate (`make check` + CI)
    - Candidate A3 -- `pla completion bash`: parser-derived shell completion for a 15-verb CLI
    - Candidate B1 -- collapse the 3 near-duplicate CLI path guards into one general rule
    - Candidate B2 -- delete the duplicated source-extension set + the verbatim second `_has_source` (row #125, widened)
    - Candidate B3 -- compact `ROADMAP.md` by archiving its oldest settled rows (with a data-loss trap I found)
    winner: A1
    ship: PUSHED f3abb5c
  iter-115
    lenses: hardening/DX) -- iteration 115, integration-and-adoption) -- iteration 115
    - Candidate A1 -- Make `_write_slate` atomic (tmp + `os.replace`), matching the checkpoint's own documented durability contract
    - Candidate A2 -- Warn on unrecognized `PLA_*` environment variables in `Settings.from_env`
    - Candidate A3 -- Re-pick row #121: close the deferred `disallow_any_generics` flag (35 `type-arg` sites + flip the flag)
    - Candidate B1 -- Teach `pla diff` to consume the watch slate stream: `--dir DIR` diffs the two newest `slate-NNN.json`
    - Candidate B2 -- Make the machine-readable spelling uniform: accept `--json` on `pla scan`
    - Candidate B3 -- An opt-in "findings mean non-zero" exit, so a neighbouring tool can gate on `pla`
    winner: A1
    ship: PUSHED 3559a67
  iter-114
    lenses: unknown
    - Candidate A1 -- `pla runs --prune --status STATUS`: the product's first persisted-state lifecycle capability
    - Candidate A2 -- `PythonVersionDriftCollector` (`kind="python_version_drift"`), the 17th collector
    - Candidate A3 -- teach the change feed to read the whole stream, not just two points
    - Candidate B1 -- Close the deferred `disallow_any_generics` ratchet: fix the 35 `type-arg` sites and flip the flag
    - Candidate B2 -- Make `pla watch` account for its ticks: a final summary line and a non-zero exit when every scan failed
    - Candidate B3 -- Char-budget guard for the per-iteration required-reading docs (`ROADMAP.md`, `SPEC.md`)
    winner: B1
    ship: unknown
  iter-113
    lenses: narrative-and-docs (iteration 113), new-capability (iteration 113)
    - Candidate A1 -- Bump the stale `2,200+` tests floor and give the floor a real oracle
    - Candidate A2 -- Publish the `run-<id>` state-dir layout, and fix the artifact path in the Quickstart
    - Candidate A3 -- Drift-guard the two prose provider lists against `VALID_PROVIDERS`
    - Candidate B1 -- `pla watch --out-dir DIR`: give the advertised watch -> diff change feed a producer
    - Candidate B2 -- `PythonVersionDriftCollector` (roadmap row #122): the 17th collector, 2nd relational one
    - Candidate B3 -- `pla runs --prune --status STATUS` (roadmap row #123): the first state-lifecycle capability
    winner: B1
    ship: PUSHED a34eb6c
  iter-112
    lenses: performance-and-throughput (iteration 112), narrative-and-docs (iteration 112)
    - Candidate A1 -- File-level cheap prefilter before the per-line regex loop in `todos`
    - Candidate A2 -- Per-scan shared decode of files read by more than one collector
    - Candidate A3 -- Memoize the syntax check by (path, st_mtime_ns, st_size) so `pla watch` ticks stop re-compiling an unchanged tree
    - Candidate B1 -- Make the "ten LLM-free verbs work on a bare `uv sync`" promise exact (7 standalone, 3 need a prior run)
    - Candidate B2 -- Publish the state-dir artifact layout, guarded against the four `cli.py` filename constants
    - Candidate B3 -- Fix the Quickstart install command: `uv sync` is published where the repo's own rule is `uv sync --locked`
    winner: B1
    ship: PUSHED 80955d8
  iter-111
    lenses: SIMPLIFICATION-AND-DELETION, PERFORMANCE-AND-THROUGHPUT
    - Candidate A1 -- Compact `SPEC.md` (90,573 chars) into an index + `SPEC_ARCHIVE.md`, and add the missing char-budget guard (roadmap row 109, QUEUED)
    - Candidate A2 -- Delete the verb-count magic number `15`, now pinned in 18 test modules
    - Candidate A3 -- Delete the verbatim second copy of `_has_source` and the third copy of the source-extension set (roadmap row 125, QUEUED)
    - Candidate B1 -- Make `--kind` an UPSTREAM collector allowlist, not a display-only post-filter
    - Candidate B2 -- Bound the WORK of the two collect-all-then-cap whole-tree collectors, not just their OUTPUT
    - Candidate B3 -- Cost visibility where the loop actually runs: `--timings` on `scan` (and the `watch` tick), not only on `signals`
    winner: B1
    ship: PUSHED a479e02
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
44 scouted iterations
