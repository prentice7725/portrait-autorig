from __future__ import annotations

import math
import unittest

import numpy as np

from portrait_autorig.physics import (
    DeterministicSpring, PhysicsMaterial, StrandSpringDriver,
    UpperTorsoSecondaryDriver, validate_physics_spec,
)
from portrait_autorig.rig import build_rig
from portrait_autorig.manifest import physics_deformer_entries


class DeterministicPhysicsTests(unittest.TestCase):
    def test_fixed_steps_are_reproducible(self):
        kwargs = {"rest": 0.0, "material": PhysicsMaterial(stiffness=20, damping=5)}
        a = DeterministicSpring(**kwargs)
        b = DeterministicSpring(**kwargs)
        a.stepPhysicsFixed(30, target=1.0)
        b.stepPhysicsFixed(30, target=1.0)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_reset_and_warmup_restore_a_known_state(self):
        spring = DeterministicSpring(rest=2.0)
        spring.stepPhysicsFixed(10, target=5.0)
        spring.resetPhysics()
        self.assertEqual(spring.value, 2.0)
        self.assertEqual(spring.velocity, 0.0)
        warmed = spring.warmupPhysics(0.25, target=5.0)
        self.assertTrue(math.isfinite(warmed.value))
        self.assertNotEqual(warmed.value, 2.0)

    def test_non_finite_state_rolls_back_and_degrades(self):
        spring = DeterministicSpring(material=PhysicsMaterial(stiffness=1e308, damping=0))
        before = spring.snapshot()
        result = spring.stepPhysicsFixed(1, target=1e308)
        self.assertTrue(result.degraded)
        self.assertEqual(result.diagnostic, "non_finite_rollback")
        self.assertEqual((result.value, result.velocity), (before.value, before.velocity))

    def test_invalid_material_is_rejected(self):
        with self.assertRaises(ValueError):
            PhysicsMaterial(mass=0)

    def test_strand_driver_is_id_stable_and_exposes_all_outputs(self):
        strands = [{"strand_id": "left", "length": 2}, {"strand_id": "right", "length": 4}]
        a = StrandSpringDriver(strands)
        b = StrandSpringDriver(strands)
        out_a = a.stepPhysicsFixed(10, target=1.0)
        out_b = b.stepPhysicsFixed(10, target=1.0)
        self.assertEqual(out_a, out_b)
        self.assertEqual(set(out_a), {"left", "right"})
        self.assertNotEqual(out_a["left"].value, out_a["right"].value)

    def test_torso_driver_profiles_are_explicit(self):
        driver = UpperTorsoSecondaryDriver(profile="firm_bounce")
        driver.resetPhysics()
        result = driver.stepPhysicsFixed(5, breath=1.0, angle_y=0.2)
        self.assertTrue(math.isfinite(result.value))
        with self.assertRaises(ValueError):
            UpperTorsoSecondaryDriver(profile="unknown")

    def test_physics_block_is_opt_in_and_preserved_in_manifest(self):
        head = np.zeros((12, 12, 4), dtype=np.uint8)
        head[2:10, 2:10, 3] = 255
        spec = {"config": {"update_hz": 60},
                "strand_driver": {"enabled": True, "strands": [{"strand_id": "s"}]}}
        manifest, _ = build_rig({"head": head}, frame_size=(12, 12), physics=spec)
        self.assertEqual(manifest["physics"], spec)
        self.assertEqual([item["kind"] for item in manifest["deformers"] if item["phase"] == "secondary"][-1:],
                         ["strand_spring"])

    def test_physics_deformer_entries_are_opt_in(self):
        entries = physics_deformer_entries({
            "strand_driver": {"strands": [{"strand_id": "s"}]},
            "upper_torso_driver": {"profile": "soft"},
        })
        self.assertEqual([entry["kind"] for entry in entries], ["strand_spring"])

    def test_zero_physics_keeps_the_exact_rest_reference(self):
        head = np.zeros((12, 12, 4), dtype=np.uint8)
        head[2:10, 2:10, :3] = [120, 90, 80]
        head[2:10, 2:10, 3] = 255
        manifest, _ = build_rig(
            {"head": head}, frame_size=(12, 12),
            physics={"upper_torso_driver": {"enabled": True, "profile": "soft"}},
        )
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")
        self.assertNotIn("upper_torso_physics",
                         [entry["kind"] for entry in manifest["deformers"]])

    def test_invalid_manifest_physics_is_rejected_before_runtime(self):
        errors = validate_physics_spec({
            "config": {"update_hz": 0},
            "strand_driver": {"strands": [{"strand_id": "s"}, {"strand_id": "s"}]},
            "upper_torso_driver": {"profile": "nope"},
        })
        self.assertEqual(len(errors), 3)

    def test_driver_input_modes_are_explicit(self):
        for mode in ("translation", "angle", "velocity", "acceleration", "impulse"):
            driver = UpperTorsoSecondaryDriver(input_mode=mode)
            driver.resetPhysics()
            result = driver.stepPhysicsFixed(1, breath=1.0, angle_y=0.0)
            self.assertTrue(math.isfinite(result.value))
        with self.assertRaises(ValueError):
            UpperTorsoSecondaryDriver(input_mode="angular_velocity")

    def test_torso_driver_keeps_independent_lobe_springs_and_turn_coupling(self):
        driver = UpperTorsoSecondaryDriver(turn_asymmetry=0.2)
        driver.resetPhysics()
        driver.stepPhysicsFixed(8, breath=1.0, angle_y=0.5)
        left = driver.springs["left"].snapshot()
        right = driver.springs["right"].snapshot()
        self.assertNotEqual(left.value, right.value)
        self.assertAlmostEqual(driver.snapshot()["value"], (left.value + right.value) * 0.5)
        with self.assertRaises(ValueError):
            UpperTorsoSecondaryDriver(turn_asymmetry=1.1)

    def test_turn_asymmetry_is_manifest_validated(self):
        errors = validate_physics_spec({
            "upper_torso_driver": {"profile": "soft", "turn_asymmetry": 2},
        })
        self.assertEqual(errors, ["upper_torso_driver.turn_asymmetry must be finite and in [0, 1]"])

    def test_manifest_validates_driver_input_modes(self):
        errors = validate_physics_spec({
            "strand_driver": {"input_mode": "angular_velocity"},
            "upper_torso_driver": {"input_mode": "angular_velocity"},
        })
        self.assertEqual(errors, [
            "unsupported strand_driver.input_mode: 'angular_velocity'",
            "unsupported upper_torso_driver.input_mode: 'angular_velocity'",
        ])

    def test_torso_body_velocity_coupling_is_optional_and_small(self):
        coupled = UpperTorsoSecondaryDriver(velocity_gain=1.0, acceleration_gain=0.0)
        baseline = UpperTorsoSecondaryDriver(velocity_gain=0.0, acceleration_gain=0.0)
        coupled.stepPhysicsFixed(1, body_velocity=1.0)
        baseline.stepPhysicsFixed(1, body_velocity=1.0)
        self.assertGreater(coupled.snapshot()["value"], baseline.snapshot()["value"])

    def test_inertial_model_separates_equilibrium_and_external_force(self):
        kick = UpperTorsoSecondaryDriver(model="inertial_relative_v1", breath_gain=0,
                                         pose_bias_gain=0, inertia_gain_y=1, velocity_drag_y=0)
        kick.stepPhysicsFixed(1, body_acceleration=(0, 1))
        self.assertNotEqual(kick.snapshot()["value"], 0.0)
        breath = UpperTorsoSecondaryDriver(model="inertial_relative_v1", breath_gain=1,
                                           inertia_gain_y=0, velocity_drag_y=0)
        breath.stepPhysicsFixed(1, breath=1)
        self.assertGreater(breath.snapshot()["value"], 0.0)

    def test_inertial_model_supports_independent_material_scales(self):
        driver = UpperTorsoSecondaryDriver(model="inertial_relative_v1",
            left_material_scale={"mass": 1.04}, right_material_scale={"mass": 0.96})
        driver.stepPhysicsFixed(4, body_acceleration=(0, 1))
        self.assertNotEqual(driver.springs["left"].snapshot().value,
                            driver.springs["right"].snapshot().value)

    def test_inertial_model_has_deterministic_default_lobe_material_difference(self):
        driver = UpperTorsoSecondaryDriver(model="inertial_relative_v1",
                                           breath_gain=0, pose_bias_gain=0,
                                           inertia_gain_y=1, velocity_drag_y=0)
        driver.stepPhysicsFixed(4, body_acceleration=(0, 1))
        self.assertNotEqual(driver.springs["left"].snapshot().value,
                            driver.springs["right"].snapshot().value)

    def test_model_defaults_preserve_legacy_and_new_compile_declares_v2(self):
        self.assertEqual(UpperTorsoSecondaryDriver().model, "legacy_target_v1")
        head = np.zeros((12, 12, 4), dtype=np.uint8)
        head[2:10, 2:10, 3] = 255
        manifest, _ = build_rig({"head": head}, frame_size=(12, 12),
                                physics={"upper_torso_driver": {"profile": "soft"}})
        self.assertEqual(manifest["physics"]["upper_torso_driver"]["model"],
                         "inertial_relative_v2")

    def test_v2_state_and_breath_use_pixel_units(self):
        driver = UpperTorsoSecondaryDriver(model="inertial_relative_v2",
                                           breath_displacement_px=1.0,
                                           natural_frequency_hz=2.0,
                                           damping_ratio=0.7)
        driver.warmupPhysics(1.0, breath=1.0)
        self.assertAlmostEqual(driver.snapshot()["value"], 1.0, delta=0.08)

    def test_v2_direct_qa_displacement_is_pixels(self):
        driver = UpperTorsoSecondaryDriver(model="inertial_relative_v2")
        snapshot = driver.setRelativeDisplacement(4.0)
        self.assertAlmostEqual(snapshot["left"].value, 4.0)
        self.assertAlmostEqual(snapshot["right"].value, 4.0)

    def test_v2_acceleration_is_external_and_legacy_is_unchanged(self):
        driver = UpperTorsoSecondaryDriver(model="inertial_relative_v2",
                                           breath_displacement_px=0,
                                           pose_bias_px=0, inertia_coupling_y=0.22)
        driver.stepPhysicsFixed(1, body_acceleration=(0, 10))
        self.assertLess(driver.snapshot()["value"], 0)
        self.assertEqual(UpperTorsoSecondaryDriver().model, "legacy_target_v1")

    def test_v2_clamps_displacement_in_pixel_units_and_keeps_lobes_independent(self):
        driver = UpperTorsoSecondaryDriver(model="inertial_relative_v2",
                                           max_displacement_px=2.0,
                                           left_material_scale={"frequency": 0.98},
                                           right_material_scale={"frequency": 1.02})
        snapshot = driver.setRelativeDisplacement(8.0)
        self.assertEqual(snapshot["left"].value, 2.0)
        driver.stepPhysicsFixed(12, body_acceleration=(0, 40))
        self.assertNotEqual(driver.springs["left"].snapshot().value,
                            driver.springs["right"].snapshot().value)
