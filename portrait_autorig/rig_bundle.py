"""Pinned reader for Composer Rig Bundle v0.4."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image

from .assembly import AssemblyAsset, load_assembly_bundle

RIG_BUNDLE_FORMAT = "portrait-rig-bundle"
RIG_BUNDLE_VERSION = "0.4"
RIG_BUNDLE_SCHEMA_VENDOR = "portrait-composer"
RIG_BUNDLE_SCHEMA_COMMIT = "d9393d9153522d086c61eb52dbadff02f0aa17e0"
RIG_BUNDLE_SCHEMA_ID = "portrait-rig-bundle-v0.4"
RIG_BUNDLE_SCHEMA_SHA256 = "9359098a2db74aab5871ef280fc19d0f243a8167165af6277c2d0f97ebc68bd7"
RIG_BUNDLE_SCHEMA_PATH = Path(__file__).with_name("schemas") / "portrait-rig-bundle-v0.4.schema.json"
RIG_BUNDLE_SCHEMA_PIN = (
    f"{RIG_BUNDLE_SCHEMA_VENDOR}@{RIG_BUNDLE_SCHEMA_COMMIT}:{RIG_BUNDLE_SCHEMA_ID}"
)
_SAFE_ID = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')


def _schema_metadata() -> dict[str, Any]:
    raw = RIG_BUNDLE_SCHEMA_PATH.read_bytes()
    schema = json.loads(raw.decode("utf-8"))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != RIG_BUNDLE_SCHEMA_SHA256 or schema.get("$id") != (
        "https://portrait-composer/schemas/portrait-rig-bundle-v0.4.schema.json"
    ):
        raise RuntimeError("vendored Rig Bundle schema does not match the pinned Composer commit")
    return {
        "format": RIG_BUNDLE_FORMAT,
        "version": RIG_BUNDLE_VERSION,
        "vendor": RIG_BUNDLE_SCHEMA_VENDOR,
        "upstream_commit": RIG_BUNDLE_SCHEMA_COMMIT,
        "schema_id": RIG_BUNDLE_SCHEMA_ID,
        "schema_file": RIG_BUNDLE_SCHEMA_PATH.name,
        "schema_sha256": digest,
        "pin": RIG_BUNDLE_SCHEMA_PIN,
    }


def _safe_id(value: Any) -> bool:
    if not isinstance(value, str) or value in {".", ".."} or value != value.strip():
        return False
    if value.endswith(".") or not _SAFE_ID.fullmatch(value):
        return False
    device_name = value.split(".", 1)[0].upper()
    return device_name not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _bundle_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError(f"unsafe Rig Bundle path: {relative!r}")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"unsafe Rig Bundle path: {relative!r}")
    candidate = root.joinpath(*posix.parts)
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError(f"Rig Bundle artifact is missing or outside the bundle: {relative!r}")
    return resolved


def _read_manifest(root: Path) -> dict[str, Any]:
    _schema_metadata()
    path = root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"not a Rig Bundle (missing manifest.json): {root}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Rig Bundle manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Rig Bundle manifest must be a JSON object")
    required = {
        "format", "version", "canvas", "layers", "draw_order", "instance_draw_order", "variant_layers",
        "instances", "assets", "variant_sets", "expressions", "rig_intent",
        "source_metadata", "expression_intent",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"Rig Bundle manifest is missing required fields: {', '.join(missing)}")
    if manifest.get("format") != RIG_BUNDLE_FORMAT or manifest.get("version") != RIG_BUNDLE_VERSION:
        raise ValueError(
            f"unsupported Rig Bundle contract: {manifest.get('format')!r} "
            f"version {manifest.get('version')!r}; expected {RIG_BUNDLE_FORMAT} {RIG_BUNDLE_VERSION}"
        )
    canvas = manifest["canvas"]
    if not isinstance(canvas, dict) or any(
        not isinstance(canvas.get(key), int) or isinstance(canvas.get(key), bool) or canvas[key] <= 0
        for key in ("width", "height")
    ):
        raise ValueError("Rig Bundle canvas.width/height must be positive integers")
    visible = manifest["layers"]
    if not isinstance(visible, list) or not visible or any(not _safe_id(item) for item in visible):
        raise ValueError("Rig Bundle layers must be a non-empty array of safe instance ids")
    if len(visible) != len(set(visible)) or manifest["draw_order"] != visible:
        raise ValueError("Rig Bundle draw_order must match unique visible layers in paint order")
    instances, assets = manifest["instances"], manifest["assets"]
    instance_draw_order = manifest["instance_draw_order"]
    variants, variant_layers = manifest["variant_sets"], manifest["variant_layers"]
    for name, value in (("instances", instances), ("assets", assets), ("variant_sets", variants),
                        ("variant_layers", variant_layers), ("expressions", manifest["expressions"]),
                        ("rig_intent", manifest["rig_intent"]),
                        ("source_metadata", manifest["source_metadata"])):
        if not isinstance(value, dict):
            raise ValueError(f"Rig Bundle {name} must be an object")
    if (
        not isinstance(instance_draw_order, list)
        or any(not _safe_id(item) for item in instance_draw_order)
        or len(instance_draw_order) != len(set(instance_draw_order))
        or set(instance_draw_order) != set(instances)
    ):
        raise ValueError("Rig Bundle instance_draw_order must contain every instance exactly once")
    if [item for item in instance_draw_order if item in visible] != visible:
        raise ValueError("Rig Bundle instance_draw_order must preserve visible draw_order")
    if any(not _safe_id(key) for key in instances) or any(not _safe_id(key) for key in assets):
        raise ValueError("Rig Bundle instance and asset ids must be safe path components")
    variant_members: set[str] = set()
    for set_id, spec in variants.items():
        if not _safe_id(set_id) or not isinstance(spec, dict):
            raise ValueError(f"invalid VariantSet {set_id!r}")
        members = spec.get("members")
        if spec.get("mode", "exclusive") != "exclusive" or not isinstance(members, list) or not members:
            raise ValueError(f"VariantSet {set_id!r} must be an exclusive set with members")
        if any(not _safe_id(member) for member in members):
            raise ValueError(f"VariantSet {set_id!r} has an unsafe member id")
        if len(members) != len(set(members)) or any(member not in instances for member in members):
            raise ValueError(f"VariantSet {set_id!r} has duplicate or unknown members")
        variant_members.update(members)
    if any(member not in instances for member in visible):
        raise ValueError("Rig Bundle layers references an unknown instance")
    hidden_variants = variant_members - set(visible)
    if set(instances) != set(visible) | variant_members:
        raise ValueError("Rig Bundle must contain only visible layers and VariantSet members")
    if set(variant_layers) != hidden_variants:
        raise ValueError("variant_layers must contain every hidden VariantSet member and no other id")
    for instance_id, instance in instances.items():
        if not isinstance(instance, dict):
            raise ValueError(f"instance {instance_id!r} must be an object")
        asset_ref = instance.get("asset_ref")
        if not isinstance(asset_ref, str) or asset_ref not in assets:
            raise ValueError(f"instance {instance_id!r} references an unknown asset")
        asset = assets[asset_ref]
        if not isinstance(asset, dict) or not isinstance(asset.get("semantic"), str) or not asset["semantic"]:
            raise ValueError(f"asset {asset_ref!r} must have a semantic")
        if not isinstance(instance.get("transform", {}), dict):
            raise ValueError(f"instance {instance_id!r} transform must be an object")
    for instance_id in visible:
        _bundle_file(root, f"layers/{instance_id}.png")
    for instance_id, relative in variant_layers.items():
        if relative != f"variants/{instance_id}.png":
            raise ValueError(f"variant layer {instance_id!r} has an unexpected path")
        _bundle_file(root, relative)
    reference = _bundle_file(root, "reference.png")
    with Image.open(reference) as image:
        if image.size != (canvas["width"], canvas["height"]):
            raise ValueError("Rig Bundle reference.png dimensions do not match the canvas")
    expression_intent = manifest["expression_intent"]
    if not isinstance(expression_intent, dict) or expression_intent.get("profile") != "face_expression_core_v2":
        raise ValueError("Rig Bundle expression_intent profile is unsupported")
    articulation = expression_intent.get("articulation", {})
    emotion_channels = expression_intent.get("emotion_channels", {})
    presets = expression_intent.get("presets", {})
    if not isinstance(articulation, dict) or not isinstance(emotion_channels, dict) or not isinstance(presets, dict):
        raise ValueError("Rig Bundle expression_intent channels and presets must be objects")
    for channel, mapping in articulation.items():
        if not isinstance(mapping, dict):
            raise ValueError(f"expression articulation {channel!r} must be an object")
        set_id = mapping.get("variant_set")
        states = mapping.get("states", {})
        if set_id not in variants or not isinstance(states, dict):
            raise ValueError(f"expression articulation {channel!r} references an unknown VariantSet")
        members = variants[set_id].get("members", [])
        if any(member not in members for member in states.values()):
            raise ValueError(f"expression articulation {channel!r} references a non-member")
    for preset_id, mapping in presets.items():
        if not isinstance(mapping, dict):
            raise ValueError(f"expression preset {preset_id!r} must be an object")
        for channel, member in mapping.items():
            if channel == "preserve":
                continue
            if channel not in variants or member not in variants[channel].get("members", []):
                raise ValueError(f"expression preset {preset_id!r} references a non-member")
    return manifest


def load_rig_bundle(directory: str | Path) -> AssemblyAsset:
    """Read Rig Bundle v0.4 through the already pinned Assembly compiler seam."""
    root = Path(directory).resolve()
    manifest = _read_manifest(root)
    width, height = manifest["canvas"]["width"], manifest["canvas"]["height"]
    all_ids = list(manifest["instance_draw_order"])
    source_metadata = manifest["source_metadata"]
    sources = {
        source_id: {"source_id": source_id, "path": None, "metadata": metadata}
        for source_id, metadata in source_metadata.items()
        if isinstance(source_id, str) and source_id and isinstance(metadata, dict)
    }
    if len(sources) != len(source_metadata):
        raise ValueError("Rig Bundle source_metadata ids and values must be valid objects")
    provenance_path = _bundle_file(root, "provenance/assembly.json")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Rig Bundle provenance/assembly.json is invalid") from exc
    if not isinstance(provenance, dict):
        raise ValueError("Rig Bundle provenance/assembly.json must be an object")

    with tempfile.TemporaryDirectory(prefix="autorig-rig-bundle-") as temp:
        assembly_root = Path(temp) / "converted.assembly"
        layers_dir = assembly_root / "layers"
        layers_dir.mkdir(parents=True)
        for instance_id in all_ids:
            if instance_id in manifest["layers"]:
                relative = f"layers/{instance_id}.png"
            else:
                relative = manifest["variant_layers"][instance_id]
            shutil.copyfile(_bundle_file(root, relative), layers_dir / f"{instance_id}.png")
        shutil.copyfile(_bundle_file(root, "reference.png"), assembly_root / "reference.png")
        assets = {
            asset_id: {
                "id": asset_id,
                "semantic": asset["semantic"],
                "source_binding": None,
                "planes": [],
                "compatibility": {},
                "provenance": asset.get("provenance", {}),
            }
            for asset_id, asset in manifest["assets"].items()
        }
        instances = {}
        for index, instance_id in enumerate(all_ids):
            authored = manifest["instances"][instance_id]
            instances[instance_id] = {
                "id": instance_id,
                "asset_ref": authored["asset_ref"],
                "slot": authored.get("slot", manifest["assets"][authored["asset_ref"]]["semantic"]),
                "draw_order": index,
                "visible": instance_id in manifest["layers"],
                # Rig Bundle PNG pixels already include opacity and VisualOps.
                "opacity": 1.0,
                "transform": authored.get("transform", {}),
                "transform_link": None,
                "plane": None,
            }
        assembly_manifest = {
            "format": "portrait-assembly",
            "version": "0.2",
            "sources": sources,
            "assets": assets,
            "instances": instances,
            "hierarchy": {},
            "variant_sets": manifest["variant_sets"],
            "expressions": manifest["expressions"],
            "links": {},
            "rig_intent": manifest["rig_intent"],
            "composition": {
                "draw_order": all_ids,
                "canvas": {
                    "width": width,
                    "height": height,
                    "coordinate_system": "top-left-y-down",
                    "color_space": "srgb",
                    "alpha": "straight",
                },
            },
            "provenance": provenance,
        }
        (assembly_root / "manifest.json").write_text(
            json.dumps(assembly_manifest), encoding="utf-8"
        )
        asset = load_assembly_bundle(assembly_root)

    return replace(
        asset,
        root=root,
        source_id=root.name,
        provenance=provenance,
        source_kind="rig_bundle",
        source_schema=_schema_metadata(),
        expression_intent=manifest["expression_intent"],
        source_metadata=source_metadata,
    )
