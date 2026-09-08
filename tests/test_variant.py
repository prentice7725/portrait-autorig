"""P0-F2 Composer VariantSet runtime binding contract."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import numpy as np

from portrait_autorig.capability import DEGRADED, DISABLED, READY
from portrait_autorig.image import composite_layers
from portrait_autorig.rig import RIG_Z_ORDER, build_rig
from portrait_autorig.compiler import compile_assembly_bundle
from portrait_autorig.assembly import load_assembly_bundle
from portrait_autorig.project import load_rig_project
from tests.test_assembly import AssemblyBundleBuilder


CANVAS = 64


def solid(box, value, alpha=255):
    out = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
    x1, y1, x2, y2 = box
    out[y1:y2, x1:x2, :3] = value
    out[y1:y2, x1:x2, 3] = alpha
    return out


def base_layers():
    return {
        "head": solid((18, 4, 46, 34), 180),
        "face": solid((21, 10, 43, 30), 190),
        "neck": solid((27, 30, 37, 43), 180),
        "topwear": solid((10, 42, 54, 63), 80),
    }


class VariantBindingTests(unittest.TestCase):
    def test_authored_torso_region_auto_wires_p2_3_physics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A002.assembly"
            b = AssemblyBundleBuilder(root)
            b.add_instance("head_i", semantic="head", box=(12, 2, 28, 20))
            b.add_instance("face_i", semantic="face", box=(14, 6, 26, 18))
            b.add_instance("neck_i", semantic="neck", box=(18, 18, 22, 28))
            b.add_instance("topwear_i", semantic="topwear", box=(8, 28, 32, 39))
            b.rig_intent["regions"]["upper_torso_secondary"] = {
                "target": "topwear_with_handwear", "enabled": True,
                "author_strength": 0.9, "response_profile": "springy",
                "geometry": {
                    "left": {"center": [0.32, 0.5], "radius": [0.22, 0.2]},
                    "right": {"center": [0.68, 0.5], "radius": [0.22, 0.2]},
                }, "locks": {"center": 0.1, "neckline": 0.16},
            }
            b.write()
            manifest_path = compile_assembly_bundle(str(root), str(Path(tmp) / "A002.rig"))
            manifest = __import__("json").loads(Path(manifest_path).read_text(encoding="utf-8"))
        driver = manifest["physics"]["upper_torso_driver"]
        self.assertEqual(driver["model"], "inertial_relative_v2")
        self.assertEqual(driver["profile"], "springy")
        self.assertEqual(manifest["physics"]["config"]["update_hz"], 60)

    def test_assembly_without_motion_hint_emits_rig_studio_chest_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A002.assembly"
            b = AssemblyBundleBuilder(root, canvas=(128, 128))
            b.add_instance("head_i", semantic="head", box=(20, 4, 108, 60))
            b.add_instance("face_i", semantic="face", box=(32, 16, 96, 56))
            b.add_instance("neck_i", semantic="neck", box=(48, 56, 80, 82))
            b.add_instance("topwear_i", semantic="topwear", box=(8, 76, 120, 128))
            b.write()
            out = Path(tmp) / "A002.rigproject"
            manifest_path = compile_assembly_bundle(str(root), str(out))
            manifest = __import__("json").loads(Path(manifest_path).read_text(encoding="utf-8"))

            self.assertEqual(manifest["motion"]["upper_torso_soft_morph"]["source"],
                             "topwear_geometry")
            self.assertIn("upper_torso_parametric_deformer", manifest["motion"])
            self.assertNotIn("physics", manifest)

            project = load_rig_project(out)
            project.set_chest_physics({"profile": "springy"})
            project.save()
            reloaded = load_rig_project(out)

        self.assertEqual(
            reloaded.resolved_manifest["physics"]["upper_torso_driver"]["profile"],
            "springy",
        )

    def test_assembly_compile_keeps_all_variant_images_and_reference_fidelity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            b = AssemblyBundleBuilder(root)
            b.add_instance("head_i", semantic="head", box=(12, 2, 28, 20))
            b.add_instance("face_i", semantic="face", box=(14, 6, 26, 18))
            b.add_instance("mouth_neutral_i", semantic="mouth", box=(18, 14, 22, 16))
            b.add_instance("mouth_open_i", semantic="mouth", box=(17, 13, 23, 17), visible=False)
            b.add_instance("neck_i", semantic="neck", box=(18, 18, 22, 28))
            b.add_instance("topwear_i", semantic="topwear", box=(8, 28, 32, 39))
            b.variant_sets = {"mouth": {"mode": "exclusive", "default": "mouth_neutral_i",
                                          "active": "mouth_neutral_i",
                                          "members": ["mouth_neutral_i", "mouth_open_i"]}}
            b.write()
            out = Path(tmp) / "A001.rig"
            manifest_path = compile_assembly_bundle(str(root), str(out))
            self.assertEqual(load_assembly_bundle(root).reference.shape, (40, 40, 4))
            manifest = __import__("json").loads(Path(manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")
        self.assertEqual(len([p for p in manifest["parts"] if "variant_member" in p]), 2)

    def test_assembly_reference_uses_source_visibility_not_variant_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            b = AssemblyBundleBuilder(root)
            b.add_instance("head_i", semantic="head", box=(4, 2, 36, 30), rgba=(80, 80, 80))
            b.add_instance("face_i", semantic="face", box=(8, 6, 32, 26), rgba=(150, 110, 90))
            b.add_instance("neck_i", semantic="neck", box=(14, 26, 26, 34), rgba=(120, 90, 75))
            b.add_instance("topwear_i", semantic="topwear", box=(2, 32, 38, 40), rgba=(60, 70, 90))
            b.add_instance("mouth_open_i", semantic="mouth", box=(14, 18, 26, 24),
                            visible=True, rgba=(220, 40, 40))
            b.add_instance("mouth_closed_i", semantic="mouth", box=(14, 18, 26, 24),
                            visible=False, rgba=(40, 40, 220))
            b.variant_sets = {
                "mouth_state": {
                    "mode": "exclusive", "default": "mouth_open_i",
                    "active": "mouth_closed_i",
                    "members": ["mouth_open_i", "mouth_closed_i"],
                }
            }
            b.write()
            manifest_path = compile_assembly_bundle(str(root), str(Path(tmp) / "A001.rig"))
            manifest = __import__("json").loads(Path(manifest_path).read_text(encoding="utf-8"))

        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")
        self.assertEqual(manifest["variant_sets"]["mouth_state"]["active"], "mouth_closed_i")
        visible = {p["variant_member"]: p["visible"]
                   for p in manifest["parts"] if "variant_member" in p}
        self.assertEqual(visible, {"mouth_open_i": True, "mouth_closed_i": False})

    def test_expression_state_suffixes_stay_on_the_head_motion_plane(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            b = AssemblyBundleBuilder(root)
            b.add_instance("head_i", semantic="head", box=(4, 2, 36, 30))
            b.add_instance("face_i", semantic="face", box=(8, 6, 32, 26))
            b.add_instance("eyewhite_i", semantic="eyewhite", box=(12, 12, 20, 16))
            b.add_instance("eyes_closed_i", semantic="eyes_closed", box=(12, 12, 20, 16),
                           visible=False)
            b.add_instance("mouth_i", semantic="mouth", box=(14, 18, 26, 22))
            b.add_instance("mouth_a_i", semantic="mouth_a", box=(14, 18, 26, 22),
                           visible=False)
            b.add_instance("neck_i", semantic="neck", box=(14, 26, 26, 34))
            b.variant_sets = {
                "eyes_state": {
                    "mode": "exclusive", "default": "eyewhite_i",
                    "active": "eyewhite_i",
                    "members": ["eyewhite_i", "eyes_closed_i"],
                },
                "mouth_state": {
                    "mode": "exclusive", "default": "mouth_i",
                    "active": "mouth_i",
                    "members": ["mouth_i", "mouth_a_i"],
                },
            }
            b.write()
            manifest_path = compile_assembly_bundle(str(root), str(Path(tmp) / "A001.rig"))
            manifest = __import__("json").loads(Path(manifest_path).read_text(encoding="utf-8"))

        donors = {p["tag"]: p for p in manifest["parts"] if "variant_member" in p}
        self.assertEqual(donors["eyes_closed"]["group"], "head")
        self.assertEqual(donors["eyes_closed"]["weight"], {"mode": "constant", "value": 1.0})
        self.assertEqual(donors["mouth_a"]["group"], "head")
        self.assertEqual(donors["mouth_a"]["weight"], {"mode": "constant", "value": 1.0})

    def test_compiles_explicit_instance_to_part_mapping_and_default(self):
        layers = base_layers()
        variants = {
            "mouth_viseme": {
                "mode": "exclusive", "default": "mouth_neutral__instance",
                "active": "mouth_a__instance",
                "members": ["mouth_neutral__instance", "mouth_a__instance"],
            }
        }
        variant_layers = {
            "mouth_neutral__instance": solid((27, 25, 37, 28), 30),
            "mouth_a__instance": solid((26, 24, 38, 30), 10),
        }
        ref_layers = dict(layers)
        ref_layers["mouth"] = variant_layers["mouth_a__instance"]
        reference = composite_layers(ref_layers, (CANVAS, CANVAS), order=RIG_Z_ORDER)
        manifest, images = build_rig(
            layers, frame_size=(CANVAS, CANVAS), rest_reference=reference,
            draw_order=["head", "face", "mouth", "neck", "topwear"],
            variant_sets=variants, variant_layers=variant_layers,
            instance_to_tag={k: "mouth" for k in variant_layers},
        )
        spec = manifest["variant_sets"]["mouth_viseme"]
        self.assertEqual(spec["default"], "mouth_neutral__instance")
        self.assertEqual(spec["active"], "mouth_a__instance")
        self.assertEqual(spec["member_bindings"]["mouth_a__instance"]["tag"], "mouth")
        self.assertEqual(spec["member_bindings"]["mouth_a__instance"]["part"], "variant_mouth_a__instance")
        self.assertEqual(manifest["capabilities"]["expression_variants"], READY)
        self.assertTrue(any(w["code"] == "variant_active_differs_from_default"
                            for w in manifest["variant_bindings"]["warnings"]))
        deformer = next(d for d in manifest["deformers"] if d["id"] == "variant_mouth_viseme")
        self.assertEqual(deformer["phase"], "visibility")
        self.assertEqual(deformer["config"]["mode"], "discrete")
        visible = {p["variant_member"]: p["visible"] for p in manifest["parts"] if "variant_member" in p}
        self.assertEqual(visible, {"mouth_neutral__instance": True, "mouth_a__instance": False})
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")
        self.assertIn("variant_mouth_a__instance", images)

    def test_expression_preset_validates_and_exports_atomic_selection_table(self):
        layers = base_layers()
        members = {"a": solid((26, 24, 38, 28), 20), "b": solid((26, 24, 38, 29), 40)}
        variants = {"mouth": {"mode": "exclusive", "default": "a", "active": "a", "members": ["a", "b"]}}
        ref = composite_layers({**layers, "mouth": members["a"]}, (CANVAS, CANVAS), order=RIG_Z_ORDER)
        manifest, _ = build_rig(
            layers, frame_size=(CANVAS, CANVAS), rest_reference=ref,
            variant_sets=variants, expression_presets={"annoyed": {"variants": {"mouth": "b"}}},
            variant_layers=members, instance_to_tag={"a": "mouth", "b": "mouth"},
        )
        self.assertEqual(manifest["expression_presets"]["annoyed"]["variants"], {"mouth": "b"})

    def test_no_variant_set_is_disabled_capability(self):
        manifest, _ = build_rig(base_layers(), frame_size=(CANVAS, CANVAS))
        self.assertEqual(manifest["capabilities"]["expression_variants"], DISABLED)

    def test_unsupported_transition_is_degraded_and_normalized(self):
        layers = base_layers()
        variants = {"mouth": {"mode": "exclusive", "default": "a", "members": ["a"],
                               "transition": "morph"}}
        ref = composite_layers({**layers, "mouth": solid((27, 25, 37, 28), 20)},
                               (CANVAS, CANVAS), order=RIG_Z_ORDER)
        manifest, _ = build_rig(
            layers, frame_size=(CANVAS, CANVAS), rest_reference=ref,
            variant_sets=variants, variant_layers={"a": solid((27, 25, 37, 28), 20)},
            instance_to_tag={"a": "mouth"},
        )
        self.assertEqual(manifest["capabilities"]["expression_variants"], DEGRADED)
        self.assertEqual(manifest["variant_sets"]["mouth"]["transition"], "discrete")

    def test_invalid_member_mapping_is_hard_rejected(self):
        with self.assertRaises(ValueError):
            build_rig(
                base_layers(), frame_size=(CANVAS, CANVAS),
                variant_sets={"mouth": {"members": ["missing"], "default": "missing"}},
                variant_layers={}, instance_to_tag={},
            )


if __name__ == "__main__":
    unittest.main()
