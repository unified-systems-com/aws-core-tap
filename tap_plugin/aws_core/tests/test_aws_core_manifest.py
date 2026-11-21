"""Validation tests for the AWS Core plugin.

Uses the centralized plugin validation system at all three levels.
Plugin-specific domain tests (defaults, config round-trips) are separate.
"""

import tomllib
from pathlib import Path

import pytest

from tap.plugin_testing import find_plugin_source_root
from tap_plugins.validate.service import validate_plugin

PLUGIN_ROOT = find_plugin_source_root(__file__)

pytestmark = pytest.mark.skipif(
    PLUGIN_ROOT is None,
    reason="source-layout validation needs the plugin source tree; installed as a wheel here (delegated to the plugin repo's own build).",
)


def _manifest_path() -> Path:
    """Locate tap-plugin.toml across legacy and package-mode layouts.

    Package-mode moves the manifest into the namespace package
    (tap_plugin/<slug>/tap-plugin.toml); legacy kept it at the plugin root.
    """
    legacy = PLUGIN_ROOT / "tap-plugin.toml"
    if legacy.is_file():
        return legacy
    return next((PLUGIN_ROOT / "tap_plugin").glob("*/tap-plugin.toml"))


def _declared_model_count() -> int:
    """Number of models declared in the plugin manifest.

    Derived from tap-plugin.toml so adding a model never breaks this test on
    a hardcoded count — the invariant is "every declared model loads/creates",
    not a magic number.
    """
    manifest = tomllib.loads(_manifest_path().read_text())
    return len(manifest.get("models", {}))


# Each validation level is one build of the whole plugin, and the runs level creates every declared
# model's nodes and edges inside a rolled-back transaction. One build per (level, strict) is shared by
# the tests that read it: each test still asserts on its own, in any order, against the same result a
# fresh build would give.


@pytest.fixture(scope="module")
def structure_result():
    return validate_plugin(PLUGIN_ROOT, level="structure")


@pytest.fixture(scope="module")
def strict_structure_result():
    return validate_plugin(PLUGIN_ROOT, level="structure", strict=True)


@pytest.fixture(scope="module")
def loads_result():
    return validate_plugin(PLUGIN_ROOT, level="loads")


@pytest.fixture(scope="module")
def _runs_builds() -> dict:
    return {}


@pytest.fixture
def runs_build(_runs_builds, db):
    """The runs-level result, with the Entity count read just before and just after the build.

    Built once, by whichever runs test comes first, inside that test's own transaction and under the
    harness's per-test caller context (the runs level writes through the service boundary, which
    needs the test actor); later tests reuse it.
    """
    from tap_grid.models import Entity

    if "build" not in _runs_builds:
        count_before = Entity.objects.count()
        result = validate_plugin(PLUGIN_ROOT, level="runs")
        _runs_builds["build"] = (result, count_before, Entity.objects.count())
    return _runs_builds["build"]


@pytest.fixture
def runs_result(runs_build):
    return runs_build[0]


class TestAwsCoreStructure:
    def test_structure_passes(self, structure_result):
        assert structure_result.ok, structure_result.to_human()

    def test_strict_structure_passes(self, strict_structure_result):
        assert strict_structure_result.ok, strict_structure_result.to_human()


class TestAwsCoreLoads:
    def test_loads_passes(self, loads_result):
        assert loads_result.ok, loads_result.to_human()

    def test_all_declared_models_load(self, loads_result):
        model_check = next(c for c in loads_result.checks if c.id == "model-classes")
        info_msgs = [m for m in model_check.messages if m.severity == "info"]
        assert len(info_msgs) == _declared_model_count()


@pytest.mark.django_db
class TestAwsCoreRuns:
    def test_runs_passes(self, runs_result):
        assert runs_result.ok, runs_result.to_human()

    def test_all_declared_models_create(self, runs_result):
        node_check = next(c for c in runs_result.checks if c.id == "create-nodes")
        ok_msgs = [m for m in node_check.messages if "OK" in m.text]
        assert len(ok_msgs) == _declared_model_count()

    def test_edges_create(self, runs_result):
        edge_check = next(c for c in runs_result.checks if c.id == "create-edges")
        assert edge_check.status == "pass"

    def test_grift_imports(self, runs_result):
        grift_check = next(c for c in runs_result.checks if c.id == "grift-import")
        assert grift_check.status == "pass"

    def test_no_data_persisted(self, runs_build):
        from tap_grid.models import Entity

        result, count_before, count_after = runs_build
        assert result.ok
        assert count_after == count_before
        # And nothing the build wrote is visible from this test, whichever test ran it.
        assert Entity.objects.count() == count_before
