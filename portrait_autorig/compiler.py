"""Compile a PortraitAsset into a self-contained Rig Bundle."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from .assembly import AssemblyAsset, load_assembly_bundle
from .bundle import PortraitAsset, load_legacy_run, load_portrait_bundle
from .rig import build_rig, rig_preflight, write_rig_project


def compile_asset(asset: PortraitAsset, output_dir: str | os.PathLike[str], *,
                  gradient_tags=(), contour_tags=()) -> str:
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
    return write_rig_project(str(output), "portrait", manifest, images)


def compile_bundle(bundle_dir: str, output_dir: str, *, gradient_tags=(), contour_tags=()) -> str:
    return compile_asset(load_portrait_bundle(bundle_dir), output_dir,
                         gradient_tags=gradient_tags, contour_tags=contour_tags)


def compile_legacy_run(run_dir: str, output_dir: str, *, gradient_tags=(), contour_tags=()) -> str:
    return compile_asset(load_legacy_run(run_dir), output_dir,
                         gradient_tags=gradient_tags, contour_tags=contour_tags)


def compile_assembly_asset(asset: AssemblyAsset, output_dir: str | os.PathLike[str], *,
                           gradient_tags=(), contour_tags=()) -> str:
    """Compile an Assembly Bundle v0.2 (`assembly.load_assembly_bundle`) into
    a Rig Bundle -- the "AutoRig Assembly input seam" (Master doc #22 STEP
    2). Every Stage A-D derivation in `build_rig` (remainder split, eye
    split, anchors, depth, weight, mesh) runs exactly as it does for
    Portrait Bundle input; the differences are `original_rgba=None` (an
    Assembly Bundle has no donor photo to compare against -- the Assembly
    reader must not read one), `draw_order=asset.draw_order` (Composer's
    authored paint order, not AutoRig's own canonical table), and
    `rest_reference=asset.reference` -- rest_fidelity is checked against
    Composer's own rendered `reference.png` (the real Assembly Truth, Master
    doc #2), not a composite rebuilt from the same layers the rig itself
    was derived from.
    """
    preflight = rig_preflight(asset.layers, original_rgba=None,
                              body_remainder=asset.body_remainder)
    if preflight["status"] == "INCOMPATIBLE":
        messages = "; ".join(item["message"] for item in preflight["warnings"])
        raise ValueError(f"Assembly Bundle is not rig-compatible: {messages}")
    output = Path(output_dir)
    manifest, images = build_rig(
        asset.layers,
        original_rgba=None,
        body_remainder=asset.body_remainder,
        frame_size=(asset.canvas[1], asset.canvas[0]),
        draw_order=asset.draw_order,
        rest_reference=asset.reference,
        gradient_tags=gradient_tags,
        contour_tags=contour_tags,
        run_id=asset.source_id,
        preflight=preflight,
    )
    if manifest["rest_fidelity"]["status"] == "fail":
        raise ValueError(
            "rig rest pose differs from the Assembly Bundle's own reference.png: "
            f"{manifest['rest_fidelity']}"
        )
    output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(asset.reference, mode="RGBA").save(output / "reference.png")
    manifest["source"]["assembly_bundle"] = asset.source_id
    manifest["source"]["reference"] = "reference.png"
    return write_rig_project(str(output), "portrait", manifest, images)


def compile_assembly_bundle(bundle_dir: str, output_dir: str, *,
                            gradient_tags=(), contour_tags=()) -> str:
    return compile_assembly_asset(load_assembly_bundle(bundle_dir), output_dir,
                                  gradient_tags=gradient_tags, contour_tags=contour_tags)
