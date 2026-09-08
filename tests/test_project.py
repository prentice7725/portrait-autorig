from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from portrait_autorig.bundle import PortraitAsset
from portrait_autorig.compiler import compile_asset
from portrait_autorig.image import composite_layers
from portrait_autorig.project import (
    create_rig_project,
    load_rig_project,
    open_rig,
    reset_current_deformer_to_auto,
    reset_current_pose,
    reset_entire_rig_to_auto,
    reset_chest_to_auto,
    reset_chest_physics_to_auto,
    resolve_binding,
    resolve_rig,
    set_chest_cage_bounds,
    set_chest_cage_points,
    set_chest_keyform,
    set_chest_physics,
    set_chest_parameter_range,
)


def _manifest() -> dict:
    return {
        "version": "0.2",
        "canvas": {"width": 8, "height": 8},
        "parts": [
            {"name": "topwear", "tag": "topwear",
             "source_instance_id": "topwear_instance"},
            {"name": "front_hair", "tag": "front hair",
             "source_instance_id": "hair_instance"},
        ],
        "motion": {
            "upper_torso_parametric_deformer": {
                "target_instance": "topwear_instance",
                "target_part": "topwear",
                "target_tag": "topwear",
                "cage": {"bounds": [1, 1, 7, 7]},
                "keyforms": {"neutral": [[0, 0]]},
                "ranges_px": {"x": 6.0, "y": 6.0},
            }
        },
        "deformers": [],
    }


def _images() -> dict[str, np.ndarray]:
    image = np.zeros((4, 4, 4), dtype=np.uint8)
    image[..., 3] = 255
    return {"topwear": image, "front_hair": image.copy()}


def _points(offset=0.0) -> list[list[float]]:
    return [[float(index + offset), float(index * 2 + offset)] for index in range(24)]


def _source(root: Path) -> Path:
    root.mkdir()
    (root / "manifest.json").write_text('{"format":"portrait-assembly"}', encoding="utf-8")
    return root


def test_project_round_trip_keeps_generated_base_and_authoring_separate(tmp_path):
    source = _source(tmp_path / "A002.assembly")
    project = create_rig_project(
        tmp_path / "A002.rigproject", _manifest(), _images(),
        source=source, source_kind="assembly", source_id="A002.assembly",
    )

    assert (project.root / "project.json").is_file()
    assert (project.root / "source" / "assembly_reference.json").is_file()
    assert (project.root / "generated" / "portrait_rig_manifest.json").is_file()
    assert (project.root / "authoring" / "deformers.json").is_file()
    assert project.source_revision_status == "MATCH"
    assert project.resolved_manifest == project.generated_manifest

    project.set_deformer_override(
        "upper_torso",
        {"source_instance_id": "topwear_instance",
         "keyform_overrides": {"neutral": [[1, 2]]}},
    )
    project.save()
    reloaded = load_rig_project(project.root)

    assert reloaded.authoring["deformers"]["upper_torso"]["source_instance_id"] == "topwear_instance"
    assert reloaded.resolved_manifest["motion"]["upper_torso_parametric_deformer"]["keyforms"]["neutral"] == [[1, 2]]
    assert reloaded.generated_manifest["motion"]["upper_torso_parametric_deformer"]["keyforms"]["neutral"] == [[0, 0]]


def test_revision_mismatch_is_reported_without_discarding_corrections(tmp_path):
    source = _source(tmp_path / "A002.assembly")
    project = create_rig_project(
        tmp_path / "A002.rigproject", _manifest(), _images(), source=source,
        source_kind="assembly",
    )
    project.set_deformer_override(
        "upper_torso", {"source_instance_id": "topwear_instance",
                         "range_override": {"x": 9.0}},
    )
    project.save()
    (source / "manifest.json").write_text('{"format":"portrait-assembly","revision":2}', encoding="utf-8")

    reloaded = load_rig_project(project.root)
    assert reloaded.source_revision_status == "MISMATCH"
    assert "upper_torso" in reloaded.authoring["deformers"]


