"""Compile a PortraitAsset into a self-contained Rig Bundle."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from .assembly import (
    ASSEMBLY_FORMAT, ASSEMBLY_SCHEMA_COMMIT, ASSEMBLY_SCHEMA_ID,
    ASSEMBLY_SCHEMA_PATH, ASSEMBLY_SCHEMA_PIN, ASSEMBLY_SCHEMA_VENDOR,
    ASSEMBLY_VERSION,
    AssemblyAsset, load_assembly_bundle, resolve_rig_intent_coordinates,
)
from .bundle import PortraitAsset, load_legacy_run, load_portrait_bundle
from .physics import physics_spec_from_rig_intent
from .rig_bundle import load_rig_bundle
from .project import create_rig_project
from .rig import build_rig, rig_preflight, write_rig_project
from .soft_morph import TARGET_ALIASES


def compile_asset(asset: PortraitAsset, output_dir: str | os.PathLike[str], *,
                  gradient_tags=(), contour_tags=(), island_policy="separate",
                  clip_masks=(), boundary_stitches=(), physics=None) -> str:
    preflight = rig_preflight(asset.layers, original_rgba=asset.original,
                              body_remainder=asset.body_remainder)
    if preflight["status"] == "INCOMPATIBLE":
        messages = "; ".join(item["message"] for item in preflight["warnings"])
        raise ValueError(f"Portrait Bundle is not rig-compatible: {messages}")
    output = Path(output_dir)
    manifest, images = build_rig(
        asset.layers,
        original_rgba=asset.original,
        body_remainder=asset.body_remainder,
        frame_size=asset.original.shape[:2],
        gradient_tags=gradient_tags,
        contour_tags=contour_tags,
        island_policy=island_policy,
        clip_masks=clip_masks,
        boundary_stitches=boundary_stitches,
        physics=physics,
        run_id=asset.source_id,
        tag_version=asset.tag_version,
        preflight=preflight,
    )
    if manifest["rest_fidelity"]["status"] == "fail":
        raise ValueError(
            "rig rest pose differs from the canonical Portrait Bundle composite: "
            f"{manifest['rest_fidelity']}"
        )
    output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(asset.original, mode="RGBA").save(output / "portrait_original.png")
    manifest["source"]["portrait_bundle"] = asset.source_id
    manifest["source"]["legacy_repair_applied"] = asset.legacy_repair_applied
    manifest_path = write_rig_project(str(output), "portrait", manifest, images)
    create_rig_project(
        output, manifest, images, source=asset.root, source_kind="portrait",
        source_id=asset.source_id,
    )
    return manifest_path


def compile_bundle(bundle_dir: str, output_dir: str, *, gradient_tags=(), contour_tags=(), island_policy="separate",
                   clip_masks=(), boundary_stitches=(), physics=None) -> str:
    return compile_asset(load_portrait_bundle(bundle_dir), output_dir,
                         gradient_tags=gradient_tags, contour_tags=contour_tags,
                         island_policy=island_policy, clip_masks=clip_masks,
                         boundary_stitches=boundary_stitches, physics=physics)


def compile_legacy_run(run_dir: str, output_dir: str, *, gradient_tags=(), contour_tags=(), island_policy="separate",
                       clip_masks=(), boundary_stitches=(), physics=None) -> str:
    return compile_asset(load_legacy_run(run_dir), output_dir,
                         gradient_tags=gradient_tags, contour_tags=contour_tags,
                         island_policy=island_policy, clip_masks=clip_masks,
                         boundary_stitches=boundary_stitches, physics=physics)


def compile_assembly_asset(asset: AssemblyAsset, output_dir: str | os.PathLike[str], *,
                           gradient_tags=(), contour_tags=(), island_policy="separate",
                           clip_masks=(), boundary_stitches=(), physics=None) -> str:
    """Compile an Assembly Bundle v0.2 (`assembly.load_assembly_bundle`) into
    a Rig Bundle -- the "AutoRig Assembly input seam" (Master doc #22 STEP
    2). Every Stage A-D derivation in `build_rig` (remainder split, eye
    split, anchors, depth, weight, mesh) runs exactly as it does for
    Portrait Bundle input; the differences are `original_rgba=None` (an
    Assembly Bundle has no donor photo to compare against -- the Assembly
    reader must not read one), `draw_order=asset.draw_order` (Composer's
    authored paint order, not AutoRig's own canonical table),
    `rest_reference=asset.reference` -- rest_fidelity is checked against
    Composer's own rendered `reference.png` (the real Assembly Truth, Master
    doc #2), not a composite rebuilt from the same layers the rig itself
    was derived from -- and `rig_intent=asset.rig_intent`, which supplies an
    optional Composer motion hint for the generated chest base.  When no hint
    is present, AutoRig derives an editable first cage from the character's
    topwear geometry.  Final corrections and calibration belong to the Rig
    Project authoring layer.
    """
    resolved_rig_intent, rig_intent_resolution = resolve_rig_intent_coordinates(
        asset.rig_intent, asset.instance_geometry, asset.canvas, set(TARGET_ALIASES)
    )
    # Preserve the legacy generated-base seed when a uniquely resolved
    # Composer motion hint is present. Final calibration remains authoring.
    if physics is None:
        physics = physics_spec_from_rig_intent(resolved_rig_intent)
    preflight = rig_preflight(asset.layers, original_rgba=None,
                              body_remainder=asset.body_remainder,
                              rig_intent=resolved_rig_intent)
    if preflight["status"] == "INCOMPATIBLE":
        messages = "; ".join(item["message"] for item in preflight["warnings"])
        raise ValueError(f"Input Bundle is not rig-compatible: {messages}")
    output = Path(output_dir)
    # Preserve a one-to-one Composer instance binding on ordinary semantic
    # parts where flattening did not lose identity.  Variant members retain
    # their exact instance id inside build_rig.
    by_tag: dict[str, list[str]] = {}
    for instance_id in asset.instance_draw_order:
        geometry = asset.instance_geometry.get(instance_id) or {}
        tag = geometry.get("semantic")
        if tag is not None and geometry.get("included_in_semantic_layer"):
            by_tag.setdefault(tag, []).append(instance_id)
    source_instance_ids = {
        tag: ids[0] for tag, ids in by_tag.items() if len(ids) == 1
    }
    manifest, images = build_rig(
        asset.layers,
        original_rgba=None,
        body_remainder=asset.body_remainder,
        frame_size=(asset.canvas[1], asset.canvas[0]),
        draw_order=asset.draw_order,
        rest_reference=asset.reference,
        rig_intent=resolved_rig_intent,
        gradient_tags=gradient_tags,
        contour_tags=contour_tags,
        island_policy=island_policy,
        clip_masks=clip_masks,
        boundary_stitches=boundary_stitches,
        physics=physics,
        run_id=asset.source_id,
        variant_sets=asset.variant_sets,
        expression_presets=asset.expressions,
        variant_layers=asset.instance_layers,
        variant_reference_visibility=asset.variant_visibility,
        instance_to_tag=asset.instance_to_tag,
        variant_draw_order=[asset.instance_to_tag[i] for i in asset.instance_draw_order],
        preflight=preflight,
        provenance=asset.provenance,
        source_instance_ids=source_instance_ids,
    )
    if asset.source_kind == "rig_bundle":
        manifest["source"]["rig_bundle_schema"] = json.loads(json.dumps(asset.source_schema))
    else:
        manifest["source"]["assembly_schema"] = {
            "format": ASSEMBLY_FORMAT, "version": ASSEMBLY_VERSION,
            "vendor": ASSEMBLY_SCHEMA_VENDOR,
            "upstream_commit": ASSEMBLY_SCHEMA_COMMIT,
            "schema_id": ASSEMBLY_SCHEMA_ID,
            "schema_file": ASSEMBLY_SCHEMA_PATH.name,
            "pin": ASSEMBLY_SCHEMA_PIN,
        }
    manifest["source"]["input_kind"] = asset.source_kind
    manifest["source"]["rig_intent"] = json.loads(json.dumps(asset.rig_intent))
    manifest["source"]["source_metadata"] = json.loads(json.dumps(asset.source_metadata))
    manifest["source"]["capability_limits"] = [
        "AutoRig compiles separate layer meshes; full-body joints, IK, and walking/gait generation are outside this contract"
    ]
    if asset.expression_intent:
        manifest["source"]["expression_intent"] = json.loads(json.dumps(asset.expression_intent))
    manifest["source"]["rig_intent_resolution"] = rig_intent_resolution
    if manifest["rest_fidelity"]["status"] == "fail":
        raise ValueError(
            "rig rest pose differs from the input bundle's own reference.png: "
            f"{manifest['rest_fidelity']}"
        )
    output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(asset.reference, mode="RGBA").save(output / "reference.png")
    source_key = "rig_bundle" if asset.source_kind == "rig_bundle" else "assembly_bundle"
    manifest["source"][source_key] = asset.source_id
    manifest["source"]["reference"] = "reference.png"
    manifest_path = write_rig_project(str(output), "portrait", manifest, images)
    create_rig_project(
        output, manifest, images, source=asset.root, source_kind=asset.source_kind,
        source_id=asset.source_id, instance_ids=list(asset.instance_draw_order),
    )
    return manifest_path


def compile_assembly_bundle(bundle_dir: str, output_dir: str, *,
                            gradient_tags=(), contour_tags=(), island_policy="separate",
                            clip_masks=(), boundary_stitches=(), physics=None) -> str:
    return compile_assembly_asset(load_assembly_bundle(bundle_dir), output_dir,
                                  gradient_tags=gradient_tags, contour_tags=contour_tags,
                                  island_policy=island_policy, clip_masks=clip_masks,
                                  boundary_stitches=boundary_stitches, physics=physics)


def compile_rig_bundle(bundle_dir: str, output_dir: str, *,
                       gradient_tags=(), contour_tags=(), island_policy="separate",
                       clip_masks=(), boundary_stitches=(), physics=None) -> str:
    """Compile Composer Rig Bundle v0.4 through the Assembly compiler seam."""
    return compile_assembly_asset(load_rig_bundle(bundle_dir), output_dir,
                                  gradient_tags=gradient_tags, contour_tags=contour_tags,
                                  island_policy=island_policy, clip_masks=clip_masks,
                                  boundary_stitches=boundary_stitches, physics=physics)
