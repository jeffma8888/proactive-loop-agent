# Developer entry points. All targets run fully offline (scripted provider).
.PHONY: setup test cov typecheck demo clean check

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
# bare run stays fast). Terminal report only; .coverage/htmlcov are gitignored
# and removed by `make clean`.
cov:
	uv run pytest --cov=proactive_loop --cov-report=term-missing

# Type-check the package with the locked mypy -- the local half of the
# permanent oracle for the README's "fully type-hinted" claim (the CI type
# step is the other half). Runs the pinned mypy from the project venv, offline.
typecheck:
	uv run mypy src/proactive_loop

# End-to-end demo: scan the fixture workspace, then auto-dispatch the single
# top AUTO_DISPATCH goal through the resilient loop -- all driven by the bundled
# scripted responses, so it never touches a network.
demo:
	uv run pla run \
		--workspace examples/fixture_workspace \
		--provider scripted \
		--scripted-responses examples/scripted_responses.json \
		--state-dir .pla_runs

# Remove generated run state, coverage artifacts, and Python/pytest caches.
clean:
	rm -rf .pla_runs
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .coverage htmlcov

# Reproduce the EXACT CI graded gate locally, in CI's own order, in one command.
# CI (.github/workflows/ci.yml) grades six run-steps on every push: locked
# install -> suite -> mypy oracle -> offline demo -> demo-artifact assertions ->
# armed signals self-scan.
# Before this target there was no single local command to run that gate, and the
# two demo-artifact assertions lived ONLY in ci.yml (nowhere runnable locally),
# so they could silently rot. `make check` == a green CI. It reuses `$(MAKE)
# demo` (no re-inline) so the demo command stays single-sourced. Kept in lockstep
# with ci.yml by tests/test_iter102_behavior.py (a red test == recipe/CI drift).
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
	uv run pla signals --workspace . --fail-on-kind merge_conflict --fail-on-kind syntax_error --fail-on-kind secret_file --fail-on-kind broken_link
