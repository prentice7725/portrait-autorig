"""Deterministic hair-sheet strand topology helpers (P1).

This module deliberately stops at *topology*.  It does not simulate springs or
change a source image.  A baked mesh is partitioned into connected triangle
components, prominent bottom tips are detected from each component boundary,
and wide sheets receive overlapping curtain-column weights whose sum is one at
every vertex.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable, Sequence

import numpy as np

__all__ = [
    "mesh_components", "detect_tips", "weighted_curtain_columns",
    "curtain_partition_report", "build_strand_specs",
]


def _as_vertices(vertices: Sequence[Sequence[float]]) -> np.ndarray:
    array = np.asarray(vertices, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError("vertices must have shape (N, 2)")
    return array


def _as_triangles(triangles: Sequence[Sequence[int]]) -> np.ndarray:
    array = np.asarray(triangles, dtype=np.int64)
    if array.size == 0:
        return np.empty((0, 3), dtype=np.int64)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError("triangles must have shape (M, 3)")
    if np.any(array < 0):
        raise ValueError("triangle indices must be non-negative")
    return array


def mesh_components(vertices: Sequence[Sequence[float]],
                    triangles: Sequence[Sequence[int]], *,
                    min_vertices: int = 3,
                    min_area: float = 0.0) -> list[dict[str, Any]]:
    """Return deterministic connected components of a triangle mesh.

    Components are connected through shared mesh vertices, rather than by
    testing rendered pixels.  Small speckles are omitted using both a vertex
    count and an optional geometric area threshold, so they cannot become
    independent strands.
    """
    verts = _as_vertices(vertices)
    tris = _as_triangles(triangles)
    if np.any(tris >= len(verts)):
        raise ValueError("triangle index is outside vertices")
    if min_vertices < 1 or min_area < 0:
        raise ValueError("min_vertices must be positive and min_area non-negative")

    by_vertex: dict[int, list[int]] = defaultdict(list)
    for ti, tri in enumerate(tris):
        for vertex in set(int(v) for v in tri):
            by_vertex[vertex].append(ti)
    unseen = set(range(len(tris)))
    result: list[dict[str, Any]] = []
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        queue = deque([seed])
        triangle_ids: list[int] = []
        while queue:
            ti = queue.popleft()
            triangle_ids.append(ti)
            for vertex in tris[ti]:
                for other in by_vertex[int(vertex)]:
                    if other in unseen:
                        unseen.remove(other)
                        queue.append(other)
        tri_ids = sorted(triangle_ids)
        vertex_ids = sorted({int(v) for ti in tri_ids for v in tris[ti]})
        area = 0.0
        for ti in tri_ids:
            a, b, c = (verts[int(v)] for v in tris[ti])
            area += abs(float((b[0] - a[0]) * (c[1] - a[1])
                              - (b[1] - a[1]) * (c[0] - a[0]))) * 0.5
        if len(vertex_ids) < min_vertices or area < min_area:
            continue
        result.append({
            "component_id": len(result),
            "triangle_indices": tri_ids,
            "vertex_indices": vertex_ids,
            "area": round(area, 6),
            "bbox": [
                float(np.min(verts[vertex_ids, 0])), float(np.min(verts[vertex_ids, 1])),
                float(np.max(verts[vertex_ids, 0])), float(np.max(verts[vertex_ids, 1])),
            ],
        })
    return result


def _boundary_vertices(triangles: np.ndarray, vertex_ids: Iterable[int]) -> list[int]:
    allowed = set(int(v) for v in vertex_ids)
    edges: dict[tuple[int, int], int] = defaultdict(int)
    for tri in triangles:
        for a, b in ((int(tri[0]), int(tri[1])),
                     (int(tri[1]), int(tri[2])),
                     (int(tri[2]), int(tri[0]))):
            edge = (a, b) if a < b else (b, a)
            edges[edge] += 1
    return sorted({v for edge, count in edges.items() if count == 1 for v in edge
                   if v in allowed})


def detect_tips(vertices: Sequence[Sequence[float]],
                triangles: Sequence[Sequence[int]],
                vertex_indices: Sequence[int] | None = None, *,
                min_separation: float = 12.0,
                prominence: float = 1.0,
                max_tips: int = 8) -> list[dict[str, Any]]:
    """Detect separated, prominent bottom points on one mesh component.

    ``y`` increases downward in the image coordinate system.  Candidates are
    boundary vertices that are at least ``prominence`` pixels below the local
    boundary median; a greedy distance filter prevents noisy adjacent pixels
    from producing a forest of fake tips.
    """
    verts = _as_vertices(vertices)
    tris = _as_triangles(triangles)
    if np.any(tris >= len(verts)):
        raise ValueError("triangle index is outside vertices")
    ids = sorted(set(range(len(verts)) if vertex_indices is None else
                     (int(v) for v in vertex_indices)))
    if not ids:
        return []
    boundary = _boundary_vertices(tris[np.all(np.isin(tris, ids), axis=1)], ids)
    if not boundary:
        return []
    points = verts[boundary]
    y_max = float(np.max(points[:, 1]))
    # The component's boundary median is a scale-free local baseline.  A
    # bottom contour vertex is prominent when it projects materially below
    # that baseline; the distance filter below removes adjacent anti-aliased
    # pixels from the same tip.
    local = float(np.median(points[:, 1]))
    candidates = [
        (int(v), float(verts[v, 1] - local)) for v in boundary
        if float(verts[v, 1] - local) >= float(prominence)
    ]
    candidates.sort(key=lambda item: (-item[1], float(verts[item[0], 0]), item[0]))
    selected: list[dict[str, Any]] = []
    for vertex, score in candidates:
        point = verts[vertex]
        if any(float(np.linalg.norm(point - verts[int(item["vertex_index"])]))
               < min_separation for item in selected):
            continue
        selected.append({
            "vertex_index": vertex,
            "position": [round(float(point[0]), 4), round(float(point[1]), 4)],
            "prominence": round(max(0.0, score), 4),
        })
        if len(selected) >= max_tips:
            break
    selected.sort(key=lambda item: (item["position"][0], item["position"][1],
                                    item["vertex_index"]))
    return selected


def weighted_curtain_columns(vertices: Sequence[Sequence[float]], *,
                             vertex_indices: Sequence[int] | None = None,
                             column_count: int = 5) -> list[dict[str, Any]]:
    """Build overlapping horizontal curtain columns with partition-of-unity weights."""
    verts = _as_vertices(vertices)
    ids = sorted(set(range(len(verts)) if vertex_indices is None else
                     (int(v) for v in vertex_indices)))
    if not ids:
        return []
    if column_count < 1:
        raise ValueError("column_count must be positive")
    left, right = float(np.min(verts[ids, 0])), float(np.max(verts[ids, 0]))
    if right <= left or column_count == 1:
        centers = np.array([(left + right) * 0.5])
    else:
        centers = np.linspace(left, right, int(column_count))
    spacing = float(centers[1] - centers[0]) if len(centers) > 1 else 1.0
    columns = [{"column_id": i, "center_x": round(float(x), 4), "weights": {}}
               for i, x in enumerate(centers)]
    for vertex in ids:
        distances = np.maximum(0.0, 1.0 - np.abs(float(verts[vertex, 0]) - centers) /
                               max(spacing, 1e-9))
        if not np.any(distances):
            distances[int(np.argmin(np.abs(float(verts[vertex, 0]) - centers)))] = 1.0
        distances /= float(np.sum(distances))
        for column, weight in zip(columns, distances):
            if weight > 1e-9:
                column["weights"][str(vertex)] = round(float(weight), 8)
    return columns


def curtain_partition_report(columns: Sequence[dict[str, Any]],
                             vertex_indices: Sequence[int], *,
                             tolerance: float = 1e-6) -> dict[str, Any]:
    """QA report for the partition-of-unity invariant of curtain columns."""
    ids = sorted(set(int(v) for v in vertex_indices))
    sums = {
        str(vertex): sum(float(column.get("weights", {}).get(str(vertex), 0.0))
                         for column in columns)
        for vertex in ids
    }
    errors = {vertex: abs(total - 1.0) for vertex, total in sums.items()}
    invalid = [vertex for vertex, error in errors.items() if error > tolerance]
    return {
        "vertices_checked": len(ids),
        "max_error": round(max(errors.values(), default=0.0), 8),
        "valid": not invalid,
        "invalid_vertices": invalid,
    }


def build_strand_specs(vertices: Sequence[Sequence[float]],
                       triangles: Sequence[Sequence[int]], *,
                       min_vertices: int = 3,
                       min_area: float = 0.0,
                       min_separation: float = 12.0,
                       prominence: float = 1.0,
                       column_count: int = 5) -> list[dict[str, Any]]:
    """Compile mesh components into manifest-ready ``StrandSpec`` dictionaries."""
    verts = _as_vertices(vertices)
    tris = _as_triangles(triangles)
    components = mesh_components(verts, tris, min_vertices=min_vertices, min_area=min_area)
    specs: list[dict[str, Any]] = []
    for component in components:
        ids = component["vertex_indices"]
        spec = {
            "strand_id": f"strand_{len(specs)}",
            "component_id": component["component_id"],
            "vertex_indices": ids,
            "triangle_indices": component["triangle_indices"],
            "tips": detect_tips(verts, tris, ids, min_separation=min_separation,
                                 prominence=prominence),
            "columns": weighted_curtain_columns(verts, vertex_indices=ids,
                                                 column_count=column_count),
        }
        spec["partition_qa"] = curtain_partition_report(spec["columns"], ids)
        specs.append(spec)
    return specs
