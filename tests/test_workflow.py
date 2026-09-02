from pathlib import Path

from portrait_autorig.workflow import (
    default_batch_output_path,
    default_output_path,
    discover_portrait_bundles,
    portrait_name,
)


def test_portrait_name_strips_bundle_suffix():
    assert portrait_name(Path("A001.portrait")) == "A001"
    assert portrait_name(Path("legacy-run")) == "legacy-run"


def test_default_single_output_is_sibling_rig():
    source = Path("portraits") / "A001.portrait"
    assert default_output_path(source) == Path("portraits") / "A001.rig"


def test_default_batch_output_is_rigs_folder():
    source = Path("portraits")
    assert default_batch_output_path(source) == Path("portraits") / "rigs"


def test_discover_portrait_bundles_is_non_recursive_by_default(tmp_path):
    (tmp_path / "A001.portrait").mkdir()
    (tmp_path / "A002.portrait").mkdir()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "A003.portrait").mkdir()
    (tmp_path / "not-a-bundle.txt").mkdir()

    found = discover_portrait_bundles(tmp_path)
    assert [path.name for path in found] == ["A001.portrait", "A002.portrait"]


def test_discover_portrait_bundles_can_recurse(tmp_path):
    (tmp_path / "A001.portrait").mkdir()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "A003.portrait").mkdir()

    found = discover_portrait_bundles(tmp_path, recursive=True)
    assert [path.name for path in found] == ["A001.portrait", "A003.portrait"]
