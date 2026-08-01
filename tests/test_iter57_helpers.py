"""Unit tests for the ``collectors`` verb's INTERNAL helpers.

Scope is deliberately narrow (mirroring ``test_iter56_helpers.py``'s
``_render_html`` tests and iter-48's ``_TOOL_CATALOG`` discipline): only the
pure, disk-free helpers that carry the correctness hazards of the catalog —
(1) the load-bearing anti-rot drift-guard binding ``_COLLECTOR_CATALOG``'s key
set to the LIVE collector registry, (2) the ``--json`` payload being an EXPLICIT
two-key allowlist (never a leaked model dump), and (3) the human/JSON forms
describing the identical, name-ascending set. The black-box ``pla collectors``
CLI behaviors (full stdout through ``main(argv)``, exit codes, argparse guards)
belong to the feature's behavior suite; this module imports the private helpers
directly, touches no disk, and stays fast + deterministic.
"""

from __future__ import annotations

from proactive_loop.cli import (
    _COLLECTOR_CATALOG,
    _collectors_json_payload,
    _render_collectors,
)
from proactive_loop.collectors import all_collectors


class TestCatalogDriftGuard:
    def test_catalog_key_set_equals_live_registry(self) -> None:
        # The anti-rot coupling: a collector added to or dropped from the registry
        # without a matching catalog edit turns this RED (mirrors _TOOL_CATALOG vs
        # ToolRegistry.tool_names()). This is the load-bearing correctness claim.
        assert set(_COLLECTOR_CATALOG) == {c.name for c in all_collectors()}

    def test_catalog_has_twelve_entries(self) -> None:
        assert len(_COLLECTOR_CATALOG) == 12
        assert len(all_collectors()) == 12

    def test_every_description_is_a_non_empty_string(self) -> None:
        for name, description in _COLLECTOR_CATALOG.items():
            assert isinstance(name, str) and name
            assert isinstance(description, str) and description.strip()

    def test_no_description_leads_with_another_collectors_name(self) -> None:
        # Each description describes ONLY its own collector: its FIRST token must
        # not be a DIFFERENT collector's name (which would misfile it in the
        # black-box "leading token" name-set check).
        names = set(_COLLECTOR_CATALOG)
        for name, description in _COLLECTOR_CATALOG.items():
            first_token = description.split()[0].rstrip(":").lower()
            assert first_token not in (names - {name})


class TestJsonPayload:
    def test_exactly_one_top_level_key(self) -> None:
        payload = _collectors_json_payload()
        assert set(payload.keys()) == {"collectors"}
        assert isinstance(payload["collectors"], list)

    def test_each_entry_is_exact_two_key_allowlist(self) -> None:
        # Explicit allowlist, never model_dump: exactly {name, description}.
        for entry in _collectors_json_payload()["collectors"]:
            assert set(entry.keys()) == {"name", "description"}
            assert isinstance(entry["name"], str) and entry["name"]
            assert isinstance(entry["description"], str) and entry["description"]

    def test_names_equal_sorted_registry(self) -> None:
        payload = _collectors_json_payload()
        emitted = [c["name"] for c in payload["collectors"]]
        assert emitted == sorted(c.name for c in all_collectors())

    def test_payload_is_pure_and_stable(self) -> None:
        # No hidden input: repeated calls return equal documents.
        assert _collectors_json_payload() == _collectors_json_payload()


class TestHumanRender:
    def test_lists_every_collector_ascending(self) -> None:
        rendered = _render_collectors()
        # The set of collector names appearing as a line's leading token equals
        # the registry, in ascending order.
        registry = sorted(c.name for c in all_collectors())
        leading = [
            line.strip().split()[0]
            for line in rendered.splitlines()
            if line.strip() and line.strip().split()[0] in set(registry)
        ]
        assert leading == registry

    def test_human_and_json_describe_same_set(self) -> None:
        rendered = _render_collectors()
        registry = {c.name for c in all_collectors()}
        json_names = {c["name"] for c in _collectors_json_payload()["collectors"]}
        human_names = {
            line.strip().split()[0]
            for line in rendered.splitlines()
            if line.strip() and line.strip().split()[0] in registry
        }
        assert human_names == json_names == registry
