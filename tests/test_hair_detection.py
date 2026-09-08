from __future__ import annotations

import unittest

import numpy as np

from portrait_autorig.face_motion import build_jaw_open_spec
from portrait_autorig.hair_detection import detect_hair_zones


def _layer(width=96, height=96):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    return image


class HairDetectionTests(unittest.TestCase):
    def test_supported_semantics_generate_stable_zones_and_geodesic_tips(self):
        image = _layer()
        image[8:82, 24:34, 3] = 255
        image[30:52, 58:82, 3] = 255
        report = detect_hair_zones({"front hair": image}, frame_size=(96, 96))
        self.assertEqual(report["status"], "READY")
        zones = report["zones"]["front hair"]
        self.assertEqual(len(zones), 2)
        self.assertEqual([zone["zone_id"] for zone in zones],
                         ["front_hair.zone_0", "front_hair.zone_1"])
        self.assertIn(zones[0]["class"], {"SHORT_SWAY", "LONG_STRAND", "MASS_SWAY"})
        self.assertGreater(zones[0]["effective_length_px"], 0)
        self.assertNotEqual(zones[0]["root"]["position"], zones[0]["tip"]["position"])

    def test_unsupported_semantics_do_not_create_side_hair_contract(self):
        image = _layer()
        image[10:30, 10:30, 3] = 255
        report = detect_hair_zones({"side hair": image}, frame_size=(96, 96))
        self.assertEqual(report["status"], "DISABLED")
        self.assertEqual(report["zones"], {})


class JawOpenSpecTests(unittest.TestCase):
    def test_jaw_spec_is_geometry_derived_and_neutral_is_zero_by_contract(self):
        parts = [
            {"tag": "face", "xyxy": [10, 5, 86, 86]},
            {"tag": "mouth", "xyxy": [38, 48, 58, 58]},
        ]
        spec = build_jaw_open_spec(parts)
        self.assertEqual(spec["target_tag"], "face")
        self.assertEqual(spec["mouth_box"], [38.0, 48.0, 58.0, 58.0])
        self.assertEqual(spec["influence"]["end_y"], 86.0)
        self.assertGreater(spec["max_drop_ratio"], 0)
        self.assertIsNone(build_jaw_open_spec([{"tag": "face", "xyxy": [0, 0, 10, 10]}]))


if __name__ == "__main__":
    unittest.main()
