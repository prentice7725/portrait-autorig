"""P1 strand component, tip, and curtain-weight contracts."""

from __future__ import annotations

import unittest

from portrait_autorig.strand_topology import (
    build_strand_specs, curtain_partition_report, detect_tips, mesh_components,
    weighted_curtain_columns,
)


class StrandTopologyTests(unittest.TestCase):
    def setUp(self):
        # A broad sheet with a lower center tip, plus a disconnected 3-vertex
        # speckle that should be filtered by min_area.
        self.vertices = [
            [0, 0], [20, 0], [40, 0], [0, 20], [20, 32], [40, 20],
            [100, 100], [101, 100], [100, 101],
        ]
        self.triangles = [
            [0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4],
            [6, 7, 8],
        ]

    def test_components_are_connected_and_filter_tiny_speckles(self):
        components = mesh_components(self.vertices, self.triangles, min_area=10)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["vertex_indices"], [0, 1, 2, 3, 4, 5])

    def test_bottom_tip_is_prominent_and_deterministic(self):
        tips = detect_tips(self.vertices, self.triangles, [0, 1, 2, 3, 4, 5],
                           min_separation=8, prominence=1)
        self.assertTrue(tips)
        strongest = max(tips, key=lambda item: item["prominence"])
        self.assertEqual(strongest["vertex_index"], 4)
        self.assertGreater(strongest["prominence"], 0)

    def test_curtain_weights_form_partition_of_unity(self):
        columns = weighted_curtain_columns(self.vertices, vertex_indices=[0, 1, 2, 3, 4, 5],
                                            column_count=5)
        self.assertEqual(len(columns), 5)
        for vertex in range(6):
            total = sum(column["weights"].get(str(vertex), 0.0) for column in columns)
            self.assertAlmostEqual(total, 1.0, places=6)

    def test_strand_specs_include_components_tips_and_columns(self):
        specs = build_strand_specs(self.vertices, self.triangles, min_area=10,
                                   min_separation=8, column_count=3)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["strand_id"], "strand_0")
        self.assertTrue(specs[0]["tips"])
        self.assertEqual(len(specs[0]["columns"]), 3)
        self.assertTrue(specs[0]["partition_qa"]["valid"])

    def test_partition_qa_catches_a_broken_weight_sum(self):
        report = curtain_partition_report(
            [{"weights": {"0": 0.25}}], [0], tolerance=1e-6)
        self.assertFalse(report["valid"])
        self.assertEqual(report["invalid_vertices"], ["0"])


if __name__ == "__main__":
    unittest.main()
