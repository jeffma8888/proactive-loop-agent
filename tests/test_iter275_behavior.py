"""Black-box behavior tests for foundry iteration 317 -- ``pyproject.toml`` publishes
``[project.urls]``, trove ``classifiers`` and ``keywords``, every entry bound to a live
in-repo source, shipped net-zero on the collected count.

WHY THIS ITERATION EXISTS. Package metadata is the one surface an installer shows WITHOUT
the README (``pip show``, ``uv tree``, an index page). Before this commit it carried no
Homepage, no Repository and no ``Typing :: Typed`` classifier, although the wheel ships a
PEP 561 ``py.typed`` marker and the README's only GitHub URL names the repository. Free
text in a manifest is a new prose-vs-code drift site, so each entry is bound to the fact
that backs it: the URLs to the README's canonical GitHub URL, the interpreter classifiers
to the CI matrix, the typing classifier to the marker file, the license classifier to the
``license`` table, and each keyword to a token of ``description`` (or a declared runtime
dependency).

WHAT THIS MODULE GRADES: the three Expected Behaviors of the iteration spec, one item
each -- the module is capped at THREE collected items because the ship is net-zero: the
three retired duplicate tests fund exactly these three, and a fourth would breach the
permanent ``MIN_BINDING_HEADROOM`` wall ``tests/test_iter263_behavior.py`` owns. The
``uv.lock`` no-drift proof (``uv lock --check --offline`` exit 0, lock byte-identical) is a
commit-time measurement that belongs in the tester's report, not in a test that would
spawn ``uv`` from inside ``uv``.

ISOLATION CONTRACT (honored). Every assertion is written from the spec's Expected
Behaviors; no module under ``src/`` was read. The artifact under test IS the manifest,
so it is read with ``tomllib`` (the convention of 21 sibling modules), and the
installer-facing surface is read back through ``importlib.metadata`` from the
distribution ``uv sync`` installed -- the same route ``pip show`` takes.
"""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import metadata
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DIST_NAME = "proactive-loop-agent"
_PY_CLASSIFIER = re.compile(r"^Programming Language :: Python :: (\d+\.\d+)$")
_GITHUB_REPO = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def _project() -> dict[str, object]:
    """The ``[project]`` table of the manifest this commit ships."""
    manifest = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest["project"]
    assert isinstance(project, dict)
    return project


def _readme_repo_url() -> str:
    """The ONE GitHub ``owner/repo`` the human-owned README links, as a canonical URL."""
    readme = (_REPO / "README.md").read_text(encoding="utf-8")
    pairs = {(owner, repo) for owner, repo in _GITHUB_REPO.findall(readme)}
    assert len(pairs) == 1, (
        f"the README must name exactly one GitHub repository to bind the URLs to; found {pairs}"
    )
    ((owner, repo),) = pairs
    return f"https://github.com/{owner}/{repo}"


def _ci_matrix_versions() -> set[str]:
    """``strategy.matrix.python-version`` of the CI workflow, parsed without a YAML dependency."""
    workflow = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    match = re.search(r"python-version:\s*\[([^\]]*)\]", workflow)
    assert match is not None, "ci.yml must declare a python-version matrix list"
    versions = {v.strip().strip("\"'") for v in match.group(1).split(",") if v.strip()}
    assert versions, "the CI matrix must name at least one interpreter"
    return versions


# ===========================================================================
# Behavior 1 -- [project.urls] points back at the repository the README links.
# ===========================================================================
def test_b1_project_urls_homepage_and_repository_equal_the_readme_canonical_github_url() -> None:
    """Behavior 1: ``[project.urls]`` declares ``Homepage`` and ``Repository``; both equal the
    README's canonical GitHub URL (no trailing slash, no ``.git``), every further URL points
    INTO that repository, and the installed distribution surfaces the same pairs as
    ``Project-URL`` headers -- the ``pip show`` route.
    """
    canonical = _readme_repo_url()
    urls = _project().get("urls")
    assert isinstance(urls, dict), "pyproject.toml must publish a [project.urls] table"
    assert {"Homepage", "Repository"} <= set(urls), (
        f"[project.urls] must name Homepage and Repository; keys are {sorted(urls)}"
    )
    assert urls["Homepage"] == canonical, (urls["Homepage"], canonical)
    assert urls["Repository"] == canonical, (urls["Repository"], canonical)
    assert not canonical.endswith(("/", ".git")), canonical
    for label, url in urls.items():
        assert isinstance(url, str) and url.startswith(canonical), (
            f"[project.urls].{label} = {url!r} does not point into {canonical}"
        )
    installed = metadata(_DIST_NAME).get_all("Project-URL") or []
    published = {tuple(part.strip() for part in entry.split(",", 1)) for entry in installed}
    assert published == set(urls.items()), (
        "the installed distribution must surface exactly the manifest's URLs as Project-URL; "
        f"installed={sorted(published)} manifest={sorted(urls.items())}"
    )


