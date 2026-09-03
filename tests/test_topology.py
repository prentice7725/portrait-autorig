"""Tests for topology.py -- mesh topology hash / freeze.

See PORTRAIT_AUTORIG_IMPLEMENTATION_DIRECTIVE_v0.2.md #11-12, Master doc
Architecture Invariant #10, and PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN
v0.1 #18 (P0-G).
"""

from __future__ import annotations

import unittest

from portrait_autorig.mesh import mesh_spec
from portrait_autorig.topology import mesh_topology_hash, topology_changed


class GridTopologyHashTests(unittest.TestCase):
    def test_hash_is_a_sha256_string(self):
        spec = mesh_spec((768, 768), fine=False)
        h = mesh_topology_hash(spec, (0, 0, 100, 100))
        self.assertTrue(h.startswith("sha256:"))
        self.assertEqual(len(h), len("sha256:") + 64)

    def test_same_cell_and_box_hash_identically(self):
        spec = mesh_spec((768, 768), fine=False)
        a = mesh_topology_hash(spec, (10, 10, 110, 110))
        b = mesh_topology_hash(spec, (10, 10, 110, 110))
        self.assertEqual(a, b)

    def test_resizing_the_box_without_changing_cols_rows_hashes_identically(self):
        # A geometry change, not a topology change: same connectivity, the
        # vertex *positions* just land somewhere else.
        spec = {"kind": "grid", "cell": 50}
        a = mesh_topology_hash(spec, (0, 0, 100, 100))
        b = mesh_topology_hash(spec, (200, 200, 300, 300))  # same size, moved
        self.assertEqual(a, b)

    def test_a_different_cell_count_changes_the_hash(self):
        coarse = mesh_topology_hash({"kind": "grid", "cell": 50}, (0, 0, 100, 100))
        fine = mesh_topology_hash({"kind": "grid", "cell": 10}, (0, 0, 100, 100))
        self.assertNotEqual(coarse, fine)

    def test_a_bigger_box_at_the_same_cell_changes_the_hash(self):
        small = mesh_topology_hash({"kind": "grid", "cell": 20}, (0, 0, 100, 100))
        big = mesh_topology_hash({"kind": "grid", "cell": 20}, (0, 0, 400, 400))
        self.assertNotEqual(small, big)


class ContourTopologyHashTests(unittest.TestCase):
    def test_same_vertices_and_triangles_hash_identically(self):
        contour = {"kind": "contour", "vertices": [[0, 0], [10, 0], [0, 10]],
                  "triangles": [[0, 1, 2]]}
        a = mesh_topology_hash(contour, (0, 0, 10, 10))
        b = mesh_topology_hash(contour, (0, 0, 10, 10))
        self.assertEqual(a, b)

    def test_moving_vertices_without_changing_connectivity_hashes_identically(self):
        # Topology, not geometry: the same triangle at a different position
        # has the same connectivity.
        a = mesh_topology_hash(
            {"kind": "contour", "vertices": [[0, 0], [10, 0], [0, 10]], "triangles": [[0, 1, 2]]},
            (0, 0, 10, 10))
        b = mesh_topology_hash(
            {"kind": "contour", "vertices": [[100, 100], [110, 100], [100, 110]], "triangles": [[0, 1, 2]]},
            (100, 100, 110, 110))
        self.assertEqual(a, b)

    def test_a_different_triangle_count_changes_the_hash(self):
        one_tri = mesh_topology_hash(
            {"kind": "contour", "vertices": [[0, 0], [10, 0], [0, 10]], "triangles": [[0, 1, 2]]},
            (0, 0, 10, 10))
        two_tri = mesh_topology_hash(
            {"kind": "contour", "vertices": [[0, 0], [10, 0], [0, 10], [10, 10]],
             "triangles": [[0, 1, 2], [1, 3, 2]]},
            (0, 0, 10, 10))
        self.assertNotEqual(one_tri, two_tri)

    def test_grid_and_contour_of_the_same_shape_hash_differently(self):
        # kind is part of the topology identity even if counts coincide.
        grid = mesh_topology_hash({"kind": "grid", "cell": 100}, (0, 0, 100, 100))
        contour = mesh_topology_hash(
            {"kind": "contour", "vertices": [[0, 0], [100, 0], [0, 100], [100, 100]],
             "triangles": [[0, 1, 2], [1, 3, 2]]},
            (0, 0, 100, 100))
        self.assertNotEqual(grid, contour)


class TopologyChangedTests(unittest.TestCase):
    def test_no_previous_hash_is_never_a_change(self):
        self.assertFalse(topology_changed(None, "sha256:abc"))

    def test_matching_hashes_are_not_a_change(self):
        self.assertFalse(topology_changed("sha256:abc", "sha256:abc"))

    def test_differing_hashes_are_a_change(self):
        self.assertTrue(topology_changed("sha256:abc", "sha256:def"))


if __name__ == "__main__":
    unittest.main()
