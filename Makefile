# Developer entry points. All targets run fully offline (scripted provider).
.PHONY: setup test cov typecheck readme-headroom demo clean check check-matrix

# Resolve and install the locked dependency set into a project virtualenv.
# Uses --locked (not bare 'uv sync') so a local install resolves the EXACT
# dependency set CI grades against: CI runs 'uv sync --locked' and fails on any
# uv.lock drift, so aligning setup here turns a silent local/CI divergence into
# a loud, fixable error and makes 'clone -> make setup == CI env' a guarantee.
setup:
	uv sync --locked

# Run the whole test suite (offline; no network, no API keys).
test:
	uv run pytest

# Run the suite with a coverage report (opt-in; NOT part of `make test`, so a
# bare run stays fast). Terminal report only. Every artifact a coverage run
# drops in the repo root is gitignored AND removed by `make clean`: .coverage,
# htmlcov/, and the per-worker `.coverage.<host>.<pid>.<rand>` data files that
# `addopts = -q -n auto` makes coverage write before it combines them. That
# last class is why the ignore rule and the clean recipe both carry a
# `.coverage.*` glob and not just the exact name.
cov:
	uv run pytest --cov=proactive_loop --cov-report=term-missing

# Type-check the package with the locked mypy -- the local half of the
# permanent oracle for the README's "fully type-hinted" claim (the CI type
# step is the other half). Runs the pinned mypy from the project venv, offline.
typecheck:
	uv run mypy src/proactive_loop

# Print the README suite-size ratchet's HEADROOM: how many tests may still be added
# before the published floor in the human-owned intro goes stale and reds a PUBLIC
# build. The guard that enforces that floor is silent while green, so before this
# target the only signal was the red build itself.
#
# It composes the guard's OWN seams -- `headroom_report` renders the figures and
# `collect_live_test_count` supplies the live number from a real collection -- so the
# gauge and the verdict can never disagree. Reading them from anywhere else, or
# hardcoding the count, is the drift this repo keeps proving is real; a test pins
# this recipe to both helper names for exactly that reason.
#
# `@` because the output IS the product here (one machine-readable line), unlike the
# multi-step gates above where the echoed command is the useful trace.
readme-headroom:
	@uv run python -c 'from tests.test_readme_and_ci_contract import _intro, collect_live_test_count, headroom_report; print(headroom_report(_intro(), collect_live_test_count()))'

