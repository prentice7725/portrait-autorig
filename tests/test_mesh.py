"""Tests for mesh.py -- mesh cell sizing (P0-A) and the contour mesh backend
(P1-A).

See PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1 #4, #8, #18.
"""

from __future__ import annotations

import unittest

import numpy as np

from portrait_autorig.mesh import (
    CONTOUR, GRID, MESH_CELL_FINE_PX, MESH_CELL_PX, MESH_REFERENCE_SIZE,
    contour_mesh, contour_mesh_spec, mesh_cell, mesh_spec,
    motion_aware_mesh_spec,
)


class MeshCellTests(unittest.TestCase):
    def test_reference_canvas_returns_the_base_cell_size_unscaled(self):
        self.assertEqual(mesh_cell((MESH_REFERENCE_SIZE, MESH_REFERENCE_SIZE), fine=False),
                         MESH_CELL_PX)
        self.assertEqual(mesh_cell((MESH_REFERENCE_SIZE, MESH_REFERENCE_SIZE), fine=True),
                         MESH_CELL_FINE_PX)

    def test_fine_cell_is_smaller_than_coarse_at_every_scale(self):
        for size in ((384, 384), (768, 768), (1536, 1536)):
            self.assertLess(mesh_cell(size, fine=True), mesh_cell(size, fine=False))

    def test_larger_canvas_scales_the_cell_up(self):
        small = mesh_cell((768, 768), fine=False)
        large = mesh_cell((1536, 1536), fine=False)
        self.assertGreater(large, small)

    def test_cell_size_never_drops_below_the_floor(self):
        # A tiny crop should still get a usable mesh rather than a
        # near-zero cell that degenerates into a vertex-per-pixel grid.
        self.assertGreaterEqual(mesh_cell((16, 16), fine=True), 8)

    def test_scale_uses_the_longer_side(self):
        square = mesh_cell((768, 768), fine=False)
        wide = mesh_cell((768, 1536), fine=False)
        self.assertEqual(wide, mesh_cell((1536, 1536), fine=False))
        self.assertGreater(wide, square)


class MotionAwareDensityTests(unittest.TestCase):
    def test_eye_features_use_fine_density(self):
        spec = motion_aware_mesh_spec((768, 768), tag="iridesl", group="head",
                                      deformation_kinds=("gaze",))
        self.assertEqual(spec["density"], "fine")
        self.assertEqual(spec["cell"], MESH_CELL_FINE_PX)

    def test_head_turn_surface_uses_medium_density(self):
        spec = motion_aware_mesh_spec((768, 768), tag="face", group="head",
                                      deformation_kinds=("parallax_turn",))
        self.assertEqual(spec["density"], "medium")

    def test_static_body_surface_stays_coarse(self):
        spec = motion_aware_mesh_spec((768, 768), tag="body", group="body")
        self.assertEqual(spec["density"], "coarse")
        self.assertEqual(spec["cell"], MESH_CELL_PX)

    def test_local_soft_field_promotes_target_to_fine(self):
        spec = motion_aware_mesh_spec((768, 768), tag="topwear", group="body",
                                      deformation_kinds=("local_soft_field",))
        self.assertEqual(spec["density"], "fine")


class MeshSpecTests(unittest.TestCase):
    def test_spec_carries_kind_and_cell(self):
        spec = mesh_spec((768, 768), fine=False)
        self.assertEqual(spec, {"kind": GRID, "cell": MESH_CELL_PX})

    def test_spec_kind_is_always_grid_in_p0(self):
        # P0 supports exactly one mesh kind; a contour/adaptive backend is a
        # P1 concern (absorption plan #8) that reuses this same field.
        for fine in (True, False):
            self.assertEqual(mesh_spec((768, 768), fine=fine)["kind"], "grid")


def _disk_alpha(size=200, radius=80, cx=100, cy=100):
    yy, xx = np.mgrid[0:size, 0:size]
    return (((xx - cx) ** 2 + (yy - cy) ** 2 <= radius * radius).astype(np.uint8) * 255)


def _triangle_area2(vertices, triangle):
    a, b, c = (vertices[i] for i in triangle)
    return (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])


