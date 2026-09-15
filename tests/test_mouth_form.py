import unittest

from portrait_autorig.face_motion import build_mouth_form_spec
from portrait_autorig.manifest import deformers_from_motion


class MouthFormSpecTests(unittest.TestCase):
    def setUp(self):
        self.parts = [
            {"tag": "face", "xyxy": [10, 10, 110, 130]},
            {"tag": "mouth", "xyxy": [40, 70, 80, 80]},
        ]

    def test_spec_is_geometry_derived_and_has_independent_endpoints(self):
        spec = build_mouth_form_spec(self.parts)
        self.assertIsNotNone(spec)
        self.assertEqual(spec["version"], 1)
        self.assertEqual(spec["target_tags"], ["mouth", "mouth_open", "mouth_closed", "face"])
        self.assertEqual(spec["mouth_box"], [40.0, 70.0, 80.0, 80.0])
        self.assertEqual(spec["control_points"]["left_corner"], [40.0, 75.0])
        self.assertEqual(spec["control_points"]["center"], [60.0, 75.0])
        self.assertEqual(spec["control_points"]["right_corner"], [80.0, 75.0])
        self.assertNotEqual(spec["keyforms"]["-1"], spec["keyforms"]["+1"])

    def test_missing_face_or_mouth_disables_layer_free_deformer(self):
        self.assertIsNone(build_mouth_form_spec([self.parts[0]]))
        self.assertIsNone(build_mouth_form_spec([self.parts[1]]))

    def test_manifest_places_mouth_form_before_jaw_open(self):
        spec = build_mouth_form_spec(self.parts)
        entries = deformers_from_motion({
            "mouth_form": spec,
            "jaw_open": {"enabled": True, "target_tag": "face"},
        })
        self.assertEqual([entry["kind"] for entry in entries], ["mouth_form", "jaw_open"])
        self.assertEqual(entries[0]["parameters"], ["ParamMouthForm"])
        self.assertEqual(entries[0]["phase"], "corrective")


if __name__ == "__main__":
    unittest.main()