# End-to-end demo: scan the fixture workspace, then auto-dispatch the single
# top AUTO_DISPATCH goal through the resilient loop -- all driven by the bundled
# scripted responses, so it never touches a network.
#
# WHY it also writes `--snapshot .pla_runs/snapshot.json`: the slate this recipe
# publishes is the one `make check` and CI grade, and every goal in it cites
# `sources` the synthesizer filled in. `pla verify` can resolve those citations
# against a scan snapshot -- but ONLY honestly against the snapshot the slate was
# synthesized FROM, because several collectors are mtime-driven, so a fresh
# re-scan would make staleness indistinguishable from fabrication. `run
# --snapshot` writes exactly that same-run document, which makes this recipe the
# one caller that structurally qualifies for `verify --fail-on-unresolved` (see
# the verify step in `check` below). It lands in `.pla_runs` -- the dir the
# `check` pre-step wipes -- so the pair the gate reads is always THIS demo's.
#
# WHY it also redirects `--json` into `.pla_runs/run.json` and then GRADES that
# file with `examples/check_run.py`: `run --json` is the scriptable surface the
# README sells, and until this step existed nothing outside `tests/` consumed
# one. `examples/check_run.py` was written to BE that proof and had zero callers
# itself -- the same "advertised but never demonstrated" condition the armed
# signals self-scan and `verify --fail-on-unresolved` were both added to end.
# Grading here makes both gates run the exact script a stranger would copy, and
# because that consumer imports its success value from
# `proactive_loop.models.RunStatus`, renaming that enum member reds a public
# build instead of silently reporting failure on every successful run.
#
# WHY a FILE and not a pipe (`uv run pla run --json | check_run.py`): a pipeline
# reports only its LAST command's status, so a `pla run` that DIED would be
# graded as the consumer's exit 2 ("stdin is not one JSON document") -- a true
# failure reported under a false cause. Two separate steps let `make` grade
# `pla run` itself, and the document stays an inspectable artifact.
#
# WHY `mkdir -p .pla_runs` must come FIRST: the shell opens the `>` redirect
# BEFORE `pla run` starts, and `make check` opens with `rm -rf .pla_runs`, so
# without this step the gate would die on a missing directory rather than on
# anything the demo did. The redirect is a single truncating `>` (never `>>`),
# so the graded document is always THIS run's and can never accumulate or be
# graded stale.
#
# WHY it ALSO publishes `.pla_runs/explain.json` and grades it with
# `examples/check_autonomy.py`: SPEC's autonomy contract -- a goal in a
# sensitive category always needs human approval, at any score -- is this
# product's headline claim, and until this step existed NOTHING enforced it on
# what the demo publishes. The four graded steps below are `test -f`, `ls`,
# citation resolution and checkout hygiene; all four pass on a slate that
# auto-dispatched a sensitive goal at the top score. `pla explain --json` already
# emits exactly that audit and had zero runnable consumers. The gate is
# non-vacuous on this fixture by measurement, not by hope: the demo slate's
# HIGHEST scorer is sensitive and held for approval while a lower one is
# auto-dispatched, so both arms of the predicate are live and the grader refuses
# an audit too thin to exercise either rule (a gate that cannot fire is
# fail-open). The grader IMPORTS the sensitive set from `Settings`, so widening
# it reds this build with no edit to the grader.
#
# WHY a FILE here too, and not `pla explain --json | check_autonomy.py`: the same
# reason the run document is a file -- a pipeline reports only its LAST command's
# status, so an `explain` that DIED would be graded as the consumer's exit 2.
#
# WHY `check_run.py` stays LAST: two shipped guards pin the consumer to the final
# position of this recipe, and the run document is the demo's primary artifact.
#
# WHY `uv run python` and not bare `python`: the consumer imports
# `proactive_loop`, so it needs the project virtualenv.
demo:
	mkdir -p .pla_runs
	uv run pla run \
		--workspace examples/fixture_workspace \
		--provider scripted \
		--scripted-responses examples/scripted_responses.json \
		--state-dir .pla_runs \
		--snapshot .pla_runs/snapshot.json \
		--json > .pla_runs/run.json
	uv run pla explain --slate .pla_runs/slate.json --json > .pla_runs/explain.json
	uv run python examples/check_autonomy.py < .pla_runs/explain.json
	uv run python examples/check_run.py < .pla_runs/run.json

# Remove generated run state, coverage artifacts, and Python/pytest caches.
clean:
	rm -rf .pla_runs
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .coverage .coverage.* htmlcov
	rm -rf .venv-py*

