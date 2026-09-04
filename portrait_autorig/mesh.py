"""Mesh generation for rig parts.

P0 supported exactly one mesh kind: a uniform grid, moved here unchanged from
`rig.py` (see `PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1` #4, #8 -- this
was a contract-extraction step, not a behaviour change). `mesh_spec()` is the
manifest-facing descriptor and carries an explicit `"kind"` alongside the
`"cell"` field, which keeps its current meaning exactly.

P1-A adds a second, experimental kind: a contour-aware triangle mesh, baked
at compile time (`contour_mesh`/`contour_mesh_spec`) rather than generated
procedurally by the runtime the way the grid is. Baking it here -- using
`cv2`, already a dependency -- rather than teaching the browser runtime to
trace contours and Delaunay-triangulate keeps `preview/` a dependency-free,
build-step-free set of files (see `preview/index.html`'s own docstring). Grid
remains the default for every part; `rig.build_rig`'s `contour_tags`
parameter is how a caller opts specific tags into this backend for A/B
comparison against the grid baseline (`preview/check_mesh_quality.mjs`, P1-B)
-- nothing in P1-A changes what an existing manifest looks like on its own.
P1-C adds explicit disconnected-island policies; `separate` is the default
and never creates an implicit bridge between components.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

__all__ = [
    "MESH_REFERENCE_SIZE", "MESH_CELL_PX", "MESH_CELL_MEDIUM_PX", "MESH_CELL_FINE_PX",
    "GRID", "CONTOUR", "CONTOUR_CANDIDATE_TAGS", "ISLAND_POLICIES",
    "DEFAULT_EDGE_POINTS", "DEFAULT_INTERIOR_SPACING", "DEFAULT_EDGE_PADDING",
    "mesh_cell", "mesh_spec", "motion_aware_mesh_spec", "contour_mesh", "contour_mesh_spec",
]

# Uniform grid meshing, quoted against a 768px canvas and scaled from there.
# Parts that deform along a gradient get the finer cell, since that is where
# a coarse grid shows as faceting.
MESH_REFERENCE_SIZE = 768
MESH_CELL_PX = 42
MESH_CELL_MEDIUM_PX = 36
MESH_CELL_FINE_PX = 30

GRID = "grid"
CONTOUR = "contour"


def mesh_cell(frame_size: tuple[int, int], fine: bool) -> int:
    """Grid cell size in pixels, scaled off `frame_size` against the
    reference canvas and floored so a tiny crop still gets a usable mesh."""
    scale = max(int(frame_size[0]), int(frame_size[1])) / MESH_REFERENCE_SIZE
    base = MESH_CELL_FINE_PX if fine else MESH_CELL_PX
    return max(8, int(round(base * scale)))


def mesh_spec(frame_size: tuple[int, int], *, fine: bool) -> dict[str, object]:
    """The part-level `"mesh"` manifest entry for the grid backend."""
    return {"kind": GRID, "cell": mesh_cell(frame_size, fine)}


def motion_aware_mesh_spec(frame_size: tuple[int, int], *, tag: str,
                           group: str = "", deformation_kinds=(),
                           weight_mode: str = "constant") -> dict[str, object]:
    """Select grid density from the deformation actually required by a part.

    Small eye/mouth features and local fields need the fine cell. Hair and
    other head surfaces get a medium cell when they have turn/shell motion;
    static torso surfaces remain coarse.  The returned shape stays compatible
    with the v0.2 mesh contract while recording the decision for diagnostics.
    """
    kinds = {str(kind) for kind in deformation_kinds}
    eye_or_mouth = tag in {"eyewhite", "eyewhitel", "eyewhiter", "irides", "iridesl",
                           "iridesr", "eyes", "eyel", "eyer", "eyelash", "eyelashl",
                           "eyelashr", "mouth"}
    fine = (weight_mode == "gradient_y" or eye_or_mouth
            or bool(kinds & {"eye_fold", "gaze", "local_soft_field"}))
    medium = (not fine and group == "head"
              and bool(kinds & {"parallax_turn", "shell_turn", "continuous_field"}))
    density = "fine" if fine else "medium" if medium else "coarse"
    base = MESH_CELL_FINE_PX if fine else MESH_CELL_MEDIUM_PX if medium else MESH_CELL_PX
    scale = max(int(frame_size[0]), int(frame_size[1])) / MESH_REFERENCE_SIZE
    return {"kind": GRID, "cell": max(8, int(round(base * scale))), "density": density}


# --- Contour mesh (P1-A) ---------------------------------------------------
#
# Candidate tags (absorption plan #8): parts where a tight, alpha-following
# boundary plausibly beats a uniform grid's wasted cells over mostly-empty
# alpha -- fine hair fringes, the face/neck seam. This is a *comparison*
# list for P1-B's mesh QA to judge against the grid baseline, not a default;
# nothing reads it automatically.
CONTOUR_CANDIDATE_TAGS = frozenset({
    "front hair", "back hair", "face", "neck", "neck_remainder",
    "eyelash", "eyebrow",
})

DEFAULT_EDGE_POINTS = 72
DEFAULT_INTERIOR_SPACING = 30
DEFAULT_EDGE_PADDING = 8
ISLAND_POLICIES = frozenset({"separate", "connect_nearest", "largest_only", "reject"})


def _resample_perimeter(points: np.ndarray, n: int) -> np.ndarray:
    """`n` points evenly spaced by arc length around a closed polygon."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3 or n < 3:
        return pts
    closed = np.vstack([pts, pts[:1]])
    seg = closed[1:] - closed[:-1]
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    perimeter = cum[-1]
    if perimeter <= 0:
        return pts[:1]
    targets = np.linspace(0.0, perimeter, n, endpoint=False)
    out = np.empty((n, 2), dtype=np.float64)
    seg_idx = 0
    for i, t in enumerate(targets):
        while seg_idx < len(seg_len) - 1 and cum[seg_idx + 1] < t:
            seg_idx += 1
        span = seg_len[seg_idx]
        frac = 0.0 if span <= 0 else (t - cum[seg_idx]) / span
        out[i] = closed[seg_idx] + seg[seg_idx] * frac
    return out


