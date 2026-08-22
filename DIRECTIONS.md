# Foundry directions

foundry directions -- proactive-loop-agent
  iter-229
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- `broken_link` cannot see a link whose text is backticked, so the armed CI gate is fail-open on the idiom this repo's docs use 9 times
    - Candidate A2 -- Four git collectors render an EMPTY workspace label under `--workspace .`, the exact spelling `make check` and CI use, and that string is a `--baseline` identity key
    - Candidate A3 -- Row #205's own roster is STALE: 10 test modules sample `git status --porcelain`, not 7, and 2 of the unnamed ones are already safe
    - Candidate B1 -- The demo publishes its approval outcome and the consumer that reads that document ignores it
    - Candidate B2 -- Give `pla trend` its first producer->consumer pair: a bounded offline `watch --out-dir` stream
    - Candidate B3 -- `make hooks`: the shipped pre-commit gate is the one gate with no make verb
    winner: A1
    ship: pending (not yet decided)
  iter-228
    lenses: hardening/DX
    - Candidate A1 -- `pla run --suppress-title TITLE`: a declined goal can finally stop coming back
    - Candidate A2 -- `PythonVersionDriftCollector`: the 18th collector, and only the 2nd RELATIONAL one
    - Candidate A3 -- `--max-iterations N` / `--max-llm-calls N`: the L1 budget becomes SETTABLE
    - Candidate B1 -- `tests/conftest.py` strips the `PLA_*` namespace: the suite stops depending on the developer's shell
    - Candidate B2 -- packaging-declaration oracle: nothing reads `[project.scripts]`, so renaming `main` stays green
    - Candidate B3 -- `pla resume` names the file it cannot parse (the safe half of row #151)
    winner: B3
    ship: PUSHED 167ca51
  iter-227
    lenses: narrative-and-docs (iteration 227), new-capability
    - Candidate A1 -- README's exit-code section points readers at the one surface `python -OO` deletes
    - Candidate A2 -- SPEC.md's orientation map names 8 of the 15 tracked root entries, hiding all three machine gates
    - Candidate A3 -- seven test NAMES report a collector count the registry outgrew (15/16 vs a live 17)
    - Candidate B1 -- `run`/`dispatch --allow-tool NAME`: narrow the ACT sandbox for one dispatch
    - Candidate B2 -- `run --max-iterations N` / `--max-llm-calls N`: make the L1 budget SETTABLE, not just reportable
    - Candidate B3 -- `PythonVersionDriftCollector`: the 18th collector, and only the 2nd RELATIONAL one
    winner: A1
    ship: PUSHED 747c860
  iter-198
    lenses: new-capability (iteration 198)
    - Candidate A1 -- `dispatch --dry-run`: the first LLM-free rehearsal of one saved goal
    - Candidate A2 -- `PythonVersionDriftCollector`: the 18th collector, 3rd relational one
    - Candidate A3 -- `run` / `dispatch --allow-tool NAME`: narrow the ACT sandbox for one dispatch
    - Candidate B1 -- `resume` names the corrupt `meta.json` instead of leaking a bare decoder message
    - Candidate B2 -- a global `PLA_*` env scrub, so a developer's exported knob cannot red a clean checkout
    - Candidate B3 -- an oracle for the DECLARED console-script entry point, not the installed one
    winner: A1
    ship: PUSHED 561dc22
  iter-197
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- SPEC.md's orientation map names 8 of 15 tracked top-level entries, omitting all three machine gates
    - Candidate A2 -- the next line of the same block names 4 of 9 Makefile recipes
    - Candidate A3 -- the committed decision log denies four ships git can prove, and the README never glosses `ship: unknown`
    - Candidate B1 -- `pla trend --dir DIR`: which goals PERSIST across a watch stream
    - Candidate B2 -- `dispatch`/`run --allow-tool NAME`: narrow the ACT sandbox for one dispatch
    - Candidate B3 -- Per-category autonomy thresholds (`PLA_CATEGORY_MIN_SCORE=career:4.5,project:3.0`)
    winner: B1
    ship: PUSHED 4999dd9
  iter-196
    lenses: performance-and-throughput (iteration 196), narrative-and-docs
    - Candidate A1 -- Convert 2 more collectors onto the shared per-scan walk (dir_source)
    - Candidate A2 -- syntax_error dominates a scan and emits nothing on a healthy tree
    - Candidate A3 -- warm-tick cost of the perception layer (pla watch)
    - Candidate B1 -- Retire the three stale roster counts in `src/` prose and bind them to the registry
    - Candidate B2 -- Correct the one `src/` claim that contradicts both its cited module and the README
    - Candidate B3 -- The README overclaims what the committed decision log contains
    winner: B1
    ship: PUSHED e7574c2
  iter-195
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Delete the byte-identical `_log_absorbed` twin; hoist it onto `BaseCollector`
    - Candidate A2 -- Retire the roadmap index rows whose own status says no iteration will take them
    - Candidate A3 -- Collapse the twice-hand-copied depth-counted cache-scope protocol
    - Candidate B1 -- Lazy-import the collector registry so the zero-input verbs stop paying for perception
    - Candidate B2 -- Measured-down report on roadmap row #210 (shared walk provider, batch 3)
    - Candidate B3 -- (pending measurement)
    winner: A1
    ship: PUSHED a1f04e9
  iter-194
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- `run --json` publishes a `run_id` that names nothing; make the run identity joinable
    - Candidate A2 -- give the persisted run directory its first non-existence consumer
    - Candidate A3 -- give `signals --baseline` its first consumer, armed on `ci_config` only
    - Candidate B1 -- collapse the duplicated CI gate-contract constants: 9 definition sites for 4 facts, and 4 tests that exist only to police the copies
    - Candidate B2 -- delete the product's ONLY exact structural duplicate: the shared `_dirs_to_scan` body in `git_stash` and `git_state`
    - Candidate B3 -- collapse the 6th copy of the prune idiom: convert the next batch of hand-rolled walkers onto `dir_source.walk`
    winner: A2
    ship: PUSHED 39458cd
  iter-193
    lenses: **hardening/DX**, **integration-and-adoption**
    - Candidate A1 -- `make roadmap-headroom`: a headroom gauge for the ROADMAP char budget
    - Candidate A2 -- a per-module non-triviality census: no tracked test module collects zero tests
    - Candidate A3 -- couple `make check`'s three inlined commands to the named recipes they duplicate
    - Candidate B1 -- `make demo` grades its own run document through the committed consumer `examples/check_run.py`
    - Candidate B2 -- put the README's published `watch` -> `diff` change feed under a gate, and pin the exact outcome it publishes
    - Candidate B3 -- `make hooks` / `make hooks-off`: a one-command on-ramp for the shipped opt-in gate
    winner: B1
    ship: PUSHED 3492fac
  iter-192
    lenses: unknown
    - Candidate A1 -- 18th collector: `python_version_drift` (declared floor vs pinned interpreter)
    - Candidate A2 -- `run` / `dispatch --max-iterations N` and `--max-llm-calls N`: make the L1 budget reachable
    - Candidate A3 -- `pla trend --dir DIR`: which goals PERSIST across a watch stream
    - Candidate B1 -- `signals --fail-over N` is fail-OPEN on a degraded collector
    - Candidate B2 -- oracle the 2 unguarded `_out_dir_guard` messages (roadmap #136)
    - Candidate B3 -- pin the live-tree porcelain-sampling contract, and correct roadmap #205
    winner: B2
    ship: PUSHED 4f83718
  iter-191
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- SPEC section 2's Layout tree is the repo's orientation map and it is 4-of-17 stale, in the one region the SPEC guard cannot see
    - Candidate A2 -- the docstring that argues against stale numerals carries a stale LIST: 2 false names, 2 omissions, and HEAD widened the gap
    - Candidate A3 -- the repo's most numerous artifact class has a naming contract that exists only in a gitignored file outside the repo
    - Candidate B1 -- the 18th collector: local branches you walked away from, read from the branch reflog
    - Candidate B2 -- goals have a change feed; the facts under them do not -- nothing compares two snapshots
    - Candidate B3 -- make the L1 budget SETTABLE from the CLI, with the roadmap's named seam trap measured and resolved
    winner: A1
    ship: PUSHED 6f15baf
  iter-190
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- convert the 3 content walkers onto dir_source, lower WALK_BUDGET 10 to 7
    - Candidate A2 -- text_source retains decoded text across watch ticks, keyed on size and mtime_ns
    - Candidate A3 -- persist the syntax_error parse verdict across processes
    - Candidate B1 -- the ONE-prune-set safety claim is false: 3 definitions, 7 / 6 / 6 members
    - Candidate B2 -- the two provider-consumer sentences are prose sets with no guard
    - Candidate B3 -- the repo's most numerous artifact class has a numbering scheme no document explains
    winner: B1
    ship: PUSHED 3e3b52f
  iter-189
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- convert 2 more collectors onto `dir_source.walk`, deleting their hand-copied prune block
    - Candidate A2 -- delete the two LOCAL copies of the walk policy in `todos` and `notes`, which have already diverged
    - Candidate A3 -- retire settled `ROADMAP.md` row #121 and its pin test, reclaiming 968 of 1,012 remaining chars
    - Candidate B1 -- persist the parse-verdict memo across PROCESSES, opt-in and content-digest keyed
    - Candidate B2 -- defer the heavy module-level imports in `cli.py` so a non-scanning verb stops paying pydantic
    - Candidate B3 -- a per-scan WORK-BUDGET oracle: pin physical traversals, decodes, parses and child processes
    winner: B3
    ship: PUSHED 37055aa
  iter-188
    lenses: integration-and-adoption (state-dir iter-188), simplification-and-deletion (state-dir iter-188)
    - Candidate A1 -- the graded gate cannot see a demo run that never reached `done`; the grader for it is already shipped and unconsumed
    - Candidate A2 -- `signals --fail-over N` gets its first consumer (roadmap #184), and the measurement says the obvious shape would be a fail-open
    - Candidate A3 -- `--baseline`'s first consumer: commit one snapshot and arm `ci_config` only (roadmap #161)
    - Candidate B1 -- delete the two duplicate copies of the dir-prune policy (3 definitions -> 1), proven behavior-preserving
    - Candidate B2 -- convert ONE remaining bespoke walker onto the shared provider, deleting its traversal and its prune block
    - Candidate B3 -- narrow the `filesystem.py` exemption to its true scope: `_has_source` walks with NO recency prune and should be served, not re-walk
    winner: B1
    ship: PUSHED 154e42a
  iter-187
    lenses: hardening/DX -- iteration 187, integration-and-adoption -- iteration 187
    - A1 -- Reclaim `ROADMAP.md` headroom before the 40,000-char ceiling reds a public build
    - A2 -- Oracle the two unguarded `_out_dir_guard` messages (roadmap row #136)
    - A3 -- `make test-contracts`: a derived, seconds-scale pre-check for the guard class that reverted iter-186
    - B1 -- Arm the gate against a committed baseline: `--baseline`'s first executable consumer (roadmap #161)
    - B2 -- `pla scan --json`: one machine-readable idiom across every verb
    - B3 -- `make hooks`: a discoverable on-ramp for the pre-commit gate the repo already ships
    winner: B2
    ship: unknown
  iter-186
    lenses: NEW-CAPABILITY, hardening/DX
    - Candidate A1 -- `pla trend --dir DIR`: which goals RECUR across a watch stream
    - Candidate A2 -- `pla watch --collector NAME`: the stream verb's perception cannot be scoped
    - Candidate A3 -- `dispatch`/`explain --rank N`: act on the goal the table just numbered
    - Candidate B1 -- `tests/conftest.py` strips the `PLA_*` namespace so an exported knob cannot red a clean checkout
    - Candidate B2 -- oracle the two unguarded `_out_dir_guard` messages
    - Candidate B3 -- `resume` names the corrupt file it choked on, instead of surfacing a raw JSON parser message
    winner: A2
    ship: REVERTED
  iter-185
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- the README links NONE of the four companion documents, so the decision log is unreachable
    - Candidate A2 -- CHECKED AND VOID: DIRECTIONS.md misreporting its own ship outcomes
    - Candidate A3 -- the exit-code preamble sends a scripting reader to the one surface `python -OO` deletes
    - Candidate A4 -- the exit-1 row omits the third malformed-JSON file that actually reaches it
    - Candidate B1 -- `pla trend --dir DIR`: which goals PERSIST across a watch stream
    - Candidate B2 -- `--max-iterations N` / `--max-llm-calls N`: make the L1 budget SETTABLE
    - Candidate B3 -- `PythonVersionDriftCollector`: the 18th collector, 2nd RELATIONAL one
    winner: A1
    ship: PUSHED 6082214
  iter-184
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- move `syntax_error` onto `dir_source`, because that seam is where 59% of the cold scan lives
    - Candidate A2 -- an INPUT-side path prune, so a user who ignores a subtree stops paying for it
    - Candidate A3 -- correct the two queued suite-throughput rows against a measurement taken today
    - Candidate B1 -- the exit-5 producer guard requires 2 of the 3 gates that actually return 5
    - Candidate B2 -- the README tells a scripting reader the exit-code contract lives in the one surface `python -OO` deletes
    - Candidate B3 -- the README links NONE of the four other tracked documents, including the decision log that is the repo's differentiator
    winner: B1
    ship: PUSHED 304ecdf
  iter-183
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- one shared scan-scope lifecycle: `walk_scope` and `scan_scope` are byte-identical
    - Candidate A2 -- fold the last 2 hand-copied `_SKIP_DIRS` + `_is_hidden` copies (ROADMAP row #178)
    - Candidate A3 -- delete `_out_dir_guard` outright: the special case of a general rule that already exists
    - Candidate B1 -- convert the next batch of `os.walk` collectors onto the shared `dir_source` provider (ROADMAP #210)
    - Candidate B2 -- one shared per-scan stat provider, the third member of the `text_source` / `dir_source` family
    - Candidate B3 -- re-measure suite throughput; ROADMAP #169's premise has now moved twice
    winner: B1
    ship: PUSHED 41dc9ec
  iter-182
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 (primary) -- the demo persists its snapshot and the gate runs `verify --fail-on-unresolved`
    - Candidate A2 -- give `examples/check_run.py` its first non-test consumer
    - Candidate A3 -- `make verify-demo`: the same wiring, with none of the pinned-gate coupling
    - Candidate B1 (primary) -- delete the `_log_absorbed` duplicate that iteration 184 shipped two iterations ago
    - Candidate B2 -- collapse the two depth-counted per-scan cache scopes into one
    - Candidate B3 -- fold the 2 drifted `_SKIP_DIRS` + `_is_hidden` copies into the seam (roadmap row #178, census re-confirmed today)
    winner: A1
    ship: PUSHED 3e9e944
  iter-181
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- single-source the `PLA_*` clearing idiom, and apply it to the 3 tests an exported knob reds
    - Candidate A2 -- oracle the 2 `watch --out-dir` guard messages that no test names
    - Candidate A3 -- `make test-cold`: an offline cold-suite instrument, plus correcting the warm citations
    - Candidate B1 -- the demo writes its paired snapshot, and the gate runs `pla verify` as the first CONTENT read-back
    - Candidate B2 -- `signals --fail-over N`: the one ratchet with nothing to keep fresh gets its first consumer
    - Candidate B3 -- `--baseline`'s first consumer: commit one snapshot and arm `ci_config` only
    winner: A1
    ship: PUSHED e888949
  iter-180
    lenses: unknown
    - Candidate A1 -- `scan --suppress FILE`: let the user retire a goal that keeps coming back
    - Candidate A2 -- `signals --max-items N`: make perception DEPTH reachable from the CLI
    - Candidate A3 -- `run --max-goals N`: the autonomous verb acts on 1 of N goals it already approved
    - Candidate B1 -- the suite is not environment-hermetic: an exported `PLA_*` knob reds a clean checkout
    - Candidate B2 -- 52 conditional-skip sites, and no instrument anywhere reports that a test skipped
    - Candidate B3 -- iter-169 made absorbed collector failures visible; two collectors still swallow per-item failures in total silence
    winner: B3
    ship: PUSHED 5d7737b
  iter-179
    lenses: narrative-and-docs, NEW-CAPABILITY (iteration 179)
    - Candidate A1 -- SPEC.md never documents the enforcement surface: the armed `signals` gates, exit code 5, and the fact that this repo's own CI runs them
    - Candidate A2 -- SPEC.md never documents `runs --prune`, the product's only destructive operation
    - Candidate A3 -- README never mentions 2 of the 9 shipped `make` targets, one of which exists purely to keep a README number from going stale
    - Candidate B1 -- `run --max-goals N`: the sole autonomous verb acts on 1 of N goals it already approved
    - Candidate B2 -- per-category autonomy thresholds (`PLA_CATEGORY_MIN_SCORE=career:4.5,maintenance:3.0`)
    - Candidate B3 -- `PythonVersionDriftCollector`: the 18th collector, 3rd relational one
    winner: A3
    ship: PUSHED 96a5336
  iter-178
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- single-source the per-path content digest into `text_source`
    - Candidate A2 -- `syntax_error` skips `ast.parse` when a matching `__pycache__` pyc proves the source already compiled
    - Candidate A3 -- re-price ROADMAP row #210: the remaining redundant walks are worth ~1.5% here, not the ~915 ms the seam's docstring cites
    - Candidate B1 -- bind `SPEC.md`'s module contracts to the live registries, the way `README.md` already is
    - Candidate B2 -- a "Repository map" section: the public README never names ANY of the four other tracked docs
    - Candidate B3 -- freeze `SPEC.md`'s section numbering with a citation oracle
    winner: B1
    ship: PUSHED d4a39dc
  iter-177
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Empty the one-member retirement allowlist by retiring the settled row #121
    - Candidate A2 -- Delete the last two hand-copied walk-policy blocks in `notes.py` and `todos.py`
    - Candidate A3 -- Collapse the byte-identical per-scan cache-scope lifecycle into one guard
    - Candidate B1 -- Split the `todos` prefilter per REGEX, not per file: +29.93 ms measured (36.9% of its hot loop)
    - Candidate B2 -- Convert the next 2-3 walking collectors onto `dir_source` (queued row #210), priced honestly
    - Candidate B3 -- PENDING MEASUREMENT IN THIS RUN (see below)
    winner: B1
    ship: PUSHED 9c263e6
  iter-176
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- `pla verify --fail-on-unresolved`: the exit code a caller can branch on
    - Candidate A2 -- the demo publishes its own snapshot, and the gate asserts the file
    - Candidate A3 -- `make hooks`: a one-command on-ramp for the pre-commit gate the README already advertises
    - Candidate B1 -- one `_ranked_pairs()` helper; five copies of the ordering contract deleted
    - Candidate B2 -- one shared digest-memo primitive; three hand-rolled copies deleted
    - Candidate B3 -- bound the append-only Done ledger, the only unbounded term in a hard-capped file
    winner: A1
    ship: PUSHED 6c8f0d3
  iter-175
    lenses: hardening/DX (iteration 175), integration-and-adoption (iteration 175)
    - Candidate A1 -- a user-facing JSON read must name the file it failed on
    - Candidate A2 -- `make test-cold`: derive the suite wall-time instead of citing it
    - Candidate A3 -- make the two `_out_dir_guard` clauses distinguishable to the suite
    - Candidate B1 -- `run --snapshot FILE`: the demo cannot produce the newest verb's required input
    - Candidate B2 -- `verify --fail-on-unresolved`: the trust verb has no channel a gate can branch on
    - Candidate B3 -- the gate finally READS an artifact back (roadmap row #185), priced
    winner: B1
    ship: PUSHED 328ca70
  iter-174
    lenses: NEW-CAPABILITY, HARDENING/DX
    - Candidate A1 -- `pla coverage`: which PERCEIVED signals the slate cites NOBODY
    - Candidate A2 -- `pla trend --dir DIR`: which goals PERSIST across a whole watch stream
    - Candidate A3 -- `run/dispatch --allow-tool NAME`: narrow the ACT sandbox for one dispatch
    - Candidate B1 -- git ignores `.coverage` but NOT the `.coverage.<host>.<pid>` files the suite actually writes
    - Candidate B2 -- Row #136: the newest of the four CLI path guards is the only unguarded one
    - Candidate B3 -- Row #185: make one gate step READ the demo slate instead of stat-ing it
    winner: B1
    ship: PUSHED 10d0aa2
  iter-173
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- The newest module's load-bearing safety claim is false in all three clauses, and roadmap #210 is queued to act on it
    - Candidate A2 -- The armed-gate justification claims to be exhaustive but explains 10 of 17 live kinds, and the next collector makes it 8 unexplained
    - Candidate A3 -- "Red on arrival" disqualifies three kinds by reasoning as if the product's own ratchet never shipped
    - Candidate B1 -- `pla verify --slate S --snapshot N`: resolve each goal's cited sources against the signals actually perceived
    - Candidate B2 -- `pla trend --dir DIR`: which goals PERSIST across a whole watch stream, not just the last tick
    - Candidate B3 -- `run/dispatch/resume --max-iterations N` and `--max-llm-calls N`: make the L1 budget SETTABLE, not merely reportable
    winner: B1
    ship: PUSHED c45c54e
  iter-172
    lenses: performance-and-throughput, NARRATIVE-AND-DOCS
    - Candidate A1 -- convert the 7 remaining walking collectors onto dir_source (roadmap #210)
    - Candidate A2 -- shared per-scan stat provider: 14,179 stat calls, but only 1.7% of the scan
    - Candidate A3 -- retire Path.relative_to from the per-file hot loop: 101 ms, 10.8% of the scan
    - Candidate B1 -- Bump the README suite-size floor 3,800+ -> 4,200+ and publish the headroom
    - Candidate B2 -- Four shipped rows lost their reasoning: derive the archive-coverage census instead of hardcoding it
    - Candidate B3 -- Guard the README's hand-enumerated shared-walk collector list before row #210 makes it false
    winner: B1
    ship: PUSHED aae1a80
  iter-171
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Fold the three hand-copied content-digest memos into one seam (136 LOC of triplicated policy)
    - Candidate A2 -- Retire the 4 ROADMAP index rows whose premise is DEAD: 3,538 chars against 1,594 chars of headroom
    - Candidate A3 -- One `_emit_json` seam: 22 hand-spelled `indent=2` sites and 8 copy-pasted comments
    - Candidate B1 -- One shared tree walk per scan: 13 redundant traversals, ~350 ms of a 915 ms scan
    - Candidate B2 -- Cut the suite's critical path: 2 tests cost 20.43 s of a 55.53 s suite and 0.54 s standalone
    - Candidate B3 -- Make `signals --timings` attribute shared I/O honestly: the perf instrument is off by up to 8x
    winner: B1
    ship: PUSHED 817baf1
  iter-170
    lenses: INTEGRATION-AND-ADOPTION, SIMPLIFICATION-AND-DELETION
    - Candidate A1 -- first committed consumer of the four-verb `--json` contract
    - Candidate A2 -- an oracle that every fenced README `pla` command line actually PARSES
    - Candidate A3 -- close the retention gap: `runs --prune` has no consumer while the repo fakes retention with `rm -rf`
    - Candidate B1 -- collapse THREE hand-copied content-digest memos into one generic memo, keeping three separate instances
    - Candidate B2 -- retire 12 of the 13 hand-copied "verb count is 15" pins, keeping one on the seam that already exists
    - Candidate B3 -- delete the byte-identical test-helper bodies that up to 12 modules each redefine
    winner: A1
    ship: PUSHED 3b165f7
  iter-169
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- `resume` dies on a corrupt `meta.json` without naming the file, while `runs` tolerates the identical file (ROADMAP #151)
    - Candidate A2 -- the README suite-size floor is 139 tests from turning the public build red, and nothing reports the headroom (ROADMAP #206)
    - Candidate A3 -- the graded demo gate is existence-only, so an empty slate and a 0-byte artifact pass it (ROADMAP #185)
    - Candidate B1 -- the `--baseline` ratchet still has ZERO gate consumers, and the producer that feeds it already shipped (ROADMAP #161, feeding on #200)
    - Candidate B2 -- `resume` is the last execution verb with no machine result, and the document builder it needs already exists (ROADMAP #196)
    - Candidate B3 -- the snapshot has a ratchet reader but no TRUST reader, so `sources` are still taken on the model's word (ROADMAP #201)
    winner: B2
    ship: PUSHED 8c039b9
  iter-168
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `pla verify --slate S --snapshot N`: resolve each goal's cited sources against the signals actually perceived (roadmap row #201)
    - Candidate A2 -- `run --max-iterations N` / `--max-llm-calls N`: make the L1 budget SETTABLE, not merely reportable (roadmap row #190)
    - Candidate A3 -- `pla resume --json`: the last execution verb with no machine result (roadmap row #196)
    - Candidate B1 -- Single-source the `ROADMAP.md` size budget: a second, undocumented ceiling has boxed the PM's own artifact down to 88 chars
    - Candidate B2 -- Roadmap row #136: give the 2 unguarded `_out_dir_guard` messages an oracle
    - Candidate B3 -- Row #205 is FALSIFIED for 4 of the 5 modules it names; convert it into a forward-looking determinism census
    winner: B1
    ship: PUSHED a95c513
  iter-167
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- SPEC.md's layout tree hides 14 of the 20 files in the L2 perception package, and nothing guards it
    - Candidate A2 -- the operator's pinned README layer line is still unlanded
    - Candidate A3 -- the two iteration counters and the commit-tag convention are recorded nowhere in the repo
    - Candidate B1 -- `pla verify --slate S --snapshot N`: give the shipped snapshot its first reader
    - Candidate B2 -- `resume --json`: the last execution verb with no machine result
    - Candidate B3 -- `--max-iterations N` / `--max-llm-calls N` on the three loop verbs
    winner: A1
    ship: unknown
  iter-166
    lenses: performance-and-throughput (iter 166), narrative-and-docs
    - Candidate A1 -- one shared per-scan directory walk instead of 11
    - Candidate A2 -- the suite is at 60.03 s warm, 2x every figure the repo cites, against a documented 120 s BROKEN cliff
    - Candidate A3 -- trim the ~130 ms of import every `pla` process pays before it does any work
    - Candidate B1 -- the README's suite-size floor is 323 tests stale, with 177 tests of headroom before it reds the public build
    - Candidate B2 -- DIRECTIONS.md misreports its own outcomes: 5 entries say `ship: unknown`, and git proves at least one of them shipped
    - Candidate B3 -- two diverging iteration counters, and the offset is recorded nowhere
    winner: B1
    ship: PUSHED 10b7118
  iter-165
    lenses: SIMPLIFICATION-AND-DELETION, performance-and-throughput (iteration 165)
    - Candidate A1 -- Hoist the walk policy: delete notes.py's and todos.py's private `_SKIP_DIRS` + `_is_hidden` copies
    - Candidate A2 -- One `_emit_json` writer: retire the 18 hand-copied `print(json.dumps(payload, indent=2))` stdout emitters
    - Candidate A3 -- Host the ancestor-chain rule once: delete the 2 verbatim copies inside the path guards
    - Candidate B1 -- `--timings` attributes the WHOLE wall, not just collect
    - Candidate B2 -- re-price row #129's `todos` prefilter against today's tree
    - Candidate B3 -- settle row #169 (`--dist worksteal`) with the repeats it demands
    winner: A1
    ship: PUSHED c07b267
  iter-164
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- the fail-open collector WARNING has zero consumers, so the armed gate reports GREEN when the collector for an armed kind crashes
    - Candidate A2 -- every gate asserts the demo ARTIFACTS exist; nothing reads one back (roadmap row #185, consumer half)
    - Candidate A3 -- `signals --fail-over N` has had zero consumers since it shipped (roadmap row #184)
    - Candidate B1 -- collapse the third CLI path guard into the second: `_out_dir_guard` is `_state_dir_guard`'s polarity clause plus `_out_target_guard`'s ancestor walk, and its 21-line docstring exists only to justify the duplicate
    - Candidate B2 -- retire settled roadmap row #121 and delete the exemption machinery it forces, so the iter-168 retire-on-ship brake stands unqualified
    - Candidate B3 -- delete the last two hand-copied walk-policy blocks: `notes.py` and `todos.py` each carry their own `_SKIP_DIRS` and `_is_hidden` while 8 sibling collectors import the seam (roadmap row #178)
    winner: A1
    ship: unknown
  iter-163
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- L2 fail-open degradation is invisible: the one collector-failure warning is unreachable for all 17 shipped collectors
    - Candidate A2 -- Census guard: every `*_guard` return message must be pinned by a test
    - Candidate A3 -- Rescope roadmap row #117: its premise is FALSIFIED, and the one real residual is a 6-line self-sufficiency fix
    - Candidate B1 -- The graded gate never READS the demo artifacts back, and the obvious readback step is FAIL-OPEN
    - Candidate B2 -- `resume --json`: the one execution verb a machine cannot read
    - Candidate B3 -- Give `--fail-over` its first consumer, armed against the COMMITTED fixture, at a count the caps cannot make vacuous
    winner: A1
    ship: PUSHED 7d7aad6
  iter-162
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `pla verify --slate S --snapshot N`: resolve each goal's cited sources against the signals actually perceived
    - Candidate A2 -- `pla trend --dir DIR`: which goals RECUR across an N-tick watch stream
    - Candidate A3 -- `--max-iterations N` / `--max-llm-calls N`: make the L1 budget SETTABLE, not just reportable
    - Candidate B1 -- Reclaim `ROADMAP.md` char headroom: the size guard is ~1 iteration from REVERTING an iteration
    - Candidate B2 -- Oracle the 2 unguarded `_out_dir_guard` messages (row #136)
    - Candidate B3 -- Packaging-contract oracle (row #117): priced, and the naive version is a false negative
    winner: B1
    ship: PUSHED a381bd0
  iter-161
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- The README's LLM-free sentence names 7 of the 10 LLM-free verbs, and the oracle to fix it already exists
    - Candidate A2 -- ROADMAP row #122 misstates its own scope twice, contradicted by its own file and the live registry
    - Candidate A3 -- The README publishes three mutually incompatible spellings of "the transparency arc", two of them claiming to be the whole thing
    - Candidate B1 -- `dispatch --allow-tool NAME` (repeatable): a per-run tool allowlist, the L1 half of the autonomy contract
    - Candidate B2 -- `scan --snapshot FILE`: persist the signals the scan actually perceived
    - Candidate B3 -- 18th collector: zero-byte source file (`kind="empty_file"`)
    winner: B2
    ship: PUSHED 9f86ff8
  iter-160
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- Cut the suite's wall-clock FLOOR: one nested-pytest test is 26.16s of a 42.77s suite
    - Candidate A2 -- Per-scan directory-listing memo: 156 of 166 dir listings in one scan are redundant
    - Candidate A3 -- Process startup: every `pla` invocation pays ~123 ms of import before it does any work
    - Candidate B1 -- Retire the self-staling "~Nx this repo's own N files" cache-cap comments and add a shape guard
    - Candidate B2 -- The README's LLM-free verb sentence hand-enumerates 7 of the 10 live LLM-free verbs, and nothing guards it
    - Candidate B3 -- ROADMAP row #122 misstates its own scope twice, contradicted by its own file and the live registry
    winner: B1
    ship: PUSHED e1fdc4c
  iter-159
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Reclaim ROADMAP.md char headroom: retire the one retirable SHIPPED row and relocate the settled Done-ledger tail
    - Candidate A2 -- Delete the two drifted `_SKIP_DIRS` + `_is_hidden` copies in `todos.py` / `notes.py` (3 declarers -> 1)
    - Candidate A3 -- Delete the two remaining hand-copied workspace-relative path idioms in favour of the hosted `BaseCollector._relative`
    - Candidate B1 -- One shared per-scan tree enumeration: 11 collectors each `os.walk` the same tree
    - Candidate B2 -- Give `merge_conflict` and `broken_link` the content memo the other two content collectors already ship
    - Candidate B3 -- Remove the suite's CPU oversubscription: its critical-path test is 44x slower in-suite than alone
    winner: B2
    ship: PUSHED 0f7c6eb
  iter-158
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- `resume --json`, the third call site of the shared dispatch payload builder
    - Candidate A2 -- `pla scan --json`, the convention-conformant spelling of `--format json`
    - Candidate A3 -- make the graded gate PARSE the machine-readable document instead of blind-checking two paths
    - Candidate B1 -- Retire the 5 settled `ROADMAP.md` rows into the archive: 264 bytes of headroom remain before the measured stall trigger
    - Candidate B2 -- Single-source the 12 byte-identical `_registry` test helpers: 88 deletable lines, zero variants
    - Candidate B3 -- One shared permissive `root + direct children` walk, and ONE canonical rationale instead of two that have already drifted
    winner: B1
    ship: PUSHED 2e01037
  iter-157
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- `resume` dies on a corrupt `meta.json` that `runs` tolerates
    - Candidate A2 -- char-size budget guard for `ROADMAP.md` (the file that has already stalled this loop)
    - Candidate A3 -- the self-grading gate asserts the demo artifacts EXIST; nothing READS one back
    - Candidate B1 -- `dispatch --json`: the approval path is the only execution path with no machine result
    - Candidate B2 -- `scan --exclude-path`: two shipped iterations of suppression the LLM path cannot reach
    - Candidate B3 -- `--baseline` and `--fail-over` still have ZERO consumers, in all three gate sites
    winner: B1
    ship: PUSHED f8dd8ad
  iter-156
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `run --max-goals N`: dispatch the top N AUTO goals, not only the head
    - Candidate A2 -- `scan --suppress FILE`: let the user retire a goal that keeps coming back
    - Candidate A3 -- Ground each goal's `sources` against the signals actually perceived
    - Candidate B1 -- Key the root-Markdown table guard on git's TRACKED set, not the working dir (row #155)
    - Candidate B2 -- A char-budget guard for `ROADMAP.md`, now measured 1,641 chars from the trigger (rows #138 + #109)
    - Candidate B3 -- Pin the last 2 unpinned CLI guard messages and make the census two-sided (row #136)
    winner: B1
    ship: PUSHED 9fa85e7
  iter-155
    lenses: narrative-and-docs (iteration 155), new-capability (iteration 155)
    - Candidate A1 -- The README documents 12 of the 17 collectors it advertises; give L2 the drift-guarded table L1 already has
    - Candidate A2 -- The ROADMAP's Done-ledger warning cites six rows as evidence and all six are now wrong
    - Candidate A3 -- README's exit-1 enumeration omits meta.json, the one input `resume` reads unguarded
    - Candidate B1 -- The L1 execution budget is REPORTABLE but not SETTABLE: give the three loop verbs `--max-iterations` / `--max-llm-calls`
    - Candidate B2 -- `pla trend --dir DIR`: which goals PERSIST across a watch stream (`diff` only ever reads the two newest slates)
    - Candidate B3 -- Per-category autonomy thresholds: `PLA_CATEGORY_MIN_SCORE=career:4.5,project:3.0`
    winner: A1
    ship: PUSHED 4a6c833
  iter-154
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- pin `--dist` to a MEASURED xdist scheduler instead of inheriting the default `load`
    - Candidate A2 -- stop the parent pool from starving the nested-pytest children (oversubscription)
    - Candidate A3 -- stop paying mypy's cold start 18 times
    - Candidate B1 -- `pyproject.toml` still publishes "all 3334 tests" as present-tense fact (live: 3845)
    - Candidate B2 -- exit 1 has a THIRD malformed-input file, `meta.json`, that neither prose surface names
    - Candidate B3 -- the repo answers "how fast is the suite" five different ways in four tracked files
    winner: A1
    ship: REVERTED
  iter-153
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Single-source the duplicated CLI/sandbox test helpers: delete 128 redundant lines across 12 modules
    - Candidate A2 -- Retire the 5 settled ROADMAP.md rows: only 2,252 chars of headroom remain before the documented loop-stall trigger
    - Candidate A3 -- Collapse the only exact structural duplicate in src/: the two permissive `_dirs_to_scan` walkers
    - B1 -- Collapse the duplicated nested clean-project pytest bootstrap (largest measured wall win)
    - B2 -- Persist the parse memo across invocations, so a repeated scan skips the 232 ms of re-parsing
    - B3 -- Cut the ~130 ms import tax paid by every `pla` invocation
    winner: B1
    ship: PUSHED 3d42a19
  iter-152
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- `pla signals --github`: turn the armed gate's finding into a GitHub annotation
    - Candidate A2 -- `run --json`: a machine-readable result, so the gate stops globbing
    - Candidate A3 -- `[tool.pla]` in `pyproject.toml`: commit the armed set once instead of three times
    - Candidate B1 -- discharge roadmap row #163: one parameterized child-dir walk instead of three hand-maintained ones
    - Candidate B2 -- collapse the two hand-copied memo snapshot/eviction pairs into one shared memo
    - Candidate B3 -- one `--json` flag declaration instead of ten
    winner: A2
    ship: PUSHED 52b8a4f
  iter-151
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- Audit the TRACKED root-Markdown set, not the working directory (roadmap row #155)
    - Candidate A2 -- Oracle the 2 unguarded CLI path-guard messages (roadmap row #136)
    - Candidate A3 -- Packaging-contract oracle, RE-SCOPED: the declared console script is never resolved (roadmap row #117)
    - Candidate B1 -- Give `--fail-over N` its first real consumer: ratchet the 3 kinds `--fail-on-kind` cannot arm
    - Candidate B2 -- Prove the demo's artifacts are CONSUMABLE, not merely present (writer -> reader round-trip)
    - Candidate B3 -- Stop `signals --kind` from silently discarding all but the last value
    winner: B3
    ship: PUSHED 97e70ca
  iter-150
    lenses: NEW-CAPABILITY, HARDENING / DX
    - Candidate A1 -- `pla signals --max-items N`: make the perception depth a user knob
    - Candidate A2 -- publish that a collector TRUNCATED: a `capped` field on the `--json` and `--summary` surfaces
    - Candidate A3 -- `DebugArtifactCollector` (`kind="debug_artifact"`): the 18th collector, AST-parse-only
    - B1 -- `make check-matrix`: make the local gate reproduce BOTH CI matrix legs, not one accidental one
    - B2 -- `resume` must name the file when `meta.json` is corrupt (roadmap row #151), instead of leaking a raw stdlib parser message
    - B3 -- Key the root-Markdown table guard on the git-TRACKED set, and assert set EQUALITY (roadmap row #155)
    winner: B1
    ship: PUSHED f26288d
  iter-149
    lenses: narrative-and-docs (iteration 149), new-capability (iteration 149)
    - Candidate A1 -- The Done ledger tells the reader to look 28 rows up in the archive; 5 are not there and 3 appear nowhere in it
    - Candidate A2 -- Give `filesystem.py`'s walk-policy charter an oracle: "Eleven modules already import that seam" plus its enumerated list
    - Candidate A3 -- `DIRECTIONS.md` is a 34.6KB tracked public artifact that explains nothing about itself, and it misreports a shipped iteration
    - Candidate B1 (primary) -- The inspector can narrow perception; the two verbs that PRODUCE the slate cannot
    - Candidate B2 -- `PythonVersionDriftCollector`: the 18th collector, and it is measurably SILENT on this repo
    - Candidate B3 -- Ancestor-directory matching for `--exclude-path`, where the measured defect is worse than the roadmap row says
    winner: B3
    ship: PUSHED e2f0dce
  iter-148
    lenses: performance-and-throughput (iteration 148), narrative-and-docs (iteration 148)
    - Candidate A1 -- settle roadmap row #169 (`--dist worksteal`) with the repeats it was blocked on
    - Candidate A2 -- ship roadmap row #129 (`todos` cheap prefilter) on re-validated numbers
    - Candidate A3 -- pytest collection cost: measure it, then cut the fixed leg of every suite run
    - Candidate B1 -- Two collector docstrings claim a walk parity the code contradicts; correct them and pin the flavors
    - Candidate B2 -- Give filesystem.py's "Eleven modules already import that seam" claim a live oracle
    - Candidate B3 -- A roadmap-ledger drift check: fail when a row's status contradicts the shipped record (row #172)
    winner: B1
    ship: PUSHED ab532dc
  iter-147
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Delete the verbatim second `_has_source` + the third copy of its constant, hoisting into the seam 11 modules already import (roadmap row #125)
    - Candidate A2 -- Collapse the 2 near-identical bounded digest-memo mechanisms into one shared helper (roadmap row #146)
    - Candidate A3 -- Fold the last 2 hand-copied `_SKIP_DIRS`/`_is_hidden` walk policies into the same seam -- as a COSMETIC fold plus a drift guard, NOT a behavior fix (roadmap row #178)
    - Candidate B1 -- Cut the suite's single 24.75s long-pole test, which is 58% of the wall clock
    - Candidate B2 -- Prune the armed self-scan gate to the collectors its 4 armed kinds can reach (roadmap row #170)
    - Candidate B3 -- Stop paying the whole library's import on every CLI process: 128 ms of fixed cost per spawn
    winner: A1
    ship: PUSHED db84abc
  iter-146
    lenses: integration-and-adoption, simplification-and-deletion
    - Candidate A1 -- re-land the reverted exit-code epilog on `pla --help`, with a py3.13-safe docstring parse
    - Candidate A2 -- give `runs --prune` its first executable consumer: a graded DRY-RUN step in `make check` + `ci.yml`
    - Candidate A3 -- `make hooks` / `make hooks-uninstall`: a one-command on-ramp for the shipped opt-in gate
    - Candidate B1 -- delete the TWO private copies of `_SKIP_DIRS` + `_is_hidden` in `notes.py` and `todos.py`
    - Candidate B2 -- collapse the two git-subprocess invocation paths into one helper
    - Candidate B3 -- compact `SPEC.md` toward an index, the operator's own named watch item
    winner: A1
    ship: PUSHED 5cc70e5
  iter-145
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- Key the root-Markdown table guard on the TRACKED file set, and close the ambient-glob census at zero
    - Candidate A2 -- Oracle the packaging contract: prove the DECLARED `pla` entry point resolves, offline
    - Candidate A3 -- Char-size budget guard for the per-iteration required-reading docs
    - Candidate B1 -- Give `--baseline` its first consumer: commit a one-entry `ci_config` baseline and arm that kind in the existing gate
    - Candidate B2 -- Publish the exit-code contract in `pla --help`, the surface a scripting consumer reads first
    - Candidate B3 -- `signals --annotate github`: render findings in the workflow-command format CI already consumes
    winner: B2
    ship: REVERTED
  iter-144
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `PythonVersionDriftCollector` (`kind="python_version_drift"`), the 18th collector and 3rd relational perceiver
    - Candidate A2 -- `resume --workspace PATH`: stop resuming a checkpointed run against the current directory
    - Candidate A3 -- `--exclude-path` ancestor matching: make a bare directory mean its subtree
    - Candidate B1 -- Close the rest of the shared-mutable-tree class: 4 more in-repo-fixture comparisons, and a census that can see helper-indirect runs
    - Candidate B2 -- Key the root-Markdown guard on the TRACKED file set (roadmap row #155)
    - Candidate B3 -- The char-size budget guard for the per-iteration required-reading docs (rows #109 + #138), with ~1 iteration of headroom left
    winner: B1
    ship: PUSHED e0ce3a4
  iter-143
    lenses: narrative-and-docs, new-capability
    - Candidate A1 (primary) -- Exit code 5 has TWO producers; the exit-code contract names one, and the guard that should have caught it pins only the incomplete half
    - Candidate A2 -- The architecture bullet describes 12 of the 17 collectors, four lines under an intro that says 17
    - Candidate A3 -- Two collector docstrings assert a walk parity the code disproves, and the false claim points at the exact merge that would change behavior
    - Candidate B1 (primary) -- `signals --baseline FILE --resolved`: report what the snapshot recorded and the workspace no longer shows
    - Candidate B2 -- Ancestor-prefix matching for `--exclude-path`, so one pattern means the subtree (roadmap row #149)
    - Candidate B3 -- `DebugArtifactCollector` (`kind="debug_artifact"`): the 18th collector, AST-only, provably silent here (roadmap row #105)
    winner: A1
    ship: PUSHED 83b89d6
  iter-142
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 (primary) -- Bound the nested-pytest fan-out: two child runs bring up 12 workers inside the 12-worker suite
    - Candidate A2 -- placeholder, being measured
    - Candidate A3 -- placeholder, being measured
    - Candidate B1 (primary) -- Two collector docstrings assert a walk parity the code disproves; fix the prose and pin the parity with an AST guard
    - Candidate B2 -- The README's own architecture description names 12 of the 17 collectors; the 5 newest are missing
    - Candidate B3 -- Three of the 21 shipped-row ledger lines cannot be resolved to a commit, and the shas are mechanically derivable
    winner: A1
    ship: PUSHED 533db40
  iter-141
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- Fold the 3 byte-identical OpenAI-wire `_complete` closures into the `_SdkAdapter` seam that already exists
    - Candidate A2 -- Collapse the two twin bounded digest-memos into one shared helper
    - Candidate A3 -- Delete the verbatim `_has_source` twin and the third copy of the source-extension set
    - Candidate B1 -- `addopts` gains `--dist worksteal`: 30.01s -> 26.05s measured
    - Candidate B2 -- Stop the armed self-scan gate paying for 13 collectors it cannot fail on
    - Candidate B3 -- Make the 120s cliff measurable: publish the COLD (fresh-clone) suite number
    winner: A1
    ship: PUSHED fe395dd
  iter-140
    lenses: integration-and-adoption (iteration 140), simplification-and-deletion (iteration 140)
    - Candidate A1 -- Arm `broken_link` in the shared armed set, wiring the 17th collector's first consumer
    - Candidate A2 -- Give `signals --fail-over N` its first consumer: a code-TODO budget step in the graded gate
    - Candidate A3 -- Let the shipped pre-commit hook carry the two ratchets (`PLA_HOOK_FAIL_OVER` / `PLA_HOOK_BASELINE`)
    - Candidate B1 -- Collapse the duplicated `_has_source` + `_SOURCE_EXTS` (roadmap row #125), design question settled by measurement
    - Candidate B2 -- placeholder, refined below
    - Candidate B3 -- placeholder, refined below
    winner: A1
    ship: PUSHED 6bc2b80
  iter-139
    lenses: hardening/DX, integration-and-adoption
    - Candidate A1 -- Arm the self-scan kinds that measurement now shows are ZERO, and delete the stale "red on arrival" rationale
    - Candidate A2 -- Close the one deliberately-deferred mypy flag: flip `disallow_any_generics` and annotate the 35 bare generics (queued row #121)
    - Candidate A3 -- Close the `resume`-vs-`runs` corrupt-`meta.json` asymmetry (queued row #151)
    - Candidate B1 -- `make hooks`: put the shipped pre-commit gate on the project's own command surface
    - Candidate B2 -- Complete the exit-code contract: exit 5 now has TWO producers and the table names one
    - Candidate B3 -- Give `--fail-over` its first consumer, or record that this repo has no state-independent slice for it
    winner: A2
    ship: PUSHED c4ad01f
  iter-138
    lenses: new-capability, hardening/DX
    - Candidate A1 -- `DebugArtifactCollector` (`kind="debug_artifact"`): revive abandoned row #105
    - Candidate A2 -- `PythonVersionDriftCollector` (`kind="python_version_drift"`): queued row #122
    - Candidate A3 -- `pla signals --fail-over N`: a COUNT-BUDGET gate that cannot rot
    - Candidate B1 -- key the root-Markdown table guard on the TRACKED set, and assert set EQUALITY (row #155)
    - Candidate B2 -- the `ROADMAP.md` char-size budget guard queued three times and never built (rows #138 + #109)
    - Candidate B3 -- give the newest CLI path guard its first oracle (row #136)
    winner: A3
    ship: PUSHED 004f037
  iter-137
    lenses: narrative-and-docs, new-capability
    - Candidate A1 -- Give the source's embedded performance measurements a VINTAGE, and derive the guard from the corpus so it cannot be fail-open
    - Candidate A2 -- Overturn roadmap row #163's premise: the two "identical strategy" docstrings are defensible, and give the word "identical" a real oracle
    - Candidate A3 -- Correct the Makefile's gate rationale, one third of which live measurement disproves
    - Candidate B1 -- `BrokenDocLinkCollector` (`kind="broken_link"`): the 17th collector, and the 2nd relational one
    - Candidate B2 -- `--exclude-path` learns subtree (ancestor-prefix) matching, so ONE spelling can hide a directory
    - Candidate B3 -- `DebugArtifactCollector` (`kind="debug_artifact"`), scoped by measurement to real debugger scaffolding
    winner: B1
    ship: PUSHED 5939593
  iter-136
    lenses: performance-and-throughput, narrative-and-docs
    - Candidate A1 -- Delete one of two duplicate nested pytest runs: 33% of the suite wall, zero behavior lost
    - Candidate A2 -- Make `--exclude-path` prune COLLECTION, not just the display: today it saves 2.5%
    - Candidate A3 -- Land the already-measured `todos` prefilter (roadmap row #129)
    - Candidate B1 -- The README's headline "2,700+ tests" is 657 short of live, and its guard is fail-open in BOTH directions
    - Candidate B2 -- Two collector docstrings claim an "identical strategy" the code contradicts
    - Candidate B3 -- `todos.py`'s performance block is 33% stale and, alone among the three, undated
    winner: B1
    ship: PUSHED 48378fa
  iter-135
    lenses: simplification-and-deletion, performance-and-throughput
    - Candidate A1 -- finish row #165: fold the 3 remaining inline relative-path idioms onto `BaseCollector._relative` (and correct the row's false premise)
    - Candidate A2 -- collapse the three near-duplicate path-target guards into one parameterized guard
    - Candidate A3 -- table-drive the five static-info `_cmd_*` handlers
    - Candidate B1 -- Parallelize the suite: `pytest-xdist` + `-n auto` in `addopts`
    - Candidate B2 -- The `todos` cold-scan prefilter (roadmap row #129, already QUEUED with a settled shape)
    - Candidate B3 -- Cut the fresh-process startup tax on the CLI critical path
    winner: B1
    ship: PUSHED 6fac577
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
    - B1 -- `signals --baseline FILE`: suppress signals already present in a saved snapshot
    - B2 -- 17th collector: `BrokenDocLinkCollector` (`kind="broken_link"`)
    - B3 -- `--max-iterations N` on `run` / `dispatch`: the L1 budget has no CLI control
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
    - A1 -- Memoize `todos`' per-line extraction on a content digest
    - A2 -- One shared per-scan read+digest pass for the three whole-corpus text collectors
    - A3 -- Cross-process persistence of the syntax verdict memo
    - B1 -- Oracle the README config table: the 14 published defaults and the flag-equivalent column
    - B2 -- Publish the `.pla_runs/run-<id>/` artifact layout (roadmap row #128)
    - B3 -- Make `ROADMAP.md` state what actually shipped, and add the row-coverage guard
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
    - A1 -- Document the CLI exit-code contract in the README (codes 3 and 4 are undocumented) + a source-derived reverse guard
    - A2 -- Oracle for the `[project.scripts] pla` console-script entry point
    - A3 -- Make the freshly shipped "works on a bare `uv sync`" promise exact (7, not 10) and guard the distinction
    - B1 -- Delete the 2 divergent private copies of the collector skip-dir seam (`_SKIP_DIRS` + `_is_hidden`) in `notes.py` / `todos.py`; import the canonical pair + an AST single-definition guard
    - B2 -- Delete the verbatim second copy of `_has_source` + `_SOURCE_EXTS` (`license.py` duplicates `ci_config.py`), including the hand-written "keep these in sync" comment
    - B3 -- Delete the stale collector/verb counts written in test PROSE, and collapse the count-locks onto one canonical constant
    winner: A1
    ship: PUSHED 193ac4d
  iter-109
    lenses: HARDENING / DX, INTEGRATION AND ADOPTION
    - H1 -- Close the deferred `disallow_any_generics` flag: annotate the 35 bare generics and flip the ratchet to full `strict` (roadmap row #121)
    - H2 -- Document the `pla dispatch` exit-code contract (3 = BLOCKED, 4 = NEEDS_APPROVAL) below the README marker, with a source-derived reverse guard (roadmap row #115)
    - H3 -- One offline oracle for the console-script contract `pla = proactive_loop.cli:main` (the measured residual of roadmap row #117)
    - I1 -- The one README command aimed at the reader's OWN repo exits 1; make the zero-config first run the LLM-free path and grade every published `pla` line against it
    - I2 -- One machine-readable-stdout purity contract across every JSON emitter, so `pla X --json | jq` is a guaranteed seam
    - I3 -- `pla scan --json` is exit 2 while ten sibling verbs accept `--json`: close the flag-vocabulary inconsistency
    winner: unknown
    ship: PUSHED b83621f
  iter-108
    lenses: NEW CAPABILITY, HARDENING / DX
    - A1 -- `pla runs --prune`: the product's first persisted-state LIFECYCLE capability
    - A2 -- 17th collector `PythonVersionDriftCollector` (`kind="python_version_drift"`): the 2nd RELATIONAL collector
    - A3 -- `pla signals --format {table,json,markdown,csv,html}`: render parity for the perception inspector
    - B1 -- Tighten the mypy oracle to strict-minus-generics: the "fully type-hinted" claim currently passes with an unannotated parameter on the L1 dispatch seam
    - B2 -- ROADMAP row #115: document the CLI exit-code contract + a source-derived reverse guard
    - B3 -- ROADMAP row #109: char-size budget test for the per-iteration required-reading docs
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
    - H1 -- Make the `make check` demo assertions freshness-aware (they are fail-OPEN locally today)
    - H2 -- Correct the README ACT-sandbox tool enumeration + bind the prose to `_TOOL_NAMES` (roadmap row #112, QUEUED)
    - H3 -- Char-size budget guard for the per-iteration required-reading docs (roadmap row #109, QUEUED)
    - I1 -- Document + drift-guard the CLI EXIT-CODE contract (exit 3 and exit 4 exist, are load-bearing, and are documented NOWHERE)
    - I2 -- Give the package a documented top-level import surface -- today `import proactive_loop` yields only `__version__`
    - I3 -- Fix the FIRST command in the Quickstart: bare `uv sync` under a comment claiming "the locked dependency set", with a stale dep list
    winner: unknown
    ship: PUSHED 9cae927
  iter-102
    lenses: NEW CAPABILITY -- iteration 102, HARDENING / DX -- iteration 102
    - A1 -- Publish each collector's emitted signal `kind` in `pla collectors` (+ `--kind` reverse lookup)
    - A2 -- `copy_file`: the 15th L1 ACT-sandbox tool (non-destructive snapshot before a mutation)
    - A3 -- Re-propose `DebugArtifactCollector` (`kind="debug_artifact"`, the 17th collector)
    - B1 -- Correct the README ACT-sandbox tool enumeration + bind it to `ToolRegistry` with a drift guard (roadmap row #112)
    - B2 -- Prune noise directories inside `NotesCollector`'s inner walk (roadmap row #108, top of backlog)
    - B3 -- Char-size budget guard for the per-iteration required-reading docs (roadmap row #109)
    winner: B2
    ship: PUSHED 407f3c0
  iter-101
    lenses: narrative-and-docs, new-capability
    - A1 (RECOMMENDED) -- Publish the 16 `kind` strings that `pla signals --kind` requires, with a source-derived drift guard
    - A2 -- Correct the README's ACT-sandbox tool enumeration: it presents a closed list of 11 while 14 ship, and the 3 missing include a MUTATING tool
    - A3 -- Keep `ROADMAP.md` under the stall budget by ARCHIVING OLD ROWS WHOLESALE (my first framing was wrong; corrected here)
    - B1 (RECOMMENDED) -- Make `--kind` a validated, self-describing vocabulary: derive the 16 kinds into one registry constant and wire it as argparse `choices=`
    - B2 -- `pla scan --min-weight W`: a relevance floor on what the synthesizer is allowed to see
    - B3 -- 17th collector: `SuppressionCollector` (kind=`suppression`) -- surface silenced checkers as latent work
    winner: B1
    ship: PUSHED 268a588
  iter-100
    lenses: performance-and-throughput, narrative-and-docs
    - A1 (STRONGLY RECOMMENDED) -- Prune noise directories inside `NotesCollector`'s inner `rglob("*.md")`
    - A3 -- `pla runs --limit N`, applied BEFORE `_run_row` (bound the per-invocation artifact walk)
    - A2 (DEMOTED after measurement) -- give `NotesCollector` the `max_read_bytes` cap the other text collectors got
    - B1 (STRONGLY RECOMMENDED) -- Close the README's undocumented-flag gap and bind every live CLI long option to the docs with a drift guard
    - B3 -- Turn the operator's docs-growth WATCH ITEM into a machine check (size budget for the per-iteration required-reading docs)
    - B2 (fold into B1, do not pick alone) -- Bind the README CLI TABLE's verb rows to the live subparser set
    winner: B1
    ship: PUSHED d3f97ec
  iter-99
    lenses: SIMPLIFICATION-AND-DELETION, performance-and-throughput
    - A1 (RECOMMENDED) -- Collapse the count-drift cascade to a single pinned expectation
    - A2 (SAFE FALLBACK) -- Delete the two duplicate `_SKIP_DIRS` / `_is_hidden` copies
    - A3 (OPERATOR WATCH ITEM) -- Compact `SPEC.md` into an index + `SPEC_ARCHIVE.md`
    - B1 (RECOMMEND) -- Pre-read byte-size cap in the whole-tree text collectors
    - B3 -- Deterministic I/O-budget guard (counting oracle, test-only)
    - B2 -- Scan-scoped walk+read dedup (single-pass workspace index)
    winner: B1
    ship: PUSHED 83fa8e0
  iter-98
    lenses: NEW-CAPABILITY, HARDENING / DX
    - A1 (RECOMMEND) -- `DebugArtifactCollector` (kind="debug_artifact")
    - A2 -- `pla signals --top N` ranked-limited view
    - A3 -- `EnvExampleCollector` (kind="env_example") -- onboarding-hygiene gap
    - B1 (RECOMMEND) -- Extend the offline-first import guard from `src/` to `tests/`
    - B2 -- License-badge integrity oracle (bind README badge <-> LICENSE file <-> pyproject)
    - B3 -- Pin the "green in CI on Python 3.12 AND 3.13" claim to the CI matrix
    winner: A1
    ship: unknown
  iter-97
    lenses: unknown
    - A1 (recommend) -- `pla config [--json]`: resolved-Settings inspector
    - A2 -- `copy_file(src, dst)` L1 ACT-sandbox tool
    - A3 -- `GitignoreCollector` (`kind="gitignore"`): new L2 perception axis
    - B1 (recommend) -- extend the offline-first import guard to the `tests/` tree
    - B2 -- whole-pipeline determinism regression guard (run-twice-identical)
    - B3 -- `make check` clean-slate hardening (no stale-artifact false pass)
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
    - A1 (recommend) — `copy_file(src, dst)` L1 ACT-sandbox tool
    - A2 — `pla config [--json]` resolved-settings introspection verb
    - A3 — `GitignoreCollector` (`kind="gitignore"`)
    - B1 (build front-door) -- `make check`: one local target that reproduces the exact CI gate
    - B2 (distribution packaging) -- CHEAP oracle that the PEP 561 `py.typed` marker actually SHIPS
    - B3 (type oracle) -- mypy hygiene flags `warn_unused_ignores` + `warn_redundant_casts`
    winner: B1
    ship: PUSHED 19ea19b
  iter-94
    lenses: unknown
    - A1 (L2 perception -- NEW collector): `LicenseCollector` (`kind="license"`)
    - A2 (L1 action -- NEW sandbox tool): `copy_file(src, dst)`
    - A3 (CLI -- NEW query knob): `pla diff --only {added,removed,changed,unchanged}`
    - B1 (build front-door): `make check` -- one local target that reproduces the exact CI gate
    - B2 (distribution packaging): assert the PEP 561 `py.typed` marker actually SHIPS in the wheel
    - B3 (type oracle): mypy hygiene flags `warn_unused_ignores` + `warn_redundant_casts`
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
110 scouted iterations
