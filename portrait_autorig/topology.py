"""Mesh topology hash / freeze.

`PORTRAIT_AUTORIG_IMPLEMENTATION_DIRECTIVE_v0.2.md` #11-12; Master doc
(`SEETHROUGH_COMPOSER_AUTORIG_RESPONSIBILITY_VERSIONUP_MASTER_v0.2.md`) #11,
Architecture Invariant #10:

    generate mesh -> compute topology_hash -> FREEZE

Once a part's mesh topology hash is in a written Rig Manifest, a later
recompile whose hash for that tag disagrees means any vertex weights,
keyforms, constraints, or physics bindings computed against the old
topology are invalid and must not be silently reused.

AutoRig has no persistent weight/keyform/physics-binding cache of its own
yet -- every compile derives all of that fresh from the input layers, so
there is nothing today that actually *needs* invalidating. This module's
job is narrower and honest about that: compute a deterministic hash per
part so a future cache (or an external tool diffing two manifests) has
something to invalidate against, and provide `topology_changed` for exactly
that comparison. `mesh_topology_hash` hashes *topology* -- vertex count,
triangle/index connectivity, UV count -- never vertex *position*: resizing
a part's box changes its geometry, not its topology, and must hash the
same.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import mesh as mesh_module

__all__ = ["mesh_topology_hash", "topology_changed"]


def _grid_topology(cell: int, xyxy: tuple[int, int, int, int]) -> dict[str, Any]:
    """Vertex count and triangle index list a grid mesh's own `cell`/`xyxy`
    fully determine -- mirrors `gridVertexList` in `preview/runtime.mjs`
    exactly (same cols/rows formula, same triangle winding), since that is
    the topology this hash has to actually match at runtime."""
    x1, y1, x2, y2 = (int(v) for v in xyxy)
    cell = max(4, int(cell))
    cols = max(1, round((x2 - x1) / cell))
    rows = max(1, round((y2 - y1) / cell))
    vertex_count = (cols + 1) * (rows + 1)

    def at(r: int, c: int) -> int:
        return r * (cols + 1) + c

    index: list[int] = []
    for r in range(rows):
        for c in range(cols):
            a, b, d, e = at(r, c), at(r, c + 1), at(r + 1, c), at(r + 1, c + 1)
            index.extend((a, b, d, b, e, d))
    return {"kind": mesh_module.GRID, "vertex_count": vertex_count,
            "uv_count": vertex_count, "index": index}


def _contour_topology(mesh: dict[str, Any]) -> dict[str, Any]:
    """A contour mesh's vertices/triangles are already baked explicitly
    (`mesh.contour_mesh`); topology is just their count and connectivity."""
    vertices = mesh.get("vertices") or []
    triangles = mesh.get("triangles") or []
    index: list[int] = [int(i) for tri in triangles for i in tri]
    return {"kind": mesh_module.CONTOUR, "vertex_count": len(vertices),
            "uv_count": len(vertices), "index": index}


def mesh_topology_hash(mesh: dict[str, Any], xyxy: tuple[int, int, int, int]) -> str:
    """Deterministic `"sha256:..."` over one part's mesh topology --
    vertex count, index/triangle connectivity, UV count. Two meshes with
    the same connectivity hash identically regardless of where their
    vertices actually sit (a resized box is a geometry change, not a
    topology change); a different `cell`/backend kind that happens to
    produce the same cols/rows or vertex/triangle count also hashes
    identically, correctly, since the *topology* -- what a downstream
    weight/keyform/constraint is actually bound to -- is the same.
    """
    kind = mesh.get("kind", mesh_module.GRID)
    if kind == mesh_module.CONTOUR and mesh.get("vertices") is not None:
        topology = _contour_topology(mesh)
    else:
        topology = _grid_topology(mesh.get("cell", mesh_module.MESH_CELL_PX), tuple(xyxy))
    canonical = json.dumps(topology, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def topology_changed(previous_hash: str | None, current_hash: str) -> bool:
    """Whether a part's topology hash disagrees with a prior compile's --
    the trigger Architecture Invariant #10 names for invalidating dependent
    weights/keyforms/constraints/physics bindings rather than silently
    reusing them. `previous_hash=None` (nothing to compare against, e.g. a
    tag's first-ever compile) is never a change."""
    return previous_hash is not None and previous_hash != current_hash
