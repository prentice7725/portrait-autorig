from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .expression import attach_to_run, transplant_pack, write_expression_pack


EXPRESSION_STATE_PRESETS = (
    "eye_closed",
    "wink_left",
    "wink_right",
    "mouth_open",
    "mouth_a",
    "mouth_i",
    "mouth_u",
    "mouth_e",
    "mouth_o",
)


@dataclass(frozen=True)
class ExpressionApplyResult:
    base_run: Path
    mode: str
    states: tuple[str, ...]
    part_count: int


def _manifest_path(run_dir: Path) -> Path:
    manifests = sorted(run_dir.glob("*_rig_manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"No *_rig_manifest.json in {run_dir}")
    if len(manifests) > 1:
        raise ValueError(f"Multiple rig manifests found in {run_dir}; expected one")
    return manifests[0]


def _validate_state_map(donors: dict[str, Path]) -> dict[str, Path]:
    if not donors:
        raise ValueError("Add at least one expression donor")
    normalized: dict[str, Path] = {}
    for raw_state, raw_path in donors.items():
        state = raw_state.strip()
        if not state:
            raise ValueError("Expression state name cannot be empty")
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        normalized[state] = path
    return normalized


def apply_image_donors(base_run: Path, donors: dict[str, Path]) -> ExpressionApplyResult:
    """Attach generated full-frame donor images to an existing rig run.

    Each donor contributes only the semantic region implied by its state name;
    identity, hair, body, and every untouched pixel continue to come from the
    base rig.
    """
    base_run = Path(base_run).expanduser().resolve()
    _manifest_path(base_run)
    normalized = _validate_state_map(donors)

    rgba = {
        state: np.array(Image.open(path).convert("RGBA"))
        for state, path in normalized.items()
    }
    block = attach_to_run(str(base_run), rgba)
    return ExpressionApplyResult(
        base_run=base_run,
        mode="image",
        states=tuple(normalized),
        part_count=len(block.get("parts", {})),
    )


def apply_rig_donors(base_run: Path, donors: dict[str, Path]) -> ExpressionApplyResult:
    """Transplant semantic feature layers from already compiled donor rigs.

    Unlike calling ``transplant_to_run`` repeatedly, this merges every donor
    state first and writes the expression block once, so later states cannot
    overwrite earlier ones.
    """
    base_run = Path(base_run).expanduser().resolve()
    manifest_path = _manifest_path(base_run)
    normalized = _validate_state_map(donors)
    for path in normalized.values():
        _manifest_path(path)

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    merged_parts = []
    merged_report = {
        "source": "transplant_multi",
        "states": {},
        "donors": {},
    }
    for state, donor_run in normalized.items():
        pack = transplant_pack(str(base_run), str(donor_run), [state])
        merged_parts.extend(pack.get("parts", []))
        report = pack.get("report", {})
        merged_report["states"].update(report.get("states", {}))
        merged_report["donors"][state] = str(donor_run)

    block = write_expression_pack(
        str(base_run),
        {"parts": merged_parts, "report": merged_report},
        manifest.get("parts", ()),
    )
    manifest["expressions"] = block
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return ExpressionApplyResult(
        base_run=base_run,
        mode="rig",
        states=tuple(normalized),
        part_count=len(block.get("parts", {})),
    )
