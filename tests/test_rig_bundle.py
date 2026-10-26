"""Structural contract tests; the synthetic pixels are not a source-quality fixture."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from portrait_autorig.project import load_rig_project
from portrait_autorig.rig_bundle import load_rig_bundle
from portrait_autorig.workflow import bundle_kind, compile_bundle_input


CANVAS = (64, 64)


def _image(path: Path, box, color):
    image = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    pixels = np.asarray(image).copy()
    x1, y1, x2, y2 = box
    pixels[y1:y2, x1:x2] = color
    Image.fromarray(pixels, mode="RGBA").save(path)


def _write_rig_bundle(root: Path):
    (root / "layers").mkdir(parents=True)
    (root / "variants").mkdir()
    (root / "provenance").mkdir()
    items = [
        ("head_i", "head", (18, 3, 46, 31), (170, 130, 100, 255), True),
        ("face_i", "face", (22, 9, 42, 28), (210, 170, 135, 255), True),
        ("neck_i", "neck", (27, 28, 37, 39), (150, 115, 90, 255), True),
        ("topwear_i", "topwear", (12, 34, 52, 50), (60, 80, 130, 255), True),
        ("bottomwear_i", "bottomwear", (19, 49, 45, 64), (70, 65, 90, 255), True),
        ("left_arm_i", "left_arm", (7, 36, 15, 50), (150, 115, 90, 255), True),
        ("right_arm_i", "right_arm", (49, 36, 57, 50), (150, 115, 90, 255), True),
        ("eyes_open_i", "eyes", (25, 15, 39, 18), (15, 15, 20, 255), True),
        ("eyes_closed_i", "eyes", (25, 17, 39, 19), (30, 30, 35, 255), False),
        ("mouth_neutral_i", "mouth", (29, 23, 35, 25), (95, 30, 45, 255), True),
        ("mouth_smile_i", "mouth", (28, 22, 36, 26), (120, 25, 45, 255), False),
        ("left_hand_i", "left_hand", (2, 47, 10, 56), (200, 130, 100, 255), True),
        ("right_hand_i", "right_hand", (54, 47, 62, 56), (200, 130, 100, 255), True),
        ("left_leg_i", "left_leg", (19, 55, 30, 64), (60, 65, 100, 255), True),
        ("right_leg_i", "right_leg", (34, 55, 45, 64), (60, 65, 100, 255), True),
    ]
    assets, instances, visible, variant_paths = {}, {}, [], {}
    reference = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    for order, (instance_id, semantic, box, color, is_visible) in enumerate(items):
        asset_id = f"asset_{instance_id}"
        assets[asset_id] = {
            "id": asset_id, "semantic": semantic, "source_binding": None,
            "planes": [], "compatibility": {}, "provenance": {},
        }
        instances[instance_id] = {
            "id": instance_id, "asset_ref": asset_id, "slot": semantic,
            "draw_order": order, "visible": is_visible, "opacity": 1.0,
            "transform": {"x": 0, "y": 0, "scale_x": 1, "scale_y": 1, "rotation": 0},
            "visual_ops": [],
        }
        image = root / "layers" / f"{instance_id}.png" if is_visible else root / "variants" / f"{instance_id}.png"
        _image(image, box, color)
        if is_visible:
            visible.append(instance_id)
            with Image.open(image) as layer:
                reference.alpha_composite(layer.convert("RGBA"))
        else:
            variant_paths[instance_id] = f"variants/{instance_id}.png"
    reference.save(root / "reference.png")
    # `instance.draw_order` is descriptive metadata and can lag behind the
    # authoritative composition order after a reorder; the bundle carries the
    # latter explicitly in instance_draw_order.
    for rank, row in enumerate(reversed(items)):
        instances[row[0]]["draw_order"] = rank
    (root / "provenance" / "assembly.json").write_text("{}", encoding="utf-8")
    manifest = {
        "format": "portrait-rig-bundle", "version": "0.4", "assembly_format": "portrait-assembly",
        "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
        "layers": visible, "draw_order": visible,
        "instance_draw_order": [row[0] for row in items],
        "variant_layers": variant_paths,
        "instances": instances, "assets": assets,
        "variant_sets": {
            "eyes": {"mode": "exclusive", "default": "eyes_open_i", "active": "eyes_open_i",
                     "members": ["eyes_open_i", "eyes_closed_i"]},
            "mouth_form": {"mode": "exclusive", "default": "mouth_neutral_i", "active": "mouth_neutral_i",
                           "members": ["mouth_neutral_i", "mouth_smile_i"]},
        },
        "expressions": {
            "happy": {"variants": {"mouth_form": "mouth_smile_i"},
                      "metadata": {"preserve": ["blink", "viseme"]}},
        },
        "rig_intent": {"regions": {}, "attachments": {}, "deformation_scopes": {}},
        "donors": {},
        "source_metadata": {
            "source_portrait": {
                "validation": {"static_reconstruction": "pass"},
                "derived": {"left_right": {"status": "computed", "scope": "head"}},
                "warnings": ["fixture source warning"],
            },
            "donor:mouth": {"revision": "sha256:fixture"},
        },
        "expression_intent": {
            "profile": "face_expression_core_v2",
            "articulation": {
                "blink": {"variant_set": "eyes",
                          "states": {"open": "eyes_open_i", "closed": "eyes_closed_i"}},
            },
            "emotion_channels": {
                "mouth_form": {"mode": "authored_state", "variant_set": "mouth_form"},
            },
            "presets": {
                "happy": {
                    "mouth_form": "mouth_smile_i",
                    "preserve": {"blink": True, "viseme": True},
                },
            },
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


class RigBundleReaderTests(unittest.TestCase):
    def test_rig_bundle_preserves_expression_states_side_layers_and_source_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "portrait.rigbundle"
            expected = _write_rig_bundle(root)
            asset = load_rig_bundle(root)
            self.assertEqual(asset.instance_to_tag["left_hand_i"], "left_hand")
            self.assertEqual(asset.instance_to_tag["right_hand_i"], "right_hand")
            self.assertIn("left_hand", asset.layers)
            self.assertIn("right_hand", asset.layers)
            body_side_tags = {
                "left_arm", "right_arm", "left_hand", "right_hand",
                "left_leg", "right_leg", "bottomwear",
            }
            self.assertTrue(body_side_tags <= set(asset.layers))
            self.assertEqual(asset.expression_intent, expected["expression_intent"])
            self.assertEqual(asset.source_metadata["source_portrait"]["warnings"],
                             ["fixture source warning"])
            self.assertEqual(asset.source_metadata["donor:mouth"]["revision"], "sha256:fixture")
            self.assertIn("eyes_closed_i", asset.instance_layers)
            self.assertEqual(asset.source_schema["schema_id"], "portrait-rig-bundle-v0.4")
            self.assertEqual(asset.instance_draw_order, [
                "head_i", "face_i", "neck_i", "topwear_i", "bottomwear_i", "left_arm_i",
                "right_arm_i", "eyes_open_i", "eyes_closed_i", "mouth_neutral_i", "mouth_smile_i",
                "left_hand_i", "right_hand_i", "left_leg_i", "right_leg_i",
            ])

    def test_workflow_compiles_rig_bundle_and_reports_full_body_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "portrait.rigbundle"
            _write_rig_bundle(root)
            self.assertEqual(bundle_kind(root), "rig_bundle")
            output = Path(tmp) / "portrait.rig"
            result = compile_bundle_input(root, output)
            manifest_path = result.manifest_path
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project = load_rig_project(output)
            self.assertEqual(manifest["rest_fidelity"]["status"], "pass")
            self.assertEqual(manifest["source"]["input_kind"], "rig_bundle")
            self.assertEqual(manifest["source"]["rig_bundle"], root.name)
            self.assertNotIn("donor_slots", manifest)
            self.assertEqual(manifest["source"]["source_metadata"]["source_portrait"]["warnings"],
                             ["fixture source warning"])
            self.assertEqual(manifest["source"]["expression_intent"]["presets"]["happy"]["mouth_form"],
                             "mouth_smile_i")
            self.assertIn("happy", manifest["expression_presets"])
            self.assertFalse(any(key in manifest for key in ("joints", "ik", "gait")))
            part_tags = {part["tag"] for part in manifest["parts"]}
            self.assertTrue({"left_arm", "right_arm", "left_leg", "right_leg", "left_hand", "right_hand"}
                            <= part_tags)
            self.assertEqual(project.source["kind"], "rig_bundle")
            variant_parts = {part["variant_member"] for part in manifest["parts"]
                             if "variant_member" in part}
            self.assertIn("eyes_closed_i", variant_parts)
            self.assertIn("mouth_smile_i", variant_parts)
            limits = manifest["source"]["capability_limits"]
            self.assertTrue(any("joints, IK" in item and "walking/gait" in item for item in limits))

    def test_missing_hidden_variant_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "portrait.rigbundle"
            _write_rig_bundle(root)
            (root / "variants" / "eyes_closed_i.png").unlink()
            with self.assertRaisesRegex(ValueError, "missing or outside"):
                load_rig_bundle(root)