def _dedup_points(points: np.ndarray, tol: float = 0.75) -> np.ndarray:
    """Drop points within `tol` px of one already kept, by snapping to a
    `tol`-sized grid -- cheap and order-stable, unlike a pairwise distance
    check, and the tolerance is well under anything visually meaningful."""
    kept: list[tuple[float, float]] = []
    seen: set[tuple[int, int]] = set()
    for x, y in points:
        key = (int(round(float(x) / tol)), int(round(float(y) / tol)))
        if key in seen:
            continue
        seen.add(key)
        kept.append((float(x), float(y)))
    return np.array(kept, dtype=np.float64).reshape(-1, 2)


def contour_mesh(alpha: np.ndarray, xyxy: tuple[int, int, int, int], *,
                 edge_points: int = DEFAULT_EDGE_POINTS,
                 interior_spacing: int = DEFAULT_INTERIOR_SPACING,
                 edge_padding: int = DEFAULT_EDGE_PADDING,
                 alpha_threshold: int = 10,
                 dilate_px: int = 1,
                 island_policy: str = "separate") -> dict[str, Any] | None:
    """Contour-aware triangle mesh for one part (absorption plan #8):

      1. dilate the alpha mask a little (closes small gaps from a soft edge
         before tracing)
      2. trace its outer contour
      3. resample the contour perimeter into `edge_points` evenly spaced
         points
      4. lay an interior grid at `interior_spacing` px
      5. drop interior points within `edge_padding` px of the mask boundary
      6. deduplicate
      7. Delaunay-triangulate everything that is left
      8. drop triangles whose centroid falls outside the mask (a concave
         gap, e.g. between hair strands)

    `alpha` is the part's own crop -- the same HxW array `crop_to_alpha`
    already produces -- and `xyxy` its canvas placement, matching every
    other per-part geometry function in `rig.py`. Returns
    `{"vertices": [[x, y], ...], "triangles": [[a, b, c], ...]}` in absolute
    canvas pixel coordinates (`xyxy`'s offset already applied, so the runtime
    treats them exactly like the grid backend's canvas-absolute vertices), or
    None when there is nothing usable to triangulate. Disconnected alpha
    follows `island_policy`: `separate` (default) keeps components disjoint,
    `largest_only` discards smaller components, `reject` returns None, and
    `connect_nearest` adds explicit narrow bridges.
    """
    if island_policy not in ISLAND_POLICIES:
        raise ValueError(f"unsupported island policy: {island_policy!r}")
    x1, y1, x2, y2 = (int(v) for v in xyxy)
    width, height = x2 - x1, y2 - y1
    if width <= 0 or height <= 0:
        return None
    mask = (np.asarray(alpha) > alpha_threshold).astype(np.uint8)
    if mask.shape != (height, width):
        raise ValueError(f"alpha shape {mask.shape} does not match xyxy {width}x{height}")
    if dilate_px > 0:
        kernel = np.ones((2 * dilate_px + 1, 2 * dilate_px + 1), np.uint8)
        mask = cv2.dilate(mask, kernel)
    if not np.any(mask):
        return None

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = [c for c in contours if len(c) >= 3]
    if len(contours) != 1:
        if len(contours) < 1 or island_policy == "reject":
            return None
        if island_policy == "largest_only":
            largest = max(contours, key=cv2.contourArea)
            mask = np.zeros_like(mask)
            cv2.drawContours(mask, [largest], -1, 1, thickness=cv2.FILLED)
            contours = [largest]
        elif island_policy == "separate":
            vertices: list[list[float]] = []
            triangles: list[list[int]] = []
            # Each component gets its own triangulation.  Combining the
            # indexed results preserves disconnected topology: no triangle
            # can bridge two islands by construction.
            for contour in sorted(contours, key=cv2.contourArea, reverse=True):
                component = np.zeros_like(mask)
                cv2.drawContours(component, [contour], -1, 1, thickness=cv2.FILLED)
                piece = contour_mesh(
                    component * 255, xyxy, edge_points=edge_points,
                    interior_spacing=interior_spacing, edge_padding=edge_padding,
                    alpha_threshold=alpha_threshold, dilate_px=0,
                    island_policy="reject")
                if not piece:
                    continue
                offset = len(vertices)
                vertices.extend(piece["vertices"])
                triangles.extend([[a + offset, b + offset, c + offset]
                                  for a, b, c in piece["triangles"]])
            return {"vertices": vertices, "triangles": triangles} if triangles else None
        elif island_policy == "connect_nearest":
            # Explicitly requested bridging: join each smaller component to
            # the current union by a one-pixel corridor between nearest
            # contour points, then run the normal single-surface path.
            merged = mask.copy()
            base = contours[0]
            for contour in contours[1:]:
                a = base.reshape(-1, 2)[:, None, :]
                b = contour.reshape(-1, 2)[None, :, :]
                ia, ib = np.unravel_index(np.argmin(((a - b) ** 2).sum(axis=2)),
                                          ((a.shape[0]), (b.shape[1])))
                cv2.line(merged, tuple(int(v) for v in base.reshape(-1, 2)[ia]),
                         tuple(int(v) for v in contour.reshape(-1, 2)[ib]), 1,
                         max(1, int(edge_padding)))
                base = np.vstack([base.reshape(-1, 2), contour.reshape(-1, 2)])[:, None, :]
            mask = merged
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if len(contours) != 1:
                return None
    edge_pts = _resample_perimeter(contours[0].reshape(-1, 2).astype(np.float64), edge_points)

    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    h, w = mask.shape
    step = max(1, int(interior_spacing))
    interior = [(float(x), float(y))
                for y in range(0, h, step) for x in range(0, w, step)
                if mask[y, x] and dist[y, x] >= edge_padding]

    all_pts = _dedup_points(np.vstack([edge_pts, np.array(interior, dtype=np.float64).reshape(-1, 2)]))
    if len(all_pts) < 3:
        return None

    # Subdiv2D requires strictly-interior points; nudge onto [0, w)x[0, h)
    # rather than dropping edge points the perimeter resampling landed
    # exactly on the boundary, which it frequently does.
    clamped = np.clip(all_pts, [0.0, 0.0], [w - 1e-3, h - 1e-3])
    subdiv = cv2.Subdiv2D((0, 0, w, h))
    index_of: dict[tuple[float, float], int] = {}
    for i, (x, y) in enumerate(clamped):
        key = (round(float(x), 2), round(float(y), 2))
        if key in index_of:
            continue  # exact duplicate after clamping; keep the first index
        try:
            subdiv.insert((float(x), float(y)))
        except cv2.error:
            continue
        index_of[key] = i

    triangles: list[list[int]] = []
    for tri in subdiv.getTriangleList():
        tri_pts = [(tri[0], tri[1]), (tri[2], tri[3]), (tri[4], tri[5])]
        if not all(0 <= px < w and 0 <= py < h for px, py in tri_pts):
            continue  # Subdiv2D emits triangles touching its bounding rect
        idxs = [index_of.get((round(px, 2), round(py, 2))) for px, py in tri_pts]
        if any(i is None for i in idxs):
            continue
        cxi, cyi = int(sum(p[0] for p in tri_pts) / 3.0), int(sum(p[1] for p in tri_pts) / 3.0)
        if not (0 <= cxi < w and 0 <= cyi < h and mask[cyi, cxi]):
            continue  # centroid outside the mask: a concave-gap sliver
        a, b, c = idxs
        area2 = ((clamped[b][0] - clamped[a][0]) * (clamped[c][1] - clamped[a][1])
                - (clamped[c][0] - clamped[a][0]) * (clamped[b][1] - clamped[a][1]))
        if abs(area2) < 1e-6:
            continue  # degenerate sliver
        triangles.append([a, b, c])

    if not triangles:
        return None
    vertices = [[round(float(px + x1), 2), round(float(py + y1), 2)] for px, py in all_pts]
    return {"vertices": vertices, "triangles": triangles}


def contour_mesh_spec(alpha: np.ndarray, xyxy: tuple[int, int, int, int], *,
                      edge_points: int = DEFAULT_EDGE_POINTS,
                      interior_spacing: int = DEFAULT_INTERIOR_SPACING,
                      edge_padding: int = DEFAULT_EDGE_PADDING,
                      alpha_threshold: int = 10,
                      island_policy: str = "separate") -> dict[str, Any] | None:
    """The part-level `"mesh"` manifest entry for the contour backend, or
    None when `contour_mesh` could not produce one -- the caller's cue to
    fall back to `mesh_spec` (grid) for that part instead."""
    baked = contour_mesh(alpha, xyxy, edge_points=edge_points,
                         interior_spacing=interior_spacing, edge_padding=edge_padding,
                         alpha_threshold=alpha_threshold, island_policy=island_policy)
    if baked is None:
        return None
    return {
        "kind": CONTOUR, "edge_points": edge_points,
        "interior_spacing": interior_spacing, "edge_padding": edge_padding,
        "island_policy": island_policy,
        **baked,
    }
