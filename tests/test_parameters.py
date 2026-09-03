"""Tests for parameters.py -- the standard parameter registry.

See PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1 #3, #18 (P0-A: contract
extraction). IDs are asserted verbatim since a host may already be wired to
the Iki-style naming convention (ParamAngleX, ParamEyeLOpen, ...) -- renaming
one silently would be a breaking change these tests are meant to catch.
"""

from __future__ import annotations

import unittest

from portrait_autorig import parameters as P


class StandardParameterIdsTests(unittest.TestCase):
    def test_ids_match_the_documented_iki_style_convention(self):
        self.assertEqual(P.PARAM_ANGLE_X, "ParamAngleX")
        self.assertEqual(P.PARAM_ANGLE_Y, "ParamAngleY")
        self.assertEqual(P.PARAM_ANGLE_Z, "ParamAngleZ")
        self.assertEqual(P.PARAM_EYE_L_OPEN, "ParamEyeLOpen")
        self.assertEqual(P.PARAM_EYE_R_OPEN, "ParamEyeROpen")
        self.assertEqual(P.PARAM_EYEBALL_X, "ParamEyeBallX")
        self.assertEqual(P.PARAM_EYEBALL_Y, "ParamEyeBallY")
        self.assertEqual(P.PARAM_MOUTH_OPEN, "ParamMouthOpenY")
        self.assertEqual(P.PARAM_MOUTH_FORM, "ParamMouthForm")
        self.assertEqual(P.PARAM_BREATH, "ParamBreath")


class StandardParameterRegistryTests(unittest.TestCase):
    def test_registry_has_one_entry_per_standard_parameter_in_order(self):
        registry = P.standard_parameter_registry()
        self.assertEqual([entry["id"] for entry in registry],
                         [row[0] for row in P.STANDARD_PARAMETERS])

    def test_each_entry_has_min_max_default(self):
        for entry in P.standard_parameter_registry():
            self.assertEqual(set(entry), {"id", "min", "max", "default"})
            self.assertLessEqual(entry["min"], entry["default"])
            self.assertLessEqual(entry["default"], entry["max"])

    def test_eye_open_and_breath_defaults_match_todays_rest_pose(self):
        # Rest pose invariance (both directives' hard invariant): eyes open,
        # angles/breath centered, mouth closed at every parameter's default.
        by_id = {entry["id"]: entry for entry in P.standard_parameter_registry()}
        self.assertEqual(by_id[P.PARAM_EYE_L_OPEN]["default"], 1.0)
        self.assertEqual(by_id[P.PARAM_EYE_R_OPEN]["default"], 1.0)
        self.assertEqual(by_id[P.PARAM_ANGLE_X]["default"], 0.0)
        self.assertEqual(by_id[P.PARAM_BREATH]["default"], 0.0)
        self.assertEqual(by_id[P.PARAM_MOUTH_OPEN]["default"], 0.0)

    def test_parameter_descriptor_shape(self):
        self.assertEqual(P.parameter_descriptor("ParamFoo", -1.0, 1.0, 0.0),
                         {"id": "ParamFoo", "min": -1.0, "max": 1.0, "default": 0.0})


if __name__ == "__main__":
    unittest.main()
