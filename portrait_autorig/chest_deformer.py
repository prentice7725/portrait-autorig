"""P3 chest parametric warp generation.

The P2.x soft-field implementation remains in :mod:`soft_morph` for
backward compatibility.  P3 moves shape authoring to a small compile-time
keyform cage: physics supplies a normalized parameter and the runtime only
interpolates the pre-generated poses.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

__all__ = [
    "P3_VERSION", "P3_DEFORMER_KIND", "DEFAULT_CAGE_COLS", "DEFAULT_CAGE_ROWS",
    "DEFAULT_RANGE_X_PX", "DEFAULT_RANGE_Y_PX", "build_chest_parametric_deformer",
    "validate_chest_parametric_deformer",
]

P3_VERSION = 1
P3_DEFORMER_KIND = "chest_parametric_deformer"
DEFAULT_CAGE_COLS = 6  # control points, not cells
DEFAULT_CAGE_ROWS = 4  # control points, not cells
DEFAULT_RANGE_X_PX = 6.0
DEFAULT_RANGE_Y_PX = 6.0


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _cage_bounds(part: dict[str, Any], soft_spec: dict[str, Any],
                 frame_size: tuple[int, int]) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = (float(v) for v in part["xyxy"])
    width, height = x2 - x1, y2 - y1
    boxes: list[tuple[float, float, float, float]] = []
    coordinate_space = soft_spec.get("coordinate_space")
    if coordinate_space == "canvas_normalized":
        bx, by, bw, bh = 0.0, 0.0, float(frame_size[1]), float(frame_size[0])
    else:
        bx, by, bw, bh = x1, y1, width, height
    for lobe in (soft_spec.get("left"), soft_spec.get("right")):
        if not isinstance(lobe, dict):
            continue
        center, radius = lobe.get("center"), lobe.get("radius")
        if not (isinstance(center, (list, tuple)) and isinstance(radius, (list, tuple))
                and len(center) >= 2 and len(radius) >= 2):
            continue
        cx, cy = bx + float(center[0]) * bw, by + float(center[1]) * bh
        rx, ry = abs(float(radius[0]) * bw), abs(float(radius[1]) * bh)
        boxes.append((cx - rx, cy - ry, cx + rx, cy + ry))
    if boxes:
        rx1, ry1 = min(box[0] for box in boxes), min(box[1] for box in boxes)
        rx2, ry2 = max(box[2] for box in boxes), max(box[3] for box in boxes)
    else:
        rx1, ry1, rx2, ry2 = x1 + width * 0.15, y1 + height * 0.2, x2 - width * 0.15, y1 + height * 0.75
    pad_x, pad_y = max(1.0, (rx2 - rx1) * 0.08), max(1.0, (ry2 - ry1) * 0.06)
    # Keep the cage on the visible topwear surface and never turn it into a
    # whole-garment/abdomen deformer.
    return (max(x1, rx1 - pad_x), max(y1, ry1 - pad_y),
            min(x2, rx2 + pad_x), min(y2, ry2 + pad_y))


def _cage_points(bounds: tuple[float, float, float, float], cols: int, rows: int) -> list[list[float]]:
    x1, y1, x2, y2 = bounds
    return [[round(x1 + (x2 - x1) * c / max(1, cols - 1), 4),
             round(y1 + (y2 - y1) * r / max(1, rows - 1), 4)]
            for r in range(rows) for c in range(cols)]


def _axis_values(start: float, end: float, base_cell: float,
                 refine: tuple[float, float, float] | None) -> list[float]:
    count = max(1, round((end - start) / max(1.0, base_cell)))
    values = [start + (end - start) * i / count for i in range(count + 1)]
    if refine is not None:
        refine_start, refine_end, refine_cell = refine
        if refine_end > refine_start and refine_cell > 0:
            value = max(start, refine_start)
            while value <= min(end, refine_end) + 1e-6:
                values.append(value)
                value += refine_cell
            values.extend((max(start, refine_start), min(end, refine_end)))
    return sorted({round(float(value), 4) for value in values})


def _mesh_vertices(part: dict[str, Any]) -> list[tuple[float, float]]:
    mesh = part.get("mesh") or {}
    if mesh.get("kind") == "contour" and mesh.get("vertices"):
        return [(float(x), float(y)) for x, y in mesh["vertices"]]
    x1, y1, x2, y2 = (float(v) for v in part["xyxy"])
    cell = float(mesh.get("cell", 30))
    refinement = mesh.get("refinement") or {}
    region = refinement.get("region")
    refine_x = refine_y = None
    if isinstance(region, (list, tuple)) and len(region) >= 4:
        refine_x = (float(region[0]), float(region[2]), float(refinement.get("cell", 0)))
        refine_y = (float(region[1]), float(region[3]), float(refinement.get("cell", 0)))
    xs = _axis_values(x1, x2, cell, refine_x)
    ys = _axis_values(y1, y2, cell, refine_y)
    return [(x, y) for y in ys for x in xs]


def _binding(vertices: Iterable[tuple[float, float]], bounds: tuple[float, float, float, float],
             occluder_alpha: np.ndarray | None, alpha_threshold: int,
             cols: int, rows: int) -> dict[str, Any]:
    x1, y1, x2, y2 = bounds
    width, height = max(1e-6, x2 - x1), max(1e-6, y2 - y1)
    fade_x, fade_y = width * 0.08, height * 0.08
    cells: list[list[int]] = []
    uv: list[list[float]] = []
    influence: list[float] = []
    locked_vertices: list[bool] = []
    locked = 0
    for x, y in vertices:
        gx = (x - x1) / width * (cols - 1)
        gy = (y - y1) / height * (rows - 1)
        cx = max(0, min(cols - 2, int(math.floor(gx))))
        cy = max(0, min(rows - 2, int(math.floor(gy))))
        u, v = max(0.0, min(1.0, gx - cx)), max(0.0, min(1.0, gy - cy))
        edge = min(x - x1, x2 - x, y - y1, y2 - y)
        weight = _smoothstep(0.0, min(fade_x, fade_y), edge)
        is_locked = False
        if occluder_alpha is not None:
            ix, iy = int(round(x)), int(round(y))
            if 0 <= iy < occluder_alpha.shape[0] and 0 <= ix < occluder_alpha.shape[1]:
                is_locked = float(occluder_alpha[iy, ix]) > alpha_threshold
        if is_locked:
            weight = 0.0
            locked += 1
        cells.append([cx, cy])
        uv.append([round(u, 6), round(v, 6)])
        influence.append(round(float(weight), 6))
        locked_vertices.append(bool(is_locked))
    return {"mode": "bilinear_grid_v1", "vertex_cells": cells,
            "vertex_uv": uv, "vertex_influence": influence,
            "locked_vertices": locked_vertices,
            "occluder_locked_vertex_count": locked}


def _keyforms(cols: int, rows: int, range_x: float, range_y: float) -> dict[str, list[list[float]]]:
    def make(kind: str) -> list[list[float]]:
        out: list[list[float]] = []
        y_weights = {
            "pos": (0.05, 0.35, 1.00, 0.85),
            "neg": (0.05, 0.35, 0.85, 1.00),
        }
        for row in range(rows):
            trow = row / max(1, rows - 1)
            for col in range(cols):
                t = col / max(1, cols - 1)
                centered = t - 0.5
                if kind in {"y_pos", "y_neg"}:
                    weight = y_weights["pos" if kind == "y_pos" else "neg"][row]
                    dy = (-1.0 if kind == "y_pos" else 1.0) * range_y * weight
                    # A small continuous spread/compensation keeps the pose
                    # from reading as a rigid rectangle while the attachment
                    # row remains almost fixed.
                    dx = centered * range_y * (0.18 if row >= 2 else 0.05)
                    if kind == "y_neg":
                        dx *= -1.0
                else:
                    weight = (0.05, 0.35, 0.90, 1.00)[row]
                    dx = (1.0 if kind == "x_pos" else -1.0) * range_x * weight
                    dx += (-centered if kind == "x_pos" else centered) * range_x * 0.12
                    dy = centered * range_y * 0.05 * weight
                out.append([round(dx, 4), round(dy, 4)])
        return out
    return {"neutral": [[0.0, 0.0] for _ in range(cols * rows)],
            "bust_x_neg": make("x_neg"), "bust_x_pos": make("x_pos"),
            "bust_y_neg": make("y_neg"), "bust_y_pos": make("y_pos")}


def build_chest_parametric_deformer(
    part: dict[str, Any], soft_spec: dict[str, Any], *,
    frame_size: tuple[int, int], occluder_alpha: np.ndarray | None = None,
    alpha_threshold: int = 10, profile: str = "soft",
    range_x_px: float = DEFAULT_RANGE_X_PX, range_y_px: float = DEFAULT_RANGE_Y_PX,
) -> dict[str, Any]:
    """Generate one continuous P3 cage, binding, and four auto keyforms."""
    cols, rows = DEFAULT_CAGE_COLS, DEFAULT_CAGE_ROWS
    bounds = _cage_bounds(part, soft_spec, frame_size)
    points = _cage_points(bounds, cols, rows)
    binding = _binding(_mesh_vertices(part), bounds, occluder_alpha, alpha_threshold, cols, rows)
    return {
        "version": P3_VERSION, "enabled": True,
        # Keep both selectors: tags are the compatibility alias, while the
        # Composer instance name is the stable authored target when multiple
        # torso-like parts share a semantic tag.
        "target_instance": (soft_spec.get("target_instance")
                            or part.get("source_instance_id") or part.get("name")),
        "target_part": part.get("name"),
        "target_tag": part.get("tag", "topwear"), "profile": profile,
        "breath_isolated": True,
        "parameters": {"x": "ParamBustX", "y": "ParamBustY"},
        "ranges_px": {"x": float(range_x_px), "y": float(range_y_px)},
        "cage": {"cols": cols, "rows": rows, "bounds": [round(v, 4) for v in bounds],
                 "rest_points": points},
        "binding": binding,
        "keyforms": _keyforms(cols, rows, float(range_x_px), float(range_y_px)),
        "locks": {"upper_attachment": True, "center_seam": False,
                  "occluder_aware": True},
        "source": "autorig_p3_auto_keyform",
    }


def validate_chest_parametric_deformer(spec: dict[str, Any] | None) -> list[str]:
    """Return contract violations; empty means a usable P3 v1 block."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["P3 deformer must be an object"]
    if spec.get("version") != P3_VERSION:
        errors.append(f"unsupported P3 version {spec.get('version')!r}")
    cage, binding, keyforms = spec.get("cage"), spec.get("binding"), spec.get("keyforms")
    if not isinstance(cage, dict) or cage.get("cols") != DEFAULT_CAGE_COLS or cage.get("rows") != DEFAULT_CAGE_ROWS:
        errors.append("P3 cage must be a 6x4 control-point lattice")
    if not isinstance(binding, dict) or binding.get("mode") != "bilinear_grid_v1":
        errors.append("P3 binding mode must be bilinear_grid_v1")
    if not isinstance(keyforms, dict) or any(name not in keyforms for name in (
            "neutral", "bust_x_neg", "bust_x_pos", "bust_y_neg", "bust_y_pos")):
        errors.append("P3 keyforms must contain Neutral and BustX/BustY +/- poses")
    return errors
