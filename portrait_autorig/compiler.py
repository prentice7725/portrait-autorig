"""Compile a PortraitAsset into a self-contained Rig Bundle."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from .bundle import PortraitAsset, load_legacy_run, load_portrait_bundle
from .rig import build_rig, write_rig_project


def compile_asset(asset: PortraitAsset, output_dir: str | os.PathLike[str], *,
                  gradient_tags=()) -> str:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(asset.original, mode="RGBA").save(output / "portrait_original.png")
    manifest, images = build_rig(
        asset.layers,
        body_remainder=asset.body_remainder,
        frame_size=asset.original.shape[:2],
        gradient_tags=gradient_tags,
        run_id=asset.source_id,
        tag_version=asset.tag_version,
    )
    manifest["source"]["portrait_bundle"] = asset.source_id
    manifest["source"]["legacy_repair_applied"] = asset.legacy_repair_applied
    return write_rig_project(str(output), "portrait", manifest, images)


def compile_bundle(bundle_dir: str, output_dir: str, *, gradient_tags=()) -> str:
    return compile_asset(load_portrait_bundle(bundle_dir), output_dir,
                         gradient_tags=gradient_tags)


def compile_legacy_run(run_dir: str, output_dir: str, *, gradient_tags=()) -> str:
    return compile_asset(load_legacy_run(run_dir), output_dir,
                         gradient_tags=gradient_tags)
