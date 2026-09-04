from __future__ import annotations

import unittest

import numpy as np

from portrait_autorig.constraints import boundary_stitch_spec, clip_mask_spec
from portrait_autorig.rig import build_rig


class ConstraintContractTests(unittest.TestCase):
    def test_clip_mask_preserves_explicit_source_and_targets(self):
        spec = clip_mask_spec("eyewhite_l", ["iris_l", "pupil_l", "highlight_l"])
        self.assertEqual(spec["kind"], "clip_mask")
        self.assertEqual(spec["source"], "eyewhite_l")
        self.assertEqual(spec["targets"], ["iris_l", "pupil_l", "highlight_l"])

    def test_clip_mask_rejects_empty_or_self_target(self):
        with self.assertRaises(ValueError):
            clip_mask_spec("eye", [])
        with self.assertRaises(ValueError):
            clip_mask_spec("eye", ["eye"])

    def test_boundary_stitch_supports_n_way_and_normalizes_weights(self):
        spec = boundary_stitch_spec([{
            "id": "neck_top",
            "members": [
                {"part": "head", "vertex": 2, "weight": 2},
                {"part": "neck", "vertex": 4, "weight": 1},
                {"part": "topwear", "vertex": 7, "weight": 1},
            ],
        }])
        members = spec["groups"][0]["members"]
        self.assertEqual(len(members), 3)
        self.assertAlmostEqual(sum(item["weight"] for item in members), 1.0, places=6)

    def test_boundary_stitch_rejects_single_member(self):
        with self.assertRaises(ValueError):
            boundary_stitch_spec([{"members": [{"part": "head", "vertex": 1}]}])

    def test_build_rig_forwards_constraint_contracts(self):
        head = np.zeros((16, 16, 4), dtype=np.uint8)
        head[2:12, 3:13, 3] = 255
        manifest, _ = build_rig(
            {"head": head}, frame_size=(16, 16),
            clip_masks=[{"source": "eyewhite_l", "targets": ["iris_l"]}],
            boundary_stitches=[{"members": [
                {"part": "head", "vertex": 0},
                {"part": "neck", "vertex": 1},
            ]}],
        )
        self.assertEqual([item["kind"] for item in manifest["constraints"]],
                         ["clip_mask", "boundary_stitch"])
