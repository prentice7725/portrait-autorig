"""Declarative P1 clip-mask and N-way boundary-stitch contracts.

The compiler emits these records without baking pixels.  Preview/runtime
backends may choose a stencil, alpha mask, or vertex correction, but the
source/target ownership and stitch participation stay explicit in the rig
manifest.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["clip_mask_spec", "boundary_stitch_spec", "compile_clip_masks",
           "compile_boundary_stitches"]


def _name(value: Any, label: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def clip_mask_spec(source: str, targets: Sequence[str], *,
                   mode: str = "alpha", phase: str = "constraints") -> dict[str, Any]:
    """Return a validated mask relation, e.g. eyewhite -> iris/pupil/highlight."""
    source_name = _name(source, "source")
    target_names = [_name(target, "target") for target in targets]
    if not target_names:
        raise ValueError("clip mask requires at least one target")
    if source_name in target_names:
        raise ValueError("clip mask source cannot also be a target")
    if mode not in {"alpha", "stencil"}:
        raise ValueError(f"unsupported clip mask mode: {mode!r}")
    return {"id": f"clip_{source_name}", "kind": "clip_mask", "phase": phase,
            "source": source_name, "targets": target_names, "mode": mode}


def boundary_stitch_spec(stitches: Sequence[Mapping[str, Any]], *,
                         tolerance_px: float = 1.0) -> dict[str, Any]:
    """Normalize N-way boundary relations with weights summing to one.

    Each input member needs ``part`` and ``vertex``; an optional ``weight`` is
    normalized per stitch group.  One vertex may participate in multiple groups.
    """
    if tolerance_px < 0:
        raise ValueError("tolerance_px must be non-negative")
    groups: list[dict[str, Any]] = []
    for index, stitch in enumerate(stitches):
        members = stitch.get("members", [])
        if not isinstance(members, Sequence) or isinstance(members, (str, bytes)) or len(members) < 2:
            raise ValueError(f"boundary stitch {index} needs at least two members")
        normalized: list[dict[str, Any]] = []
        raw_weights = []
        for member in members:
            part = _name(member.get("part"), "stitch part")
            if "vertex" not in member:
                raise ValueError("stitch member needs a vertex")
            vertex = int(member["vertex"])
            if vertex < 0:
                raise ValueError("stitch vertex must be non-negative")
            weight = float(member.get("weight", 1.0))
            if weight < 0:
                raise ValueError("stitch weight must be non-negative")
            normalized.append({"part": part, "vertex": vertex, "weight": weight})
            raw_weights.append(weight)
        total = sum(raw_weights)
        if total <= 0:
            raise ValueError("boundary stitch weights must have a positive sum")
        for member in normalized:
            member["weight"] = round(member["weight"] / total, 8)
        # Correct final rounding drift without changing the authored ordering.
        normalized[-1]["weight"] = round(
            normalized[-1]["weight"] + 1.0 - sum(item["weight"] for item in normalized), 8
        )
        groups.append({"id": str(stitch.get("id", f"boundary_stitch_{index}")),
                       "members": normalized})
    return {"kind": "boundary_stitch", "phase": "constraints",
            "tolerance_px": float(tolerance_px), "groups": groups}


def compile_clip_masks(relations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [clip_mask_spec(item["source"], item["targets"], mode=item.get("mode", "alpha"),
                            phase=item.get("phase", "constraints")) for item in relations]


def compile_boundary_stitches(stitches: Sequence[Mapping[str, Any]], *,
                              tolerance_px: float = 1.0) -> dict[str, Any]:
    return boundary_stitch_spec(stitches, tolerance_px=tolerance_px)
