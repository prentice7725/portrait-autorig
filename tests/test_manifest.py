"""Tests for manifest.py -- Rig Manifest version constants and the v0.1 ->
v0.2 upgrade path.

See PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1 #4, #7, #18 (P0-B:
manifest v0.2 plus a v0.1 compatibility adapter -- additive, no geometry
re-derivation).
"""

from __future__ import annotations

import unittest

from portrait_autorig import manifest, rig
from portrait_autorig.parameters import (
    PARAM_ANGLE_X, PARAM_ANGLE_Y, PARAM_ANGLE_Z,
    PARAM_BREATH, PARAM_EYE_L_OPEN, PARAM_EYE_R_OPEN,
    STANDARD_PARAMETERS,
)


class VersionConstantTests(unittest.TestCase):
    def test_version_constants(self):
        self.assertEqual(manifest.RIG_MANIFEST_VERSION_01, "0.1")
        self.assertEqual(manifest.RIG_MANIFEST_VERSION_02, "0.2")

    def test_current_output_version_is_v02(self):
        self.assertEqual(manifest.RIG_MANIFEST_VERSION, manifest.RIG_MANIFEST_VERSION_02)

    def test_rig_module_still_constructs_its_own_v01_base_shape(self):
        # rig.py's Stage A-D construction is untouched (absorption plan
        # "결과를 바꾸지 않고 구조부터 바꾼다") -- it is manifest.py's upgrade
        # step, applied once at the end of build_rig, that bumps this to 0.2.
        self.assertEqual(rig.MANIFEST_VERSION, manifest.RIG_MANIFEST_VERSION_01)


def _v01_manifest(**motion_overrides):
    motion = {
        "head_turn": {"max_x": 0.8, "max_y": 0.8},
        "head_tilt": {"max_deg": 2.0, "pivot": "neck_pivot"},
        "breathing": {"period_s": 4.0, "amplitude_px": 3.0},
        "blink": {"close_s": 0.08, "hold_s": 0.34, "open_s": 0.16,
                 "interval_s": [1.6, 5.4], "lid_ratio": 0.85, "lid_thickness": 0.18},
    }
    motion.update(motion_overrides)
    return {
        "version": "0.1",
        "canvas": {"width": 128, "height": 128},
        "anchors": {"face_center": [64.0, 64.0]},
        "parts": [{"name": "face", "tag": "face"}],
        "motion": motion,
        "rig_preflight": {"status": "READY"},
        "rest_fidelity": {"status": "pass"},
    }


class UpgradeManifestTests(unittest.TestCase):
    def test_upgrade_bumps_version_and_adds_v02_blocks(self):
        upgraded = manifest.upgrade_manifest_v01_to_v02(_v01_manifest())
        self.assertEqual(upgraded["version"], "0.2")
        self.assertIn("parameters", upgraded)
        self.assertIn("deformers", upgraded)
        self.assertIn("drivers", upgraded)

    def test_upgrade_preserves_every_v01_field_verbatim(self):
        source = _v01_manifest()
        upgraded = manifest.upgrade_manifest_v01_to_v02(source)
        for key in ("canvas", "anchors", "parts", "motion", "rig_preflight", "rest_fidelity"):
            self.assertEqual(upgraded[key], source[key])

    def test_upgrade_does_not_mutate_the_input(self):
        source = _v01_manifest()
        manifest.upgrade_manifest_v01_to_v02(source)
        self.assertEqual(source["version"], "0.1")
        self.assertNotIn("parameters", source)

    def test_upgrade_is_idempotent_on_an_already_v02_manifest(self):
        once = manifest.upgrade_manifest_v01_to_v02(_v01_manifest())
        twice = manifest.upgrade_manifest_v01_to_v02(once)
        self.assertIs(twice, once)

    def test_parameters_block_is_the_standard_registry(self):
        upgraded = manifest.upgrade_manifest_v01_to_v02(_v01_manifest())
        self.assertEqual([p["id"] for p in upgraded["parameters"]],
                         [row[0] for row in STANDARD_PARAMETERS])