def test_binding_prefers_stable_instance_id_over_ambiguous_tag():
    manifest = {"parts": [
        {"name": "topwear_a", "tag": "topwear", "source_instance_id": "a"},
        {"name": "topwear_b", "tag": "topwear", "source_instance_id": "b"},
    ]}
    result = resolve_binding(manifest, {"source_instance_id": "b", "target_tag": "topwear"})
    assert result["status"] == "BOUND"
    assert result["strategy"] == "source_instance_id"
    assert result["target"]["target_part"] == "topwear_b"


def test_reset_semantics_are_distinct(tmp_path):
    project = create_rig_project(tmp_path / "A002.rigproject", _manifest(), _images())
    project.editor_state["current_pose"] = {"ParamBustY": 1}
    project.set_deformer_override("upper_torso", {"target_part": "topwear", "patch": {"x": 1}})
    reset_current_pose(project)
    assert project.editor_state["current_pose"] == {}
    assert "upper_torso" in project.authoring["deformers"]

    reset_current_deformer_to_auto(project, "upper_torso")
    assert project.authoring["deformers"] == {}

    project.set_deformer_override("upper_torso", {"target_part": "topwear", "patch": {"x": 1}})
    project.authoring["physics"] = {"upper_torso_driver": {"damping_ratio": 0.8}}
    reset_entire_rig_to_auto(project)
    assert project.authoring["deformers"] == {}
    assert project.authoring["physics"] == {}


def test_resolve_rig_does_not_mutate_generated_base():
    resolved, report = resolve_rig(
        _manifest(),
        {"deformers": {"upper_torso": {
            "source_instance_id": "topwear_instance",
            "cage_override": {"bounds": [0, 0, 8, 8]},
        }}},
    )
    assert report["status"] == "MATCH"
    assert resolved["motion"]["upper_torso_parametric_deformer"]["cage"]["bounds"] == [0, 0, 8, 8]


def test_chest_authoring_helpers_persist_cage_and_keyform_without_physics(tmp_path):
    manifest = _manifest()
    manifest["motion"]["upper_torso_parametric_deformer"]["cage"]["rest_points"] = _points()
    project = create_rig_project(tmp_path / "A002.rigproject", manifest, _images())
    set_chest_cage_bounds(project, [0, 1, 8, 9])
    set_chest_cage_points(project, _points(10))
    set_chest_keyform(project, "bust_y_pos", _points(20))
    project.save()

    loaded = load_rig_project(project.root)
    override = loaded.authoring["deformers"]["upper_torso"]
    assert override["target_instance"] == "topwear_instance"
    assert override["cage_override"]["bounds"] == [0.0, 1.0, 8.0, 9.0]
    assert override["keyform_overrides"]["bust_y_pos"] == _points(20)
    assert loaded.resolved_manifest["motion"]["upper_torso_parametric_deformer"]["cage"]["rest_point_deltas"][0] == [10.0, 10.0]
    assert "physics" not in loaded.resolved_manifest
    assert loaded.generated_manifest["motion"]["upper_torso_parametric_deformer"]["cage"]["bounds"] == [1, 1, 7, 7]

    reset_chest_to_auto(loaded)
    assert loaded.authoring["deformers"] == {}
    loaded.save()
    reloaded = load_rig_project(loaded.root)
    assert reloaded.authoring["deformers"] == {}
    assert reloaded.resolved_manifest == reloaded.generated_manifest

    with pytest.raises(ValueError):
        reloaded.set_chest_keyform("neutral", _points())


