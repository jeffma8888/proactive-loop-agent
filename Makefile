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
# CI (.github/workflows/ci.yml) grades five run-steps on every push: locked
# install -> suite -> mypy oracle -> offline demo -> demo-artifact assertions.
# Before this target there was no single local command to run that gate, and the
# two demo-artifact assertions lived ONLY in ci.yml (nowhere runnable locally),
# so they could silently rot. `make check` == a green CI. It reuses `$(MAKE)
# demo` (no re-inline) so the demo command stays single-sourced. Kept in lockstep
# with ci.yml by tests/test_iter102_behavior.py (a red test == recipe/CI drift).
check:
	uv sync --locked
	uv run pytest
	uv run mypy src/proactive_loop
	$(MAKE) demo
	test -f .pla_runs/slate.json
	ls .pla_runs/run-*/artifacts/*.md > /dev/null
