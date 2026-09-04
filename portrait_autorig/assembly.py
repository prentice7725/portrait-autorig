"""Assembly Bundle v0.2 reader ("AutoRig Assembly input seam", Master doc
`SEETHROUGH_COMPOSER_AUTORIG_RESPONSIBILITY_VERSIONUP_MASTER_v0.2.md` #22
STEP 2).

Reads what `portrait-composer` actually writes
(`portrait_composer.bundle.write_assembly_bundle`), against that repo's real
schema (`schemas/portrait-assembly-v0.2.schema.json`):

    A001.assembly/
        manifest.json
        reference.png
        layers/<instance_id>.png
        expressions/, masks/, diagnostics/   (present, not yet read here)

AutoRig reads (directive #4): canvas, final instances/layers, draw_order,
the Assembly Reference, VariantSets, RigIntent, provenance. It must NOT
read: donor originals, source decomposition choices, or bake choices --
none of those live in an Assembly Bundle; Composer already resolved them.
Concretely, that means the missing-eyewhite derivation `rig.py` can run for
Portrait Bundle input (`original_rgba` comparison) never runs here: an
Assembly Bundle has no "original photo" to compare against, and asking for
one would be reading exactly the donor material this seam must not touch.

This module owns only the seam: Assembly Bundle -> the same
`{tag: full-canvas RGBA}` working set (plus an explicit `draw_order`) that
`rig.build_rig` already consumes for Portrait Bundle input, so every
existing Stage A-D derivation (remainder split, eye split, anchors, depth,
weight, mesh) runs completely unchanged regardless of which bundle produced
its input.

Positioning (scale -> rotate -> translate, same resampling filters) mirrors
`portrait_composer.render._positioned`/`_composite` exactly, so a rig
compiled from an Assembly Bundle can be checked against that bundle's own
`reference.png` (see `compiler.compile_assembly_asset`'s rest_fidelity
check) the same way Portrait Bundle input is checked against its own
canonical composite. This module does not import `portrait_composer`
(Architecture Invariant #15, Master doc #23: a versioned bundle contract
over a cross-repo private import) -- it reimplements the documented
positioning contract instead.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

__all__ = ["ASSEMBLY_FORMAT", "ASSEMBLY_VERSION", "ASSEMBLY_SCHEMA_VENDOR",
           "ASSEMBLY_SCHEMA_COMMIT", "ASSEMBLY_SCHEMA_ID", "ASSEMBLY_SCHEMA_PIN",
           "ASSEMBLY_SCHEMA_PATH", "AssemblyAsset", "validate_assembly_manifest",
           "load_assembly_bundle"]

ASSEMBLY_FORMAT = "portrait-assembly"
# Exact match, not a major-version prefix check: pre-1.0, a minor bump
# (0.2 -> 0.3) can freely be a breaking contract change (composer's own
# schema pins `"version": {"const": "0.2"}`), so a 0.3 bundle must fail
# loudly here rather than being read against the wrong field shapes.
ASSEMBLY_VERSION = "0.2"
# The schema is vendored from Composer rather than imported at runtime.  The
# commit is part of the input seam, so a future Composer schema change cannot
# silently alter what AutoRig accepts.
ASSEMBLY_SCHEMA_VENDOR = "portrait-composer"
ASSEMBLY_SCHEMA_COMMIT = "682f25e"
ASSEMBLY_SCHEMA_ID = "portrait-assembly-v0.2"
ASSEMBLY_SCHEMA_PIN = f"{ASSEMBLY_SCHEMA_VENDOR}@{ASSEMBLY_SCHEMA_COMMIT}:{ASSEMBLY_SCHEMA_ID}"
ASSEMBLY_SCHEMA_PATH = Path(__file__).with_name("schemas") / "portrait-assembly-v0.2.schema.json"


@dataclass(frozen=True)
class AssemblyAsset:
    root: Path
    canvas: tuple[int, int]            # (width, height)
    layers: dict[str, np.ndarray]      # semantic tag -> full-canvas RGBA
    body_remainder: np.ndarray | None
    draw_order: list[str]              # semantic tags, Composer's authored paint order
    rig_intent: dict[str, Any]
    variant_sets: dict[str, Any]
    expressions: dict[str, Any]
    # Composer members are LayerInstance ids; retain their positioned images
    # and semantic tags even when inactive so runtime swapping is lossless.
    instance_layers: dict[str, np.ndarray]
    instance_to_tag: dict[str, str]
    instance_draw_order: list[str]
    reference: np.ndarray              # Composer's own rendered reference.png
    source_id: str
    provenance: dict[str, Any]


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _schema_errors(manifest: Any) -> list[str]:
    """Validate the vendored Composer v0.2 structural contract.

    This deliberately stays dependency-free: the package must be able to
    preflight a bundle before optional tooling is installed.  Unknown fields
    remain allowed so Composer can add non-breaking metadata without making
    the AutoRig seam a second schema owner.
    """
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    if manifest.get("format") != ASSEMBLY_FORMAT:
        errors.append(f"format must be {ASSEMBLY_FORMAT!r}")
    if str(manifest.get("version", "")) != ASSEMBLY_VERSION:
        errors.append(f"version must be {ASSEMBLY_VERSION!r}")
    for key in ("assets", "instances", "composition"):
        if not isinstance(manifest.get(key), dict):
            errors.append(f"{key} must be an object")
    composition = manifest.get("composition")
    if isinstance(composition, dict):
        order = composition.get("draw_order")
        if not isinstance(order, list) or not order:
            errors.append("composition.draw_order must be a non-empty array")
        canvas = composition.get("canvas")
        if not isinstance(canvas, dict):
            errors.append("composition.canvas must be an object")
        else:
            for key in ("width", "height"):
                value = canvas.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                    errors.append(f"composition.canvas.{key} must be positive")
    assets = manifest.get("assets")
    instances = manifest.get("instances")
    if isinstance(assets, dict):
        for asset_id, asset in assets.items():
            if not isinstance(asset, dict):
                errors.append(f"asset {asset_id!r} must be an object")
            elif not isinstance(asset.get("semantic"), str) or not asset.get("semantic"):
                errors.append(f"asset {asset_id!r} must have semantic")
    if isinstance(assets, dict) and isinstance(instances, dict):
        for instance_id, inst in instances.items():
            if not isinstance(inst, dict):
                errors.append(f"instance {instance_id!r} must be an object")
                continue
            asset_ref = inst.get("asset_ref")
            if not isinstance(asset_ref, str) or not asset_ref:
                errors.append(f"instance {instance_id!r} must have asset_ref")
            elif not isinstance(assets.get(asset_ref), dict):
                errors.append(f"instance {instance_id!r} references unknown asset {asset_ref!r}")
    if isinstance(assets, dict) and isinstance(instances, dict) and isinstance(composition, dict):
        order = composition.get("draw_order")
        if isinstance(order, list):
            for instance_id in order:
                inst = instances.get(instance_id)
                if not isinstance(inst, dict):
                    errors.append(f"draw_order references invalid instance {instance_id!r}")
                    continue
                asset_ref = inst.get("asset_ref")
                if not isinstance(asset_ref, str) or not asset_ref:
                    errors.append(f"instance {instance_id!r} must have asset_ref")
                elif not isinstance(assets.get(asset_ref), dict):
                    errors.append(f"instance {instance_id!r} references unknown asset {asset_ref!r}")
    # Composer may optionally echo this pin in the manifest.  If present it
    # is an assertion, never a field AutoRig has to invent for old bundles.
    schema_ref = manifest.get("schema") or manifest.get("schema_ref")
    if isinstance(schema_ref, dict):
        vendor = schema_ref.get("vendor")
        commit = schema_ref.get("commit") or schema_ref.get("upstream_commit")
        if vendor is not None and vendor != ASSEMBLY_SCHEMA_VENDOR:
            errors.append(f"schema vendor must be {ASSEMBLY_SCHEMA_VENDOR!r}")
        if commit is not None and commit != ASSEMBLY_SCHEMA_COMMIT:
            errors.append(f"schema upstream commit must be {ASSEMBLY_SCHEMA_COMMIT!r}")
    return errors


@lru_cache(maxsize=1)
def _vendored_schema_metadata() -> dict[str, Any]:
    """Load and pin the checked-in schema descriptor before accepting input."""
    try:
        schema = _read_json(ASSEMBLY_SCHEMA_PATH)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"vendored Assembly schema is unavailable: {ASSEMBLY_SCHEMA_PATH}") from exc
    upstream = schema.get("x-upstream") or {}
    if (upstream.get("vendor") != ASSEMBLY_SCHEMA_VENDOR
            or upstream.get("commit") != ASSEMBLY_SCHEMA_COMMIT
            or upstream.get("schema_id") != ASSEMBLY_SCHEMA_ID):
        raise RuntimeError("vendored Assembly schema metadata does not match the pinned Composer commit")
    return schema


def validate_assembly_manifest(manifest: dict[str, Any]) -> None:
    """Raise a concise error when an Assembly manifest violates the vendored schema."""
    _vendored_schema_metadata()
    errors = _schema_errors(manifest)
    if errors:
        raise ValueError("Assembly Bundle schema validation failed: " + "; ".join(errors))


def _position(img: Image.Image, transform: dict[str, Any]) -> tuple[Image.Image, tuple[int, int]]:
    """`portrait_composer.render._positioned`, reimplemented against the
    documented contract: scale (LANCZOS) -> rotate (BICUBIC, expand,
    centre-adjusted) -> translate."""
    w, h = img.size
    scale_x = float(transform.get("scale_x", 1.0))
    scale_y = float(transform.get("scale_y", 1.0))
    if scale_x != 1.0 or scale_y != 1.0:
        new_w, new_h = max(1, round(w * scale_x)), max(1, round(h * scale_y))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        w, h = new_w, new_h
    ox, oy = 0, 0
    rotation = float(transform.get("rotation", 0.0))
    if rotation:
        pre_w, pre_h = w, h
        img = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
        w, h = img.size
        ox, oy = (w - pre_w) // 2, (h - pre_h) // 2
    x = round(float(transform.get("x", 0.0))) - ox
    y = round(float(transform.get("y", 0.0))) - oy
    return img, (x, y)


def load_assembly_bundle(directory: str | os.PathLike[str]) -> AssemblyAsset:
    """Read an Assembly Bundle directory into an `AssemblyAsset`.

    Instances are composited in `composition.draw_order` (required --
    AutoRig never invents one), skipping any instance that is not `visible`
    or has `opacity <= 0` -- exactly `portrait_composer.render._composite`'s
    own filter, so a VariantSet's inactive members (already reflected in
    their `visible` flag by Composer's own `variants.set_active`) are
    silently excluded here rather than needing their own handling. More
    than one visible instance sharing one semantic tag are composited
    together, in draw order, into that tag's one layer -- but only when
    Composer actually drew them contiguously; see the draw-order
    contiguity check below for why a gap is a hard error instead.
    """
    root = Path(directory).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"not an Assembly Bundle (missing manifest.json): {root}")
    manifest = _read_json(manifest_path)
    validate_assembly_manifest(manifest)
    if manifest.get("format") != ASSEMBLY_FORMAT:
        raise ValueError(f"not an Assembly Bundle: format={manifest.get('format')!r}")
    version = str(manifest.get("version", ""))
    if version != ASSEMBLY_VERSION:
        raise ValueError(f"unsupported Assembly Bundle version: {version!r} "
                         f"(this reader only understands {ASSEMBLY_VERSION!r})")

    composition = manifest.get("composition") or {}
    canvas_info = composition.get("canvas") or {}
    width, height = int(canvas_info.get("width", 0)), int(canvas_info.get("height", 0))
    if width <= 0 or height <= 0:
        raise ValueError("Assembly Bundle composition.canvas is missing or empty")
    if canvas_info.get("coordinate_system", "top-left-y-down") != "top-left-y-down":
        raise ValueError("unsupported coordinate system")
    if (canvas_info.get("color_space", "srgb") != "srgb"
            or canvas_info.get("alpha", "straight") != "straight"):
        raise ValueError("Assembly Bundle must use sRGB straight-alpha images")

    assets = manifest.get("assets") or {}
    instances = manifest.get("instances") or {}
    # Final draw_order is Composer's own authored contract (directive #7:
    # AutoRig must not decide it) -- absent means the bundle is malformed,
    # not an invitation to invent one from dict insertion order.
    draw_order_ids = composition.get("draw_order")
    if not draw_order_ids:
        raise ValueError("Assembly Bundle composition.draw_order is missing or empty -- "
                         "AutoRig does not invent a paint order")
    layers_dir = root / "layers"

    canvas_layers: dict[str, Image.Image] = {}
    draw_order: list[str] = []
    visible_tags_in_order: list[str] = []
    variant_sets = manifest.get("variant_sets") or {}
    if not isinstance(variant_sets, dict):
        raise ValueError("Assembly Bundle variant_sets must be an object")
    for set_id, spec in variant_sets.items():
        if not isinstance(spec, dict):
            raise ValueError(f"VariantSet {set_id!r} must be an object")
        if spec.get("mode", "exclusive") != "exclusive":
            raise ValueError(f"VariantSet {set_id!r} has unsupported mode {spec.get('mode')!r}")
    variant_member_ids = {
        str(member)
        for spec in variant_sets.values()
        for member in (spec.get("members") or [])
    }
    instance_layers: dict[str, np.ndarray] = {}
    instance_to_tag: dict[str, str] = {}
    instance_draw_order: list[str] = []
    for inst_id in draw_order_ids:
        inst = instances.get(inst_id)
        if inst is None:
            raise ValueError(f"composition.draw_order references unknown instance {inst_id!r}")
        asset = assets.get(inst["asset_ref"])
        if asset is None:
            raise ValueError(f"instance {inst_id!r} references unknown asset {inst['asset_ref']!r}")
        tag = str(asset["semantic"])
        instance_to_tag[str(inst_id)] = tag
        instance_draw_order.append(str(inst_id))
        image_path = layers_dir / f"{inst_id}.png"
        if not image_path.is_file():
            raise FileNotFoundError(f"layer image missing for instance {inst_id!r}: {image_path}")
        with Image.open(image_path) as raw:
            im = raw.convert("RGBA")
            opacity = float(inst.get("opacity", 1.0))
            if opacity < 1.0:
                r, g, b, a = im.split()
                a = a.point(lambda v: round(v * opacity))
                im = Image.merge("RGBA", (r, g, b, a))
            positioned, (x, y) = _position(im, inst.get("transform") or {})
            if str(inst_id) in variant_member_ids:
                full = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                full.alpha_composite(positioned, dest=(x, y))
                instance_layers[str(inst_id)] = np.array(full, dtype=np.uint8)
            if (not inst.get("visible", True)
                    or float(inst.get("opacity", 1.0)) <= 0.0
                    or str(inst_id) in variant_member_ids):
                continue
            visible_tags_in_order.append(tag)
            if tag not in canvas_layers:
                canvas_layers[tag] = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                draw_order.append(tag)
            canvas_layers[tag].alpha_composite(positioned, dest=(x, y))

    if not canvas_layers and not instance_layers:
        raise ValueError("Assembly Bundle has no visible instances")

    # `rig.build_rig` (like every producer-facing part of this repo) has one
    # image per *semantic tag*, not per instance -- flattening several
    # visible instances that share one semantic into that one image is only
    # lossless when Composer drew them contiguously (nothing else
    # interleaved between them). A gap means some other tag was meant to sit
    # between two same-semantic instances -- silently flattening them would
    # destroy real draw-order information and could pass its own
    # self-consistency check while actually being wrong. Hard reject instead
    # of guessing; true instance-level rig support is future work.
    for tag in dict.fromkeys(visible_tags_in_order):
        first = visible_tags_in_order.index(tag)
        last = len(visible_tags_in_order) - 1 - visible_tags_in_order[::-1].index(tag)
        if any(other != tag for other in visible_tags_in_order[first:last + 1]):
            raise ValueError(
                f"semantic tag {tag!r} is not drawn contiguously in "
                "composition.draw_order -- AutoRig cannot flatten non-adjacent "
                "same-semantic instances into one layer without losing real "
                "draw-order information (instance-level rig support does not "
                "exist yet)"
            )

    layers = {tag: np.array(img, dtype=np.uint8) for tag, img in canvas_layers.items()}
    body_remainder = layers.pop("body_remainder", None)

    reference_path = root / "reference.png"
    if not reference_path.is_file():
        raise FileNotFoundError(f"Assembly Bundle is missing its reference.png: {root}")
    with Image.open(reference_path) as ref:
        reference = np.array(ref.convert("RGBA"), dtype=np.uint8)

    return AssemblyAsset(
        root=root, canvas=(width, height), layers=layers, body_remainder=body_remainder,
        draw_order=draw_order,
        rig_intent=manifest.get("rig_intent") or {},
        variant_sets=variant_sets,
        expressions=manifest.get("expressions") or {},
        instance_layers=instance_layers,
        instance_to_tag=instance_to_tag,
        instance_draw_order=instance_draw_order,
        reference=reference,
        source_id=root.name,
        provenance=manifest.get("provenance") or {},
    )