def test_r3_chest_physics_and_ranges_round_trip_separately_from_shape(tmp_path):
    manifest = _manifest()
    manifest["physics"] = {"upper_torso_driver": {
        "model": "inertial_relative_v2", "profile": "soft",
        "natural_frequency_hz": 1.8, "damping_ratio": 0.75,
        "lag_seconds_x": 0.0, "lag_seconds_y": 1.4,
        "max_displacement_px": 16.0,
    }}
    project = create_rig_project(tmp_path / "A002.rigproject", manifest, _images())
    set_chest_physics(project, {
        "profile": "springy", "input_mode": "translation", "enabled": True,
        "natural_frequency_hz": 2.7, "damping_ratio": 0.42,
        "lag_seconds_y": 0.8, "max_displacement_px": 9.5,
    })
    set_chest_parameter_range(project, {"x": 7.0, "y": 11.0})
    set_chest_keyform(project, "bust_y_pos", _points(20))
    with pytest.raises(ValueError):
        set_chest_physics(project, {"profile": "custom"})
    with pytest.raises(ValueError):
        set_chest_physics(project, {"input_mode": "angular_velocity"})
    with pytest.raises(ValueError):
        set_chest_physics(project, {"enabled": "yes"})
    with pytest.raises(ValueError):
        set_chest_physics(project, {"idle_lag_max_px": 0})
    project.save()

    loaded = load_rig_project(project.root)
    assert loaded.authoring["physics"]["upper_torso"]["damping_ratio"] == 0.42
    driver = loaded.resolved_manifest["physics"]["upper_torso_driver"]
    assert driver["natural_frequency_hz"] == 2.7
    assert driver["max_displacement_px"] == 9.5
    assert loaded.resolved_manifest["motion"]["upper_torso_parametric_deformer"]["ranges_px"] == {
        "x": 7.0, "y": 11.0,
    }
    assert loaded.generated_manifest["physics"]["upper_torso_driver"]["damping_ratio"] == 0.75
    assert (project.root / "authoring" / "physics.json").is_file()

    reset_chest_to_auto(loaded)
    assert loaded.authoring["deformers"] == {}
    assert loaded.authoring["physics"]["upper_torso"]["profile"] == "springy"
    loaded.save()
    after_shape_reset = load_rig_project(loaded.root)
    assert after_shape_reset.authoring["physics"]["upper_torso"]["natural_frequency_hz"] == 2.7

    reset_chest_physics_to_auto(after_shape_reset)
    assert "upper_torso" not in after_shape_reset.authoring["physics"]
    assert after_shape_reset.authoring["deformers"] == {}
    assert after_shape_reset.resolved_manifest["physics"]["upper_torso_driver"]["damping_ratio"] == 0.75


def test_open_legacy_rig_uses_separate_project_and_stays_match_after_save(tmp_path):
    source = tmp_path / "A002.rig"
    (source / "rig" / "images").mkdir(parents=True)
    manifest = _manifest()
    (source / "portrait_rig_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    for name, image in _images().items():
        from PIL import Image
        Image.fromarray(image, mode="RGBA").save(source / "rig" / "images" / f"{name}.png")
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*") if path.is_file()
    }

    project = open_rig(source)
    assert project.root == tmp_path / "A002.rigproject"
    assert {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*") if path.is_file()
    } == before
    assert not (source / "project.json").exists()

    project.set_deformer_override(
        "upper_torso", {"source_instance_id": "topwear_instance",
                         "range_override": {"x": 9.0}},
    )
    project.save()
    reloaded = load_rig_project(project.root)
    assert reloaded.source_revision_status == "MATCH"
    assert reloaded.resolved_manifest["motion"]["upper_torso_parametric_deformer"]["ranges_px"]["x"] == 9.0
    assert {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*") if path.is_file()
    } == before
    assert (project.root / "authoring" / "meta.json").is_file()
    meta = json.loads((project.root / "authoring" / "meta.json").read_text(encoding="utf-8"))
    assert meta["source_revision"] == project.source["source_revision"]


def test_compiler_emits_rig_project_without_changing_runtime_manifest_contract(tmp_path):
    canvas = 64
    layers = {}
    for tag, box in {
        "head": (18, 4, 46, 34), "face": (21, 10, 43, 30),
        "neck": (27, 30, 37, 43), "topwear": (10, 42, 54, 63),
    }.items():
        image = np.zeros((canvas, canvas, 4), dtype=np.uint8)
        x1, y1, x2, y2 = box
        image[y1:y2, x1:x2] = (180, 170, 160, 255)
        layers[tag] = image
    source = tmp_path / "A002.portrait"
    source.mkdir()
    original = composite_layers(layers, (canvas, canvas))
    path = compile_asset(
        PortraitAsset(source, original, layers, None, "v3", "A002.portrait"),
        tmp_path / "A002.rig",
    )
    project = load_rig_project(tmp_path / "A002.rig")
    runtime_manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    assert project.source["kind"] == "portrait"
    assert project.resolved_manifest == runtime_manifest
    assert project.generated_manifest["version"] == runtime_manifest["version"]
