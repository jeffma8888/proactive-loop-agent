"""Unit tests for TestPostureCollector's INTERNAL pure helper.

Scope is deliberately narrow: only the fiddly filename/dir classification helper
`_is_test_file`, which decides whether a candidate code file is a *test* or a
*source* file. The black-box collector behaviors (synthetic workspaces exercised
through the public ``collect()`` API and the ``pla signals`` CLI) belong to the
feature's behavior suite (``test_iter16_behavior.py``); this module needs no
filesystem and stays fast + deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.collectors.test_posture import _is_test_file


class TestIsTestFileByName:
    @pytest.mark.parametrize(
        "name, expected",
        [
            # (a) name starts with test_
            ("test_main.py", True),
            ("test_utils.ts", True),
            # (b) stem ends with _test
            ("main_test.go", True),
            ("handler_test.rs", True),
            # (c) name contains .test.
            ("widget.test.js", True),
            ("Button.test.ts", True),
            # (d) name contains .spec.
            ("widget.spec.ts", True),
            ("service.spec.js", True),
            # plainly-named source files are NOT tests
            ("main.py", False),
            ("server.go", False),
            ("app.js", False),
            # a bare "test.py" is neither test_-prefixed nor _test-suffixed, and
            # sits in no test dir here -> source (only the exact forms count).
            ("test.py", False),
            # "contest_foo.py" must NOT be caught by the _test suffix rule.
            ("contest_helpers.py", False),
        ],
    )
    def test_name_forms(self, name: str, expected: bool) -> None:
        assert _is_test_file(Path("proj") / name) is expected


class TestIsTestFileByDirectory:
    @pytest.mark.parametrize("dirname", ["tests", "test", "__tests__"])
    def test_file_under_test_dir_is_test(self, dirname: str) -> None:
        """(e) a plainly-named file under a test dir is classified as a test."""
        rel = Path("pkg") / dirname / "helpers.py"
        assert _is_test_file(rel) is True

    def test_source_under_ordinary_dir_is_not_test(self) -> None:
        assert _is_test_file(Path("pkg") / "sub" / "mod.py") is False

    def test_intermediate_only_not_the_filename(self) -> None:
        """The filename segment itself is never treated as a test-dir name."""
        # A directory literally named "tests" at any intermediate level counts,
        # but a file whose own stem happens to be "test" does not (covered above).
        assert _is_test_file(Path("a") / "b" / "tests" / "c" / "mod.py") is True
