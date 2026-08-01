# Developer entry points. All targets run fully offline (scripted provider).
.PHONY: setup test cov demo clean

# Resolve and install the locked dependency set into a project virtualenv.
setup:
	uv sync

# Run the whole test suite (offline; no network, no API keys).
test:
	uv run pytest

# Run the suite with a coverage report (opt-in; NOT part of `make test`, so a
# bare run stays fast). Terminal report only; .coverage/htmlcov are gitignored
# and removed by `make clean`.
cov:
	uv run pytest --cov=proactive_loop --cov-report=term-missing

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
