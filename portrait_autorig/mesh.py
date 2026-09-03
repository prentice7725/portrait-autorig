"""Mesh generation for rig parts.

P0 supports exactly one mesh kind: a uniform grid, moved here unchanged from
`rig.py` (see `PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1` #4, #8 -- this
is a contract-extraction step, not a behaviour change). `mesh_spec()` is the
manifest-facing descriptor and now carries an explicit `"kind"` alongside the
existing `"cell"`, forward-declaring the field a future contour/adaptive
backend (P1) will need without another manifest migration; `"cell"` keeps its
current meaning exactly, so nothing that reads it today is affected.
"""

from __future__ import annotations

__all__ = ["MESH_REFERENCE_SIZE", "MESH_CELL_PX", "MESH_CELL_FINE_PX",
           "GRID", "mesh_cell", "mesh_spec"]

# Uniform grid meshing, quoted against a 768px canvas and scaled from there.
# Parts that deform along a gradient get the finer cell, since that is where
# a coarse grid shows as faceting.
MESH_REFERENCE_SIZE = 768
MESH_CELL_PX = 42
MESH_CELL_FINE_PX = 30

GRID = "grid"


def mesh_cell(frame_size: tuple[int, int], fine: bool) -> int:
    """Grid cell size in pixels, scaled off `frame_size` against the
    reference canvas and floored so a tiny crop still gets a usable mesh."""
    scale = max(int(frame_size[0]), int(frame_size[1])) / MESH_REFERENCE_SIZE
    base = MESH_CELL_FINE_PX if fine else MESH_CELL_PX
    return max(8, int(round(base * scale)))


def mesh_spec(frame_size: tuple[int, int], *, fine: bool) -> dict[str, object]:
    """The part-level `"mesh"` manifest entry."""
    return {"kind": GRID, "cell": mesh_cell(frame_size, fine)}
