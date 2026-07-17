# Developer entry points. All targets run fully offline (scripted provider).
.PHONY: setup test demo clean

# Resolve and install the locked dependency set into a project virtualenv.
setup:
	uv sync

# Run the whole test suite (offline; no network, no API keys).
test:
	uv run pytest

# End-to-end demo: scan the fixture workspace, then auto-dispatch the single
# top AUTO_DISPATCH goal through the resilient loop -- all driven by the bundled
# scripted responses, so it never touches a network.
demo:
	uv run pla run \
		--workspace examples/fixture_workspace \
		--provider scripted \
		--scripted-responses examples/scripted_responses.json \
		--state-dir .pla_runs

# Remove generated run state and Python/pytest caches.
clean:
	rm -rf .pla_runs
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