class DeformersFromMotionTests(unittest.TestCase):
    def test_head_turn_becomes_parallax_and_shell_deformers(self):
        deformers = manifest.deformers_from_motion({"head_turn": {"max_x": 0.8, "max_y": 0.8}})
        kinds = {d["kind"] for d in deformers}
        self.assertEqual(kinds, {"parallax_turn", "shell_turn"})
        for d in deformers:
            self.assertEqual(d["parameters"], [PARAM_ANGLE_X, PARAM_ANGLE_Y])
        shell = next(d for d in deformers if d["kind"] == "shell_turn")
        self.assertEqual(shell["targets"], {"group": "head"})
        parallax = next(d for d in deformers if d["kind"] == "parallax_turn")
        self.assertEqual(parallax["targets"], {"scope": "all"})
        self.assertEqual(parallax["config"], {"max_x": 0.8, "max_y": 0.8})

    def test_head_tilt_becomes_weighted_rotation_on_angle_z(self):
        deformers = manifest.deformers_from_motion(
            {"head_tilt": {"max_deg": 2.0, "pivot": "neck_pivot"}})
        self.assertEqual(len(deformers), 1)
        self.assertEqual(deformers[0]["kind"], "weighted_rotation")
        self.assertEqual(deformers[0]["parameters"], [PARAM_ANGLE_Z])

    def test_breathing_becomes_continuous_field_on_breath(self):
        deformers = manifest.deformers_from_motion(
            {"breathing": {"period_s": 4.0, "amplitude_px": 3.0}})
        self.assertEqual(len(deformers), 1)
        self.assertEqual(deformers[0]["kind"], "continuous_field")
        self.assertEqual(deformers[0]["parameters"], [PARAM_BREATH])

    def test_blink_becomes_one_eye_fold_deformer_per_side(self):
        deformers = manifest.deformers_from_motion({"blink": {"close_s": 0.08}})
        self.assertEqual(len(deformers), 2)
        by_target_side = {d["targets"]["side"]: d for d in deformers}
        self.assertEqual(by_target_side["l"]["parameters"], [PARAM_EYE_L_OPEN])
        self.assertEqual(by_target_side["r"]["parameters"], [PARAM_EYE_R_OPEN])
        for d in deformers:
            self.assertEqual(d["kind"], "eye_fold")

    def test_missing_motion_keys_yield_no_matching_deformer(self):
        self.assertEqual(manifest.deformers_from_motion({}), [])

    def test_every_synthesized_kind_is_in_the_known_vocabulary(self):
        motion = {
            "head_turn": {"max_x": 0.8, "max_y": 0.8},
            "head_tilt": {"max_deg": 2.0},
            "breathing": {"period_s": 4.0},
            "blink": {"close_s": 0.08},
        }
        for d in manifest.deformers_from_motion(motion):
            self.assertIn(d["kind"], manifest.DEFORMER_KINDS)

    def test_every_synthesized_deformer_carries_a_known_phase(self):
        motion = {
            "head_turn": {"max_x": 0.8, "max_y": 0.8},
            "head_tilt": {"max_deg": 2.0},
            "breathing": {"period_s": 4.0},
            "blink": {"close_s": 0.08},
        }
        for d in manifest.deformers_from_motion(motion):
            self.assertIn(d["phase"], manifest.EVALUATION_PHASES)


class EvaluationPhaseTests(unittest.TestCase):
    def test_phase_order_matches_the_directive_exactly(self):
        # directive v0.2 #13: base, primary, corrective, secondary,
        # constraints, visibility, render, in that fixed order.
        self.assertEqual(manifest.EVALUATION_PHASES,
                         ("base", "primary", "corrective", "secondary",
                          "constraints", "visibility", "render"))

    def test_evaluation_block_shape(self):
        self.assertEqual(manifest.evaluation_block(), {"phases": list(manifest.EVALUATION_PHASES)})

    def test_upgrade_adds_the_evaluation_block(self):
        upgraded = manifest.upgrade_manifest_v01_to_v02(_v01_manifest())
        self.assertEqual(upgraded["evaluation"], manifest.evaluation_block())

    def test_validate_deformer_phases_accepts_well_formed_deformers(self):
        deformers = manifest.deformers_from_motion({"breathing": {"period_s": 4.0}})
        self.assertEqual(manifest.validate_deformer_phases(deformers), [])

    def test_validate_deformer_phases_flags_a_missing_phase(self):
        errors = manifest.validate_deformer_phases([{"id": "x", "kind": "gaze"}])
        self.assertEqual(len(errors), 1)
        self.assertIn("x", errors[0])

    def test_validate_deformer_phases_flags_an_unknown_phase(self):
        errors = manifest.validate_deformer_phases(
            [{"id": "x", "kind": "gaze", "phase": "not_a_real_phase"}])
        self.assertEqual(len(errors), 1)
        self.assertIn("not_a_real_phase", errors[0])


