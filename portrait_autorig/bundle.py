"""Portrait Bundle v1 reader and pre-v1 legacy adapter."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PortraitAsset:
    root: Path
    original: np.ndarray
    layers: dict[str, np.ndarray]
    body_remainder: np.ndarray | None
    tag_version: str
    source_id: str
    legacy_repair_applied: bool = False


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"invalid bundle path: {relative!r}")
    path = (root / Path(*relative.split("/"))).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"bundle path escapes its root: {relative!r}") from error
    return path


def _rgba(path: Path, canvas: tuple[int, int]) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(path)
    arr = np.array(Image.open(path).convert("RGBA"))
    expected = (canvas[1], canvas[0], 4)
    if arr.shape != expected:
        raise ValueError(f"{path.name} has shape {arr.shape}, expected {expected}")
    return arr


def load_portrait_bundle(directory: str | os.PathLike[str]) -> PortraitAsset:
    """Read canonical layers without ever invoking legacy repair."""
    root = Path(directory).resolve()
    manifest = _read_json(root / "manifest.json")
    if manifest.get("format") != "portrait-bundle":
        raise ValueError("not a Portrait Bundle")
    version = str(manifest.get("version", ""))
    if version.split(".", 1)[0] != "1":
        raise ValueError(f"unsupported Portrait Bundle version: {version!r}")
    contract = manifest.get("layer_contract") or {}
    if contract.get("canonical_stage") != "production_repaired":
        raise ValueError("Portrait Bundle canonical layers are not production_repaired")

    canvas_info = manifest.get("canvas") or {}
    canvas = (int(canvas_info["width"]), int(canvas_info["height"]))
    if canvas_info.get("coordinate_system") != "top-left-y-down":
        raise ValueError("unsupported coordinate system")
    if canvas_info.get("color_space") != "srgb" or canvas_info.get("alpha") != "straight":
        raise ValueError("Portrait Bundle must use sRGB straight-alpha images")

    original = _rgba(_inside(root, manifest["original"]), canvas)
    layers: dict[str, np.ndarray] = {}
    remainder = None
    for tag, entry in (manifest.get("layers") or {}).items():
        if not isinstance(entry, dict):
            raise ValueError(f"layer entry must be an object: {tag!r}")
        image = _rgba(_inside(root, entry["path"]), canvas)
        if tag == "body_remainder":
            remainder = image
        elif tag in {"head_remainder", "neck_remainder"}:
            raise ValueError(f"rig-derived tag is forbidden in a Portrait Bundle: {tag}")
        else:
            layers[tag] = image
    if not layers:
        raise ValueError("Portrait Bundle has no canonical semantic layers")

    semantics = manifest.get("semantics") or {}
    return PortraitAsset(
        root=root,
        original=original,
        layers=layers,
        body_remainder=remainder,
        tag_version=str(semantics.get("version", "")),
        source_id=root.name,
    )


def load_legacy_run(directory: str | os.PathLike[str]) -> PortraitAsset:
    """Adapt one pre-v1 flat run and apply frozen compatibility repair once."""
    root = Path(directory).resolve()
    manifests = sorted(
        path for path in root.glob("*_manifest.json")
        if not path.name.endswith("_rig_manifest.json")
    )
    if not manifests:
        raise FileNotFoundError(f"no legacy run manifest in {root}")
    manifest = _read_json(manifests[0])
    if manifest.get("format") == "portrait-bundle":
        raise ValueError("use load_portrait_bundle for Portrait Bundle input")
    width, height = int(manifest["width"]), int(manifest["height"])
    canvas = (width, height)
    original = _rgba(_inside(root, manifest["original"]), canvas)
    layers = {
        tag: _rgba(_inside(root, relative), canvas)
        for tag, relative in (manifest.get("layers") or {}).items()
    }
    if not layers:
        raise ValueError("legacy run has no readable layers")

    diagnostics = manifest.get("diagnostics") or {}
    remainder_name = diagnostics.get("body_remainder")
    if not remainder_name:
        base = str(manifest.get("base", manifests[0].name[:-len("_manifest.json")]))
        candidate = root / f"{base}_body_remainder.png"
        remainder_name = candidate.name if candidate.is_file() else None
    remainder = _rgba(_inside(root, remainder_name), canvas) if remainder_name else None

    from .legacy_repair import repair_portrait_layers

    repaired = repair_portrait_layers(layers, original)
    report_name = manifest.get("report")
    report = _read_json(_inside(root, report_name)) if isinstance(report_name, str) else {}
    return PortraitAsset(
        root=root,
        original=original,
        layers=repaired.layers,
        body_remainder=remainder,
        tag_version=str((report.get("source") or {}).get("tag_version", "")),
        source_id=root.name,
        legacy_repair_applied=True,
    )

