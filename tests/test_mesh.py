"""Tests for mesh.py -- mesh cell sizing, extracted unchanged from rig.py.

See PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1 #4, #18 (P0-A: contract
extraction, no behaviour change).
"""

from __future__ import annotations

import unittest

from portrait_autorig.mesh import (
    GRID, MESH_CELL_FINE_PX, MESH_CELL_PX, MESH_REFERENCE_SIZE,
    mesh_cell, mesh_spec,
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


class MeshSpecTests(unittest.TestCase):
    def test_spec_carries_kind_and_cell(self):
        spec = mesh_spec((768, 768), fine=False)
        self.assertEqual(spec, {"kind": GRID, "cell": MESH_CELL_PX})

    def test_spec_kind_is_always_grid_in_p0(self):
        # P0 supports exactly one mesh kind; a contour/adaptive backend is a
        # P1 concern (absorption plan #8) that reuses this same field.
        for fine in (True, False):
            self.assertEqual(mesh_spec((768, 768), fine=fine)["kind"], "grid")


if __name__ == "__main__":
    unittest.main()