def _authored_soft_morph_spec(**overrides):
    spec = {
        "enabled": True, "mode": "two_lobe", "strength": 0.85,
        "horizontal_px": 2.0, "vertical_px": 0.6,
        "center_lock": 0.10, "neckline_lock": 0.16,
        "confidence": 1.0, "source": "assembly_rig_intent", "status": "READY",
        "response_profile": "firm_bounce",
        "response_config": {"stiffness": 0.82, "damping": 0.36, "overshoot": 0.42, "max_displacement": 0.72},
        "left": {"center": [0.39, 0.36], "radius": [0.24, 0.20]},
        "right": {"center": [0.61, 0.36], "radius": [0.24, 0.20]},
    }
    spec.update(overrides)
    return spec


class UpperTorsoSecondaryEntriesTests(unittest.TestCase):
    def test_none_spec_produces_nothing(self):
        self.assertEqual(manifest.upper_torso_secondary_entries(None), (None, None))

    def test_disabled_spec_produces_nothing(self):
        spec = _authored_soft_morph_spec(enabled=False)
        self.assertEqual(manifest.upper_torso_secondary_entries(spec), (None, None))

    def test_legacy_auto_derived_spec_produces_nothing(self):
        # source == "topwear_geometry" (Portrait Bundle path) has no
        # response_profile to reserve a driver for.
        spec = _authored_soft_morph_spec(source="topwear_geometry")
        self.assertEqual(manifest.upper_torso_secondary_entries(spec), (None, None))

    def test_authored_enabled_spec_produces_a_local_soft_field_deformer(self):
        deformer, _ = manifest.upper_torso_secondary_entries(_authored_soft_morph_spec())
        self.assertIsNotNone(deformer)
        self.assertEqual(deformer["kind"], "local_soft_field")
        self.assertEqual(deformer["parameters"], ["ParamUpperTorsoSecondary"])
        self.assertEqual(deformer["targets"], {"tag": "topwear"})
        self.assertEqual(deformer["phase"], manifest.PHASE_SECONDARY)
        self.assertIn(deformer["kind"], manifest.DEFORMER_KINDS)

    def test_authored_enabled_spec_produces_an_upper_torso_secondary_driver(self):
        _, driver = manifest.upper_torso_secondary_entries(_authored_soft_morph_spec())
        self.assertIsNotNone(driver)
        self.assertEqual(driver["kind"], "UpperTorsoSecondaryDriver")
        self.assertEqual(driver["output"], "ParamUpperTorsoSecondary")
        self.assertEqual(driver["response_profile"], "firm_bounce")
        self.assertEqual(driver["response_config"]["max_displacement"], 0.72)
        self.assertEqual(driver["phase"], manifest.PHASE_SECONDARY)
        params = {i["parameter"] for i in driver["inputs"]}
        self.assertIn("ParamBreath", params)
        self.assertIn("ParamAngleY", params)

    def test_upgrade_wires_the_entries_into_deformers_and_drivers(self):
        v01 = _v01_manifest()
        v01["motion"]["upper_torso_soft_morph"] = _authored_soft_morph_spec()
        upgraded = manifest.upgrade_manifest_v01_to_v02(v01)
        kinds = {d["kind"] for d in upgraded["deformers"]}
        self.assertIn("local_soft_field", kinds)
        self.assertEqual(len(upgraded["drivers"]), 1)
        self.assertEqual(upgraded["drivers"][0]["kind"], "UpperTorsoSecondaryDriver")
        param_ids = {p["id"] for p in upgraded["parameters"]}
        self.assertIn("ParamUpperTorsoSecondary", param_ids)

    def test_upgrade_without_an_authored_region_leaves_drivers_empty(self):
        upgraded = manifest.upgrade_manifest_v01_to_v02(_v01_manifest())
        self.assertEqual(upgraded["drivers"], [])
        param_ids = {p["id"] for p in upgraded["parameters"]}
        self.assertNotIn("ParamUpperTorsoSecondary", param_ids)


if __name__ == "__main__":
    unittest.main()
