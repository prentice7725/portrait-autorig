import json

import numpy as np
import pytest
from PIL import Image

from portrait_autorig.bundle import load_portrait_bundle
from portrait_autorig.compiler import compile_bundle
from portrait_autorig.spine import export_rig_bundle


def write_bundle(root, *, stage="production_repaired", layer_path="layers/face.png"):
    (root / "layers").mkdir(parents=True)
    image = np.zeros((32, 32, 4), np.uint8)
    image[4:28, 4:28] = (180, 170, 160, 255)
    Image.fromarray(image, mode="RGBA").save(root / "original.png")
    if layer_path == "layers/face.png":
        Image.fromarray(image, mode="RGBA").save(root / "layers" / "face.png")
    manifest = {
        "format": "portrait-bundle",
        "version": "1.0",
        "canvas": {
            "width": 32, "height": 32,
            "coordinate_system": "top-left-y-down",
            "color_space": "srgb", "alpha": "straight",
        },
        "semantics": {"schema": "portrait-semantic-tags", "version": "v3", "z_order": ["face"]},
        "original": "original.png",
        "layers": {"face": {"path": layer_path, "source_tag": "face"}},
        "layer_contract": {"canonical_stage": stage},
    }
    with open(root / "manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)


def test_bundle_reader_accepts_only_production_repaired_layers(tmp_path):
    write_bundle(tmp_path)
    asset = load_portrait_bundle(tmp_path)
    assert set(asset.layers) == {"face"}
    assert asset.legacy_repair_applied is False


def test_bundle_reader_rejects_a_stage_that_could_be_repaired_twice(tmp_path):
    write_bundle(tmp_path, stage="guarded")
    with pytest.raises(ValueError, match="production_repaired"):
        load_portrait_bundle(tmp_path)


def test_bundle_path_cannot_escape_the_file_seam(tmp_path):
    write_bundle(tmp_path, layer_path="../original.png")
    with pytest.raises(ValueError, match="escapes"):
        load_portrait_bundle(tmp_path)


def test_bundle_compile_never_calls_legacy_repair(tmp_path, monkeypatch):
    bundle = tmp_path / "input.portrait"
    output = tmp_path / "output.rig"
    bundle.mkdir()
    write_bundle(bundle)

    import portrait_autorig.legacy_repair as legacy_repair

    def forbidden(*args, **kwargs):
        raise AssertionError("Portrait Bundle was repaired twice")

    monkeypatch.setattr(legacy_repair, "repair_portrait_layers", forbidden)
    manifest_path = compile_bundle(str(bundle), str(output))
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["source"]["legacy_repair_applied"] is False
    assert manifest["parts"]

    spine_path = export_rig_bundle(str(output), str(tmp_path / "spine"))
    assert spine_path.endswith(".json")
