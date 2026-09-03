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
