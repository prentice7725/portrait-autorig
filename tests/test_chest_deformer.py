import unittest

import numpy as np

from portrait_autorig.chest_deformer import (
    DEFAULT_CAGE_COLS,
    DEFAULT_CAGE_ROWS,
    build_chest_parametric_deformer,
    validate_chest_parametric_deformer,
)


class ChestDeformerGenerationTests(unittest.TestCase):
    def setUp(self):
        self.part = {
            "name": "topwear_with_handwear",
            "source_instance_id": "topwear_with_handwear__instance",
            "tag": "topwear_with_handwear", "xyxy": [20, 40, 220, 260],
            "mesh": {"kind": "grid", "cell": 40,
                     "refinement": {"region": [55, 90, 185, 210], "cell": 20}},
        }
        self.spec = {
            "enabled": True, "source": "assembly_rig_intent",
            "coordinate_space": "canvas_normalized",
            "left": {"center": [0.32, 0.46], "radius": [0.18, 0.22]},
            "right": {"center": [0.68, 0.46], "radius": [0.18, 0.22]},
        }

    def test_continuous_6x4_cage_and_binding(self):
        spec = build_chest_parametric_deformer(self.part, self.spec, frame_size=(300, 300))
        self.assertEqual(spec["cage"]["cols"], DEFAULT_CAGE_COLS)
        self.assertEqual(spec["cage"]["rows"], DEFAULT_CAGE_ROWS)
        self.assertEqual(len(spec["cage"]["rest_points"]), 24)
        self.assertEqual(spec["target_instance"], "topwear_with_handwear__instance")
        self.assertEqual(spec["target_part"], "topwear_with_handwear")
        count = len(spec["binding"]["vertex_cells"])
        self.assertGreater(count, 0)
        self.assertEqual(len(spec["binding"]["vertex_uv"]), count)
        self.assertEqual(len(spec["binding"]["vertex_influence"]), count)
        for name in ("neutral", "bust_x_neg", "bust_x_pos", "bust_y_neg", "bust_y_pos"):
            self.assertEqual(len(spec["keyforms"][name]), 24)
        self.assertEqual(validate_chest_parametric_deformer(spec), [])

    def test_no_generic_center_lock_and_occluder_lock_is_explicit(self):
        occluder = np.zeros((300, 300), dtype=np.uint8)
        occluder[130:170, 100:150] = 255
        spec = build_chest_parametric_deformer(
            self.part, self.spec, frame_size=(300, 300), occluder_alpha=occluder)
        self.assertFalse(spec["locks"]["center_seam"])
        self.assertTrue(spec["locks"]["occluder_aware"])
        self.assertGreater(spec["binding"]["occluder_locked_vertex_count"], 0)

    def test_invalid_contract_is_rejected(self):
        errors = validate_chest_parametric_deformer({"version": 99})
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
