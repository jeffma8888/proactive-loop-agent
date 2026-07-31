"""Unit tests for the CLI's INTERNAL logging helpers (iteration 25).

Scope is deliberately narrow -- only the two pure/near-pure helpers behind the
``-v``/``--verbose`` flag:

* ``_verbosity_to_level(count)`` -- the pure count->level mapper.
* ``_configure_logging(level)`` -- the idempotent, level-0-no-op configurator
  that attaches at most one guarded stderr handler to the ``proactive_loop``
  package logger.

The end-to-end black-box behaviors (the flag inherited by every subcommand,
stdout cleanliness under ``-v``, the executor's live retry INFO record) belong to
the feature's behavior suite (``test_iter25_behavior.py``) and are exercised
through the public ``main([...])`` / ``GoalLoop`` surfaces there. This module
needs no filesystem and stays fast + deterministic.

ISOLATION: ``_configure_logging`` mutates PROCESS-GLOBAL logging state (it adds a
handler to a shared logger), so every test here runs inside an autouse fixture
that snapshots and fully restores the ``proactive_loop`` logger's handler list
and level. This guarantees the module leaks nothing into the rest of the suite --
a stale stderr handler bound to a torn-down capture stream is exactly the
cross-test hazard the fixture exists to prevent.
"""

from __future__ import annotations

import logging
import sys

import pytest

from proactive_loop.cli import (
    _CliLogHandler,
    _configure_logging,
    _verbosity_to_level,
)

_PKG = "proactive_loop"


@pytest.fixture(autouse=True)
def _restore_package_logger():
    """Snapshot + restore the package logger so no test leaks logging state."""
    logger = logging.getLogger(_PKG)
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    try:
        yield logger
    finally:
        # Drop anything a test attached, then reinstate the original state.
        for h in list(logger.handlers):
            if h not in saved_handlers:
                logger.removeHandler(h)
        logger.handlers[:] = saved_handlers
        logger.setLevel(saved_level)


def _cli_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if isinstance(h, _CliLogHandler)]


class TestVerbosityToLevel:
    """Behavior 2: the mapper is pure and returns the documented levels."""

    @pytest.mark.parametrize(
        "count, expected",
        [
            (-5, logging.WARNING),
            (-1, logging.WARNING),
            (0, logging.WARNING),  # 30
            (1, logging.INFO),     # 20
            (2, logging.DEBUG),    # 10
            (3, logging.DEBUG),
            (99, logging.DEBUG),
        ],
    )
    def test_maps_count_to_level(self, count, expected):
        assert _verbosity_to_level(count) == expected

    def test_returns_the_canonical_stdlib_ints(self):
        # Pin the exact stdlib integers the spec names, not just the constants.
        assert _verbosity_to_level(0) == 30
        assert _verbosity_to_level(1) == 20
        assert _verbosity_to_level(2) == 10

    def test_is_pure_no_logger_mutation(self):
        logger = logging.getLogger(_PKG)
        before_handlers = list(logger.handlers)
        before_level = logger.level
        for c in (-1, 0, 1, 2, 5):
            _verbosity_to_level(c)
        assert list(logger.handlers) == before_handlers
        assert logger.level == before_level


class TestConfigureLogging:
    """Behaviors 3 + 4: strict level-0 no-op, idempotent single stderr handler."""

    def test_level_warning_is_strict_no_op(self):
        logger = logging.getLogger(_PKG)
        before_handlers = list(logger.handlers)
        before_level = logger.level
        _configure_logging(logging.WARNING)
        # A level >= WARNING attaches nothing and changes no level.
        assert list(logger.handlers) == before_handlers
        assert logger.level == before_level
        assert _cli_handlers(logger) == []

    def test_verbose_attaches_exactly_one_stderr_handler(self):
        logger = logging.getLogger(_PKG)
        _configure_logging(logging.INFO)
        attached = _cli_handlers(logger)
        assert len(attached) == 1
        handler = attached[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr
        assert logger.level == logging.INFO

    def test_repeated_calls_are_idempotent(self):
        logger = logging.getLogger(_PKG)
        for _ in range(3):
            _configure_logging(logging.INFO)
        assert len(_cli_handlers(logger)) == 1

    def test_reconfigure_updates_level_without_stacking(self):
        logger = logging.getLogger(_PKG)
        _configure_logging(logging.INFO)
        _configure_logging(logging.DEBUG)
        assert len(_cli_handlers(logger)) == 1
        assert logger.level == logging.DEBUG

    def test_touches_only_the_package_logger_never_the_root(self):
        root = logging.getLogger()
        root_handlers_before = list(root.handlers)
        root_level_before = root.level
        _configure_logging(logging.DEBUG)
        assert list(root.handlers) == root_handlers_before
        assert root.level == root_level_before