class ContourMeshTests(unittest.TestCase):
    def test_returns_none_for_empty_alpha(self):
        empty = np.zeros((200, 200), np.uint8)
        self.assertIsNone(contour_mesh(empty, (0, 0, 200, 200)))

    def test_separate_policy_keeps_two_disconnected_islands_without_bridges(self):
        two = np.zeros((200, 200), np.uint8)
        two[20:40, 20:40] = 255
        two[150:170, 150:170] = 255
        result = contour_mesh(two, (0, 0, 200, 200), island_policy="separate")
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result["triangles"]), 2)
        for triangle in result["triangles"]:
            xs = [result["vertices"][i][0] for i in triangle]
            ys = [result["vertices"][i][1] for i in triangle]
            self.assertTrue(max(xs) < 60 or min(xs) > 130)
            self.assertTrue(max(ys) < 60 or min(ys) > 130)

    def test_reject_policy_returns_none_for_two_disconnected_islands(self):
        two = np.zeros((200, 200), np.uint8)
        two[20:40, 20:40] = 255
        two[150:170, 150:170] = 255
        self.assertIsNone(contour_mesh(two, (0, 0, 200, 200), island_policy="reject"))

    def test_largest_only_policy_discards_smaller_island(self):
        two = np.zeros((200, 200), np.uint8)
        two[10:35, 10:35] = 255
        two[120:180, 120:180] = 255
        result = contour_mesh(two, (0, 0, 200, 200), island_policy="largest_only",
                              edge_points=32, interior_spacing=15, edge_padding=4)
        self.assertIsNotNone(result)
        self.assertTrue(all(v[0] > 100 and v[1] > 100 for v in result["vertices"]))

    def test_connect_nearest_policy_explicitly_bridges_large_islands(self):
        two = np.zeros((200, 200), np.uint8)
        two[10:70, 10:70] = 255
        two[120:190, 120:190] = 255
        result = contour_mesh(two, (0, 0, 200, 200), island_policy="connect_nearest",
                              edge_points=32, interior_spacing=15, edge_padding=4)
        self.assertIsNotNone(result)
        xs = [vertex[0] for vertex in result["vertices"]]
        self.assertLess(min(xs), 70)
        self.assertGreater(max(xs), 120)
        self.assertTrue(any(70 < x < 120 for x in xs))

    def test_unknown_island_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            contour_mesh(_disk_alpha(), (0, 0, 200, 200), island_policy="guess")

    def test_raises_when_alpha_shape_disagrees_with_xyxy(self):
        alpha = _disk_alpha()
        with self.assertRaises(ValueError):
            contour_mesh(alpha, (0, 0, 999, 999))

    def test_produces_vertices_and_triangles_for_a_filled_disk(self):
        result = contour_mesh(_disk_alpha(), (50, 50, 250, 250),
                              edge_points=40, interior_spacing=20, edge_padding=6)
        self.assertIsNotNone(result)
        self.assertGreater(len(result["vertices"]), 20)
        self.assertGreater(len(result["triangles"]), 10)

    def test_triangle_indices_are_all_in_range(self):
        result = contour_mesh(_disk_alpha(), (50, 50, 250, 250))
        n = len(result["vertices"])
        for triangle in result["triangles"]:
            self.assertEqual(len(triangle), 3)
            for index in triangle:
                self.assertGreaterEqual(index, 0)
                self.assertLess(index, n)

    def test_no_degenerate_zero_area_triangles(self):
        result = contour_mesh(_disk_alpha(), (50, 50, 250, 250))
        for triangle in result["triangles"]:
            self.assertGreater(abs(_triangle_area2(result["vertices"], triangle)), 1e-6)

    def test_vertices_are_offset_into_absolute_canvas_coordinates(self):
        # The disk is centred at local (100, 100); xyxy places the part's
        # origin at canvas (50, 50), so every vertex should land inside the
        # disk's canvas-absolute bounding box, not the local one.
        result = contour_mesh(_disk_alpha(), (50, 50, 250, 250))
        xs = [v[0] for v in result["vertices"]]
        ys = [v[1] for v in result["vertices"]]
        self.assertGreaterEqual(min(xs), 50 + 100 - 80 - 5)
        self.assertLessEqual(max(xs), 50 + 100 + 80 + 5)
        self.assertGreaterEqual(min(ys), 50 + 100 - 80 - 5)
        self.assertLessEqual(max(ys), 50 + 100 + 80 + 5)

    def test_no_triangle_centroid_falls_in_a_concave_gap(self):
        # An "L" shape: the top-right quadrant is missing alpha entirely, but
        # the remaining region is still one connected island. A naive convex
        # triangulation would bridge straight across the missing quadrant;
        # the centroid-in-mask rejection (step 8) must reject every such
        # triangle instead of leaving a sliver of "mesh" over empty alpha.
        size = 200
        alpha = np.full((size, size), 255, np.uint8)
        alpha[0:100, 100:200] = 0  # missing top-right quadrant
        result = contour_mesh(alpha, (0, 0, size, size),
                              edge_points=60, interior_spacing=15, edge_padding=4)
        self.assertIsNotNone(result)
        margin = 6  # dilation/resampling slack at the concave corner
        for triangle in result["triangles"]:
            verts = [result["vertices"][i] for i in triangle]
            cx = sum(v[0] for v in verts) / 3.0
            cy = sum(v[1] for v in verts) / 3.0
            in_missing_quadrant = cx > 100 + margin and cy < 100 - margin
            self.assertFalse(in_missing_quadrant,
                             f"triangle centroid ({cx:.1f}, {cy:.1f}) sits in the missing quadrant")


class ContourMeshSpecTests(unittest.TestCase):
    def test_spec_carries_kind_and_baked_geometry(self):
        spec = contour_mesh_spec(_disk_alpha(), (50, 50, 250, 250))
        self.assertEqual(spec["kind"], CONTOUR)
        self.assertIn("vertices", spec)
        self.assertIn("triangles", spec)
        self.assertEqual(spec["edge_points"], 72)
        self.assertEqual(spec["interior_spacing"], 30)
        self.assertEqual(spec["edge_padding"], 8)
        self.assertEqual(spec["island_policy"], "separate")

    def test_spec_is_none_when_contour_mesh_is_none(self):
        empty = np.zeros((200, 200), np.uint8)
        self.assertIsNone(contour_mesh_spec(empty, (0, 0, 200, 200)))

    def test_spec_echoes_custom_parameters(self):
        spec = contour_mesh_spec(_disk_alpha(), (50, 50, 250, 250),
                                 edge_points=48, interior_spacing=25, edge_padding=5)
        self.assertEqual(spec["edge_points"], 48)
        self.assertEqual(spec["interior_spacing"], 25)
        self.assertEqual(spec["edge_padding"], 5)


if __name__ == "__main__":
    unittest.main()