# ===========================================================================
# Behavior 2 -- every classifier restates an in-repo fact: marker, matrix, license.
# ===========================================================================
def test_b2_every_classifier_is_bound_to_py_typed_the_ci_matrix_or_the_license_table() -> None:
    """Behavior 2: ``Typing :: Typed`` is present iff ``src/proactive_loop/py.typed`` exists;
    the ``Programming Language :: Python :: X.Y`` set equals the CI matrix and its minimum
    is the ``requires-python`` floor; the license classifier restates ``license.text``;
    NO classifier falls outside those three bound families; and the installed
    distribution surfaces the same list.
    """
    project = _project()
    classifiers = project.get("classifiers")
    assert isinstance(classifiers, list) and classifiers, (
        "pyproject.toml must publish a non-empty classifiers list"
    )
    assert len(set(classifiers)) == len(classifiers), f"duplicate classifier: {classifiers}"

    marker_ships = (_REPO / "src" / "proactive_loop" / "py.typed").is_file()
    assert ("Typing :: Typed" in classifiers) == marker_ships, (
        f"Typing :: Typed present={'Typing :: Typed' in classifiers} but py.typed exists={marker_ships}"
    )

    matrix = _ci_matrix_versions()
    declared = {m.group(1) for c in classifiers if (m := _PY_CLASSIFIER.match(c))}
    assert declared == matrix, (
        f"interpreter classifiers {sorted(declared)} must equal the CI matrix {sorted(matrix)}"
    )
    requires = project.get("requires-python")
    assert isinstance(requires, str)
    floor = re.fullmatch(r">=\s*(\d+\.\d+)", requires.strip())
    assert floor is not None, f"requires-python {requires!r} must be a >=X.Y floor"
    assert floor.group(1) == min(matrix, key=lambda v: tuple(map(int, v.split(".")))), (
        f"requires-python {requires!r} must floor at the oldest matrix interpreter {sorted(matrix)}"
    )

    license_table = project.get("license")
    assert isinstance(license_table, dict) and license_table.get("text") == "MIT", license_table
    license_classifiers = [c for c in classifiers if c.startswith("License :: ")]
    assert license_classifiers == ["License :: OSI Approved :: MIT License"], license_classifiers

    bound = set(license_classifiers) | {"Typing :: Typed"} | {
        c for c in classifiers if _PY_CLASSIFIER.match(c)
    }
    unbound = [c for c in classifiers if c not in bound]
    assert unbound == [], f"classifiers backed by no in-repo fact (a claim, not metadata): {unbound}"

    installed = metadata(_DIST_NAME).get_all("Classifier") or []
    assert sorted(installed) == sorted(classifiers), (installed, classifiers)


# ===========================================================================
# Behavior 3 -- keywords are tokens of the description or a declared dependency.
# ===========================================================================
def test_b3_keywords_are_lowercase_unique_tokens_of_description_or_a_runtime_dependency() -> None:
    """Behavior 3: ``keywords`` is a non-empty list of unique lowercase tokens, each either a
    whole word of ``description`` or the name of a declared runtime dependency (so no
    keyword advertises a capability the manifest does not otherwise state), and the
    installed distribution's ``Keywords`` header carries the same set.
    """
    project = _project()
    keywords = project.get("keywords")
    assert isinstance(keywords, list) and keywords, "pyproject.toml must publish keywords"
    assert all(isinstance(k, str) and k == k.lower() and k.strip() == k for k in keywords), keywords
    assert len(set(keywords)) == len(keywords), f"duplicate keyword: {keywords}"

    description = project.get("description")
    assert isinstance(description, str) and description
    words = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", description.lower()))
    dependencies = project.get("dependencies")
    assert isinstance(dependencies, list)
    dependency_names = {
        re.split(r"[\s<>=!~\[;]", d.strip(), maxsplit=1)[0].lower() for d in dependencies
    }
    unbound = [k for k in keywords if k not in words and k not in dependency_names]
    assert unbound == [], (
        f"keywords {unbound} are neither a word of description nor a runtime dependency; "
        f"description words={sorted(words)} dependencies={sorted(dependency_names)}"
    )

    header = metadata(_DIST_NAME).get("Keywords") or ""
    installed = {k.strip() for k in header.split(",") if k.strip()}
    assert installed == set(keywords), (installed, keywords)
