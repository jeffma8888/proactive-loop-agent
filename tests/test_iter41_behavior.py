"""Black-box behavior tests for iteration 41 --- rejecting **non-finite**
(``inf`` / ``-inf`` / ``nan``) values on the four upward-unbounded config floats
``Settings.auto_dispatch_min_score`` and ``RetryPolicy.{base_backoff_sec,
backoff_factor, max_backoff_sec}`` at model construction (ROADMAP #47).

Feature under test (SPEC section 3 "Key invariants", ``pm.md`` iter-41): the
existing ``Field(ge=0.0)`` / ``ge/le`` bounds let ``+inf`` slip through
(``inf >= 0.0`` is ``True``), so two live harms passed silently ---
``PLA_AUTO_DISPATCH_MIN_SCORE=inf`` silently *suppressed* the whole slate (every
finite goal score is ``< inf`` so the AUTO_DISPATCH gate never fired, yet
``pla run`` still exited 0), and an ``inf`` backoff made ``_backoff_delay`` compute
``min(raw, inf) == inf`` so a single retry ``sleep(inf)`` hung an unattended run
forever. This iteration closes the ``+inf`` mirror of the pre-existing negative
``auto_dispatch_min_score`` guard: a non-finite value is now refused at
construction (message contains ``finite``). No UPPER bound is added --- a large
FINITE threshold/backoff stays legal by design. ``-inf`` / ``nan`` were already
rejected by the ``ge``/``le`` bounds and stay rejected (regression-lock).
``jitter_frac`` (already fully bounded ``ge=0.0, le=1.0``) is untouched, and
``__version__`` stays ``0.1.1`` (additive hardening, no public-contract change).

ISOLATION CONTRACT (honored): these tests are written strictly against this
iteration's PUBLIC contract --- the iteration's PM "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` section 3 "Foundation contracts ->
Key invariants" --- and drive ONLY documented public surfaces: the public API
``proactive_loop.config.Settings`` / ``RetryPolicy`` / ``Settings.from_env`` and
the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its observable
stdout / stderr / exit code). **No file under ``src/`` was read, no engineer or
reviewer notes were read, and no ``git diff`` was consulted.** Every test is
fully offline: zero network, zero API keys, and NO ``--provider`` /
``--scripted-responses`` is passed because ``Settings.from_env()`` is constructed
(and thus validated) BEFORE any LLM client is built --- the config fault fires
fast regardless of provider (grounding fact confirmed in the spec and re-verified
live: the pre-existing negative-threshold guard already errors at this same
point). CLI tests use pytest's ``tmp_path`` (a real, EXISTING empty directory) as
the workspace so they pass the front-door workspace guard and reach config
construction, while never touching the in-repo tree (iter-15 leak lesson). Env
state is toggled exclusively through ``monkeypatch.setenv`` / ``delenv`` so
nothing leaks across tests.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import math

import pytest

pydantic = pytest.importorskip("pydantic")
from pydantic import ValidationError  # noqa: E402

import proactive_loop  # noqa: E402
from proactive_loop.cli import main  # noqa: E402
from proactive_loop.config import RetryPolicy, Settings  # noqa: E402

INF = float("inf")
NEG_INF = float("-inf")
NAN = float("nan")

_TRACEBACK = "Traceback (most recent call last)"

# Env-var name -> RetryPolicy field name for the three retry floats under test.
_RETRY_ENV_TO_FIELD = {
    "PLA_RETRY_BASE_BACKOFF_SEC": "base_backoff_sec",
    "PLA_RETRY_BACKOFF_FACTOR": "backoff_factor",
    "PLA_RETRY_MAX_BACKOFF_SEC": "max_backoff_sec",
}

_ALL_PLA_ENV = (
    "PLA_AUTO_DISPATCH_MIN_SCORE",
    *_RETRY_ENV_TO_FIELD.keys(),
    "PLA_RETRY_JITTER_FRAC",
    "PLA_RETRY_MAX_ATTEMPTS",
)


def _clear_env(monkeypatch) -> None:
    """Guarantee every PLA_* knob this suite touches is unset (defensive vs the
    ambient shell) so a rejection is provably caused by the value under test."""
    for name in _ALL_PLA_ENV:
        monkeypatch.delenv(name, raising=False)


def _assert_clean_config_rejection(rc, out, err, field: str) -> None:
    """Common assertions for a fast, offline config-validation rejection at the
    CLI: exit code exactly 1, an ``error:``-prefixed message on stderr naming the
    offending field, containing ``finite``, with no traceback and nothing on
    stdout, and provably NOT a provider/credential/scripted-file fault."""
    assert rc == 1, f"expected exit 1, got {rc}; stderr=\n{err}"
    assert rc != 2, "must not use the argparse/workspace-guard exit-2 class"
    assert rc != 0, "must not silently succeed"

    assert err.strip() != "", "expected an error message on stderr"
    assert err.lstrip().startswith("error:"), f"stderr must begin with 'error:':\n{err}"
    assert "finite" in err, f"stderr must contain 'finite':\n{err}"
    assert field in err, f"stderr must name the offending field {field!r}:\n{err}"

    assert _TRACEBACK not in err, f"traceback leaked to stderr:\n{err}"
    assert _TRACEBACK not in out, f"traceback leaked to stdout:\n{out}"
    assert "error:" not in out, f"error message leaked to stdout:\n{out}"
    assert "DECISION" not in out, f"a ranked slate must not render on rejection:\n{out}"

    low = err.lower()
    for forbidden in ("api key", "credential", "exhausted", "workspace not found"):
        assert forbidden not in low, (
            f"rejection must be the CONFIG fault, not {forbidden!r}:\n{err}"
        )


# ===========================================================================
# Behavior 1 --- inf on the threshold via env -> rejected at the CLI
# ===========================================================================
def test_behavior_01_env_inf_threshold_rejected(tmp_path, capsys, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "inf")

    rc = main(["scan", "--workspace", str(tmp_path)])
    captured = capsys.readouterr()

    _assert_clean_config_rejection(rc, captured.out, captured.err, "auto_dispatch_min_score")


# ===========================================================================
# Behavior 2 --- inf on each retry float via env -> rejected at the CLI
# ===========================================================================
@pytest.mark.parametrize("env_var,field", sorted(_RETRY_ENV_TO_FIELD.items()))
def test_behavior_02_env_inf_retry_float_rejected(
    env_var, field, tmp_path, capsys, monkeypatch
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(env_var, "inf")

    rc = main(["scan", "--workspace", str(tmp_path)])
    captured = capsys.readouterr()

    _assert_clean_config_rejection(rc, captured.out, captured.err, field)


# ===========================================================================
# Behavior 3 --- inf at direct construction -> ValidationError, str has 'finite'
# ===========================================================================
def test_behavior_03_settings_inf_raises_with_finite() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(auto_dispatch_min_score=INF)
    assert "finite" in str(exc.value), str(exc.value)


@pytest.mark.parametrize("field", sorted(_RETRY_ENV_TO_FIELD.values()))
def test_behavior_03_retrypolicy_inf_raises_with_finite(field) -> None:
    with pytest.raises(ValidationError) as exc:
        RetryPolicy(**{field: INF})
    assert "finite" in str(exc.value), str(exc.value)


# ===========================================================================
# Behavior 4 --- -inf and nan stay rejected (regression-lock; 'finite' NOT req'd)
# ===========================================================================
@pytest.mark.parametrize("bad", [NEG_INF, NAN], ids=["neg_inf", "nan"])
def test_behavior_04_settings_neg_inf_and_nan_rejected(bad) -> None:
    with pytest.raises(ValidationError):
        Settings(auto_dispatch_min_score=bad)


@pytest.mark.parametrize("field", sorted(_RETRY_ENV_TO_FIELD.values()))
@pytest.mark.parametrize("bad", [NEG_INF, NAN], ids=["neg_inf", "nan"])
def test_behavior_04_retrypolicy_neg_inf_and_nan_rejected(field, bad) -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(**{field: bad})


# ===========================================================================
# Behavior 5 --- valid finite config still loads unchanged (backward compat)
# ===========================================================================
def test_behavior_05_defaults_unchanged() -> None:
    s = Settings()
    assert s.auto_dispatch_min_score == 4.0
    rp = RetryPolicy()
    assert rp.base_backoff_sec == 1.0
    assert rp.backoff_factor == 2.0
    assert rp.max_backoff_sec == 60.0
    assert rp.jitter_frac == 0.1


def test_behavior_05_large_finite_still_legal_no_upper_bound() -> None:
    assert Settings(auto_dispatch_min_score=1_000_000.0).auto_dispatch_min_score == 1_000_000.0
    assert RetryPolicy(max_backoff_sec=1_000_000.0).max_backoff_sec == 1_000_000.0


def test_behavior_05_from_env_unset_returns_defaults(monkeypatch) -> None:
    _clear_env(monkeypatch)
    s = Settings.from_env()
    assert s.auto_dispatch_min_score == 4.0
    assert s.retry.base_backoff_sec == 1.0
    assert s.retry.backoff_factor == 2.0
    assert s.retry.max_backoff_sec == 60.0


def test_behavior_05_from_env_valid_finite_override_applies(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "2.5")
    monkeypatch.setenv("PLA_RETRY_MAX_BACKOFF_SEC", "120")
    s = Settings.from_env()
    assert s.auto_dispatch_min_score == 2.5
    assert s.retry.max_backoff_sec == 120.0


# ===========================================================================
# Behavior 6 --- jitter_frac is untouched (still rejects inf via its le=1.0 bound)
# ===========================================================================
def test_behavior_06_jitter_frac_inf_still_rejected() -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(jitter_frac=INF)


def test_behavior_06_jitter_frac_valid_bounds_unchanged() -> None:
    # A representative in-range value still constructs; the field's contract
    # (ge=0.0, le=1.0) is unchanged by this iteration.
    assert RetryPolicy(jitter_frac=0.0).jitter_frac == 0.0
    assert RetryPolicy(jitter_frac=1.0).jitter_frac == 1.0


# ===========================================================================
# Behavior 7 --- happy path unchanged: version pinned, deps unchanged, math stdlib
# ===========================================================================
def test_behavior_07_version_pinned() -> None:
    assert proactive_loop.__version__ == "0.1.1"


def test_behavior_07_pydantic_remains_sole_runtime_third_party_dep() -> None:
    # The only stdlib addition permitted is ``math``; no new runtime third-party
    # dependency may appear. Assert the distribution's declared *runtime* requires
    # (those without an ``extra ==`` environment marker, which are dev-only).
    requires = importlib_metadata.requires("proactive-loop-agent") or []
    runtime = [r for r in requires if "extra ==" not in r and "extra==" not in r]
    names = {r.split(";")[0].split("[")[0].split()[0].split(">=")[0].split("==")[0].strip().lower()
             for r in runtime}
    assert names == {"pydantic"}, f"unexpected runtime dependencies: {sorted(names)} (raw={runtime})"


def test_behavior_07_math_is_finite_available() -> None:
    # ``math`` is stdlib; guarding non-finite values must not pull in a new dep.
    assert math.isfinite(1.0) is True
    assert math.isfinite(INF) is False
    assert math.isfinite(NAN) is False