# Reproduce the EXACT CI graded gate locally, in CI's own order, in one command.
# CI (.github/workflows/ci.yml) grades eight run-steps on every push: locked
# install -> suite -> mypy oracle -> offline demo -> demo-artifact assertions ->
# armed source-citation verification -> armed signal COUNT BUDGET -> armed
# signals self-scan.
# Before this target there was no single local command to run that gate, and the
# two demo-artifact assertions lived ONLY in ci.yml (nowhere runnable locally),
# so they could silently rot. It reuses `$(MAKE) demo` (no re-inline) so the demo
# command stays single-sourced. Kept in lockstep with ci.yml by
# tests/test_iter102_behavior.py (a red test == recipe/CI drift).
#
# WHAT `check` IS NOT: everything CI grades. CI's `test` job is a
# `fail-fast: false` matrix over python-version ["3.12", "3.13"], so it grades
# those eight steps TWICE -- sixteen run-steps -- while `make check` runs them ONCE,
# under whichever interpreter uv last left in `.venv`. There is no
# `.python-version` in this repo, so which leg runs locally is an accident
# rather than a choice, and the gap is not hypothetical: a failure reproducible
# only on the newer interpreter has already reached CI unseen. `make check-matrix`
# (below) runs the SUITE under both matrix interpreters, which is the leg-varying
# half of that gap; the second leg's demo, demo-artifact assertions, count budget
# and armed self-scan stay CI-only, along with the second leg's citation
# verification, and mypy is leg-invariant by config
# (`python_version = "3.12"`), so `check` plus `check-matrix` grades 10 of CI's 16
# run-steps rather than all 16.
#
# WHY the recipe OPENS with `rm -rf .pla_runs` (the demo's own state dir): the
# last two steps are EXISTENCE checks (`test -f` / `ls`) against a persistent,
# gitignored dir, so they assert FRESHNESS only when the pre-state is clean. CI
# gets that for free -- every CI run is a fresh checkout -- but a local run does
# not. Without this pre-step a stale .pla_runs/ left by ANY earlier demo
# satisfies both assertions, so the gate reports green even when THIS demo
# produced nothing (no AUTO_DISPATCH goal survived the policy gate, a provider
# silently reflected, the state-dir path changed) -- the exact failure those two
# assertions exist to catch. A trusted fail-open gate is worse than no gate.
# Consequence to know: `make check` DISCARDS your previous .pla_runs/, exactly
# as `make clean` already does -- the pre-step is a strict SUBSET of `clean`, so
# the two cannot drift apart. It is deliberately NOT `$(MAKE) clean`: clean also
# wipes .pytest_cache/__pycache__, which buys no freshness and only makes the
# gate (and the suite that follows it) slower.
#
# WHY the recipe VERIFIES the demo's source citations (the step after the two
# artifact assertions): those two assertions are `test -f` and `ls` -- pure
# EXISTENCE -- so a demo that published a structurally valid but semantically
# wrong slate passes them. This is the first gate step that READS what the demo
# published. `CandidateGoal.sources` is free text the synthesizer fills, `verify`
# resolves each citation against the scan snapshot, and `--fail-on-unresolved`
# turns an unresolvable citation into exit 5 -- and until this step existed that
# pairing had ZERO consumers anywhere, the same "advertised but never
# demonstrated" condition the armed self-scan below was added to end.
#
# WHY it is safe to ARM here specifically, when `verify` defaults to
# reporting-only: the flag's own contract is that the caller KNOWS its
# slate/snapshot pair is same-run, because several collectors are mtime-driven
# and an unresolved source can therefore mean staleness rather than fabrication.
# `make demo` writes both halves in ONE `pla run` invocation, so the precondition
# is structural here rather than merely likely -- and measured green: this pair
# reports 0 unresolved, while appending one fabricated source to a copy of the
# slate exits 5. Both directions matter; a gate proven green but never proven to
# fire is a fail-open gate.
#
# It runs BEFORE the self-scan (so the self-scan stays the LAST step) and AFTER
# the artifact assertions, which are its precondition: verification is
# meaningless if the demo produced no slate at all.
#
# WHY the recipe also runs an armed COUNT BUDGET (`--fail-over N`, the step just
# before the self-scan): `--fail-on-kind` can only arm a kind that is ZERO here,
# so the kinds that are merely SUPPOSED to stay small -- `note`, `ci_config`,
# `dependency`, `test_posture` -- are structurally beyond its reach (all non-zero
# today: arming them by kind is red on arrival). `--fail-over N` is the count
# budget for exactly that case, and until this step existed it had ZERO consumers
# anywhere -- the same "advertised but never demonstrated" condition the two gates
# below and above it were both added to end.
#
# WHY it selects FOUR collectors instead of budgeting the whole census, which is
# the one decision in this step that is not obvious. A budget over the FULL view
# counts `working_tree` too, and `working_tree` emits one signal per changed path:
# measured on this repo, the census is 75 with a clean tree and 76 with a single
# uncommitted edit. So a whole-census budget would be red for every developer
# mid-edit while CI -- always a fresh checkout -- stayed green, which is verbatim
# the failure the self-scan's arm set below refuses to ship. `--collector` is an
# UPSTREAM filter, so naming these four both makes the count state-independent and
# makes the step cheap (four collectors run, not seventeen).
#
# WHY these four and not the other thirteen: they are the whole set that is BOTH
# state-independent AND unsaturated. `todo` (30/30), `recent_file` (20/20) and
# `git_commit` (15/15) sit ON their caps, so a budget over them can never fire --
# a gate that cannot fire is fail-open; `lockfile_drift` is mtime-driven (it is
# the one signal that differs between this tree and a fresh clone); and
# `working_tree` / `git_state` / `git_stash` are the local-state kinds. What is
# left is these four, and they are also the only ones with real headroom.
#
# WHY 9, and why the boundary is safe: the four-collector view totals 9 here
# (`note 5`, `test_posture 2`, `ci_config 1`, `dependency 1`) and `--fail-over` is
# STRICTLY greater, so 9 is inside the budget and the 10th signal fails. Measured
# in BOTH populations a gate has to survive -- this working tree and a throwaway
# `git clone --no-hardlinks` of it -- the count is 9 either way, so no
# `--exclude-path` equalisation is needed and nothing is blinded. Both directions
# were run, because a gate proven green but never proven to fire is a fail-open
# gate: `--fail-over 9` exits 0 with an empty stderr in both, and `--fail-over 8`
# exits 5 in both with one `gate: fail-over tripped -- count=9 budget=8` line.
# Raising this number is a deliberate act, which is the point of a ratchet.
#
# WHY the recipe CLOSES with an armed `pla signals` self-scan (the LAST step):
# the product ships an enforcement mode -- `--fail-on-kind KIND` exits 5 when a
# named signal kind is present -- and the README sells that exit code as "the
# channel a pre-commit hook or a CI step branches on". Until this step existed
# that integration had ZERO consumers, including the build this repo grades
# itself on, so the claim was advertised but never demonstrated: the tool did
# not police the repo that ships it. Arming it here makes the exit-5 path a
# graded, end-to-end-exercised contract on every push.
#
# WHY exactly these four kinds, and no more: the arm set must be
# STATE-INDEPENDENT -- a finding can only mean "this checkout is broken", never
# "this developer has work in progress". `merge_conflict` / `syntax_error` /
# `secret_file` / `broken_link` are must-never-appear properties of the tree
# itself and are all zero here. `broken_link` joined the set in factory iter 147:
# a relative Markdown link the filesystem disproves is a reader-facing defect on
# a repo whose whole value is being publicly readable, and it is decided by the
# committed tree alone -- no developer's work-in-progress can produce one.
# Deliberately NOT armed: `working_tree` / `git_state` / `git_stash`
# (measured: ONE uncommitted edit exits 5, so the LOCAL gate would be red for
# every developer mid-edit while CI -- always a fresh checkout -- stayed green,
# i.e. a gate that is green in the only place it is measured and red everywhere
# it is used), and `lockfile_drift` / `test_posture` / `ci_config` (non-zero in
# this repo today: red on arrival). It runs LAST so a tripped scan can never
# mask the demo-artifact assertions, and after `uv sync --locked` because it
# needs the project venv to resolve the `pla` console script.
check:
	rm -rf .pla_runs
	uv sync --locked
	uv run pytest
	uv run mypy src/proactive_loop
	$(MAKE) demo
	test -f .pla_runs/slate.json
	ls .pla_runs/run-*/artifacts/*.md > /dev/null
	uv run pla verify --slate .pla_runs/slate.json --snapshot .pla_runs/snapshot.json --fail-on-unresolved
	uv run pla signals --workspace . --collector notes --collector ci_config --collector dependencies --collector test_posture --fail-over 9
	uv run pla signals --workspace . --fail-on-kind merge_conflict --fail-on-kind syntax_error --fail-on-kind secret_file --fail-on-kind broken_link

# Run the suite under EVERY interpreter CI's matrix grades -- the SUITE half of the
# interpreter-coverage gap `check` above cannot close (see "WHAT `check` IS NOT").
# Opt-in, and deliberately NOT wired into `check` or into ci.yml: CI already IS the
# matrix, and `check` stays the fast single-leg gate.
#
# WHY each leg gets its own UV_PROJECT_ENVIRONMENT instead of a bare
# `uv run --python X.Y`: a bare `uv run --python` DELETES and recreates the
# DEFAULT `.venv` (measured), so this target would silently hand the next command
# a different interpreter than the one it just reported. Pointing each leg at its
# own throwaway `.venv-py<XY>` leaves `.venv` untouched, so no restore epilogue is
# needed and the target is safe to run at any moment. Those dirs are hidden, so
# the collectors' skip rule keeps them invisible to the armed self-scan; the
# .gitignore entry keeps them out of `git status`, and `clean` removes them.
#
# WHY --locked and --offline on every leg: --locked installs the EXACT dependency
# set CI grades (the same reason `setup` uses it, and it fails loudly on uv.lock
# drift instead of resolving something new), and --offline makes a network fetch
# impossible, so a leg cannot quietly buy its own green with a fresh download.
#
# WHY a missing interpreter FAILS rather than being skipped: the same rule the
# `check` pre-step above is built on -- a trusted fail-open gate is worse than no
# gate. Install the leg (`uv python install 3.13`) rather than skipping it.
#
# The leg set here is pinned to ci.yml's `strategy.matrix.python-version` by
# tests/test_iter156_behavior.py, so adding a leg to CI (or here) alone is a red
# test rather than a silent hole.
check-matrix:
	UV_PROJECT_ENVIRONMENT=.venv-py312 uv run --offline --locked --python 3.12 pytest
	UV_PROJECT_ENVIRONMENT=.venv-py313 uv run --offline --locked --python 3.13 pytest
