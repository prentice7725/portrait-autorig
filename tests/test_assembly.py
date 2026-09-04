"""Tests for assembly.py -- the Assembly Bundle v0.2 reader (Master doc
STEP 2, "AutoRig Assembly input seam").

`AssemblyBundleBuilder.write()`'s own reference.png is built with the exact
same `_position` this module uses, so `PositioningTests` below checks the
reader's positioning against it directly, including a real translate+scale+
rotate transform. This has additionally been verified against real
`portrait-composer` output (not just this file's own fixtures) in a manual
smoke test: byte-exact vs its actual `reference.png`, portrait-composer's
own `identity_assembly`/`write_assembly_bundle`. The rest of this file
covers the reader's own contract: the manifest shape it accepts, what it
does with visibility/opacity/multi-instance tags, and what it rejects.
"""

from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator
from PIL import Image

from portrait_autorig.assembly import (
    ASSEMBLY_SCHEMA_COMMIT, ASSEMBLY_SCHEMA_ID, ASSEMBLY_SCHEMA_PATH,
    ASSEMBLY_SCHEMA_SHA256,
    ASSEMBLY_SCHEMA_PIN, ASSEMBLY_SCHEMA_VENDOR, _position,
    load_assembly_bundle, validate_assembly_manifest,
)
from portrait_autorig.image import composite_layers

CANVAS = 40


def _solid_png(path: Path, box, rgba=(200, 100, 50, 255), canvas=CANVAS):
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    x1, y1, x2, y2 = box
    for y in range(y1, y2):
        for x in range(x1, x2):
            img.putpixel((x, y), rgba)
    img.save(path)


def _identity_transform():
    return {"x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0}


class AssemblyBundleBuilder:
    """Minimal on-disk Assembly Bundle builder for tests -- hand-built
    directly against `schemas/portrait-assembly-v0.2.schema.json`'s shape,
    the same approach `portrait-composer`'s own fixtures use."""

    def __init__(self, root: Path, canvas=(CANVAS, CANVAS)):
        self.root = root
        self.canvas = canvas
        self.assets: dict = {}
        self.instances: dict = {}
        self.draw_order: list[str] = []
        self.rig_intent = {"regions": {}, "attachments": {}, "deformation_scopes": {}}
        self.variant_sets = {}
        (root / "layers").mkdir(parents=True, exist_ok=True)

    def add_instance(self, instance_id, *, semantic, box, transform=None,
                     visible=True, opacity=1.0, rgba=(200, 100, 50, 255)):
        asset_id = f"{semantic}_asset_{instance_id}"
        self.assets[asset_id] = {"id": asset_id, "semantic": semantic, "source_binding": None,
                                 "planes": [], "compatibility": {}, "provenance": {}}
        self.instances[instance_id] = {
            "id": instance_id, "asset_ref": asset_id, "slot": semantic,
            "draw_order": len(self.draw_order), "visible": visible, "opacity": opacity,
            "transform": transform or _identity_transform(), "transform_link": None, "plane": None,
        }
        self.draw_order.append(instance_id)
        _solid_png(self.root / "layers" / f"{instance_id}.png", box, rgba, self.canvas[0])
        return self

    def write(self, *, format="portrait-assembly", version="0.2", omit_reference=False):
        manifest = {
            "format": format, "version": version,
            "sources": {}, "assets": self.assets, "instances": self.instances,
            "hierarchy": {}, "variant_sets": self.variant_sets, "links": {},
            "rig_intent": self.rig_intent,
            "composition": {
                "draw_order": self.draw_order,
                "canvas": {"width": self.canvas[0], "height": self.canvas[1],
                          "coordinate_system": "top-left-y-down", "color_space": "srgb",
                          "alpha": "straight"},
            },
            "provenance": {},
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if not omit_reference:
            # Applies visible/opacity/transform exactly like `assembly.
            # load_assembly_bundle` itself (reusing its own `_position`), so
            # this fixture's reference.png is trustworthy ground truth for a
            # rest_reference check even when an instance carries a real
            # transform -- not just a plausible stand-in.
            ref = Image.new("RGBA", self.canvas, (0, 0, 0, 0))
            for inst_id in self.draw_order:
                inst = self.instances[inst_id]
                if not inst["visible"] or inst["opacity"] <= 0:
                    continue
                with Image.open(self.root / "layers" / f"{inst_id}.png") as raw:
                    im = raw.convert("RGBA")
                    opacity = inst["opacity"]
                    if opacity < 1.0:
                        r, g, b, a = im.split()
                        a = a.point(lambda v: round(v * opacity))
                        im = Image.merge("RGBA", (r, g, b, a))
                    positioned, (x, y) = _position(im, inst["transform"])
                    ref.alpha_composite(positioned, dest=(x, y))
            ref.save(self.root / "reference.png")
        return self.root


class PositioningTests(unittest.TestCase):
    """The reader's own composite reproduces the fixture's reference.png
    exactly, including a real transform -- the property `rig.build_rig`'s
    `rest_reference` check now depends on."""

    def test_identity_transform_matches_reference_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.add_instance("topwear_i", semantic="topwear", box=(0, 15, 40, 40))
            builder.write()
            asset = load_assembly_bundle(root)
        composite = composite_layers(asset.layers, asset.canvas[::-1], order=tuple(asset.draw_order))
        self.assertTrue(np.array_equal(composite, asset.reference))

    def test_translate_scale_rotate_transform_matches_reference_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            transform = {"x": 3.0, "y": -2.0, "scale_x": 1.3, "scale_y": 0.7, "rotation": 12.0}
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.add_instance("topwear_i", semantic="topwear", box=(2, 15, 38, 39), transform=transform)
            builder.write()
            asset = load_assembly_bundle(root)
        composite = composite_layers(asset.layers, asset.canvas[::-1], order=tuple(asset.draw_order))
        self.assertTrue(np.array_equal(composite, asset.reference))


class LoadAssemblyBundleTests(unittest.TestCase):
    def test_composer_schema_vendor_is_pinned(self):
        self.assertEqual(ASSEMBLY_SCHEMA_VENDOR, "portrait-composer")
        self.assertEqual(ASSEMBLY_SCHEMA_COMMIT, "682f25e")
        self.assertEqual(ASSEMBLY_SCHEMA_ID, "portrait-assembly-v0.2")
        self.assertIn(ASSEMBLY_SCHEMA_COMMIT, ASSEMBLY_SCHEMA_PIN)
        raw = ASSEMBLY_SCHEMA_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ASSEMBLY_SCHEMA_SHA256)
        schema = json.loads(raw.decode("utf-8"))
        self.assertEqual(schema["$id"], "https://portrait-composer/schemas/portrait-assembly-v0.2.schema.json")

    def test_fixture_validates_against_exact_vendored_composer_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        schema = json.loads(ASSEMBLY_SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda e: list(e.path))
        self.assertEqual(errors, [], "fixture must satisfy Composer's vendored schema")

    def test_schema_validation_rejects_missing_instance_asset_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            path = root / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            del manifest["instances"]["neck_i"]["asset_ref"]
            with self.assertRaisesRegex(ValueError, "schema validation"):
                validate_assembly_manifest(manifest)

    def test_schema_extension_is_rejected_by_exact_composer_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            path = root / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["schema"] = {"vendor": ASSEMBLY_SCHEMA_VENDOR, "commit": "682f25e"}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema validation"):
                load_assembly_bundle(root)

    def test_reads_canvas_tags_and_draw_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.add_instance("topwear_i", semantic="topwear", box=(0, 15, 40, 40))
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertEqual(asset.canvas, (CANVAS, CANVAS))
        self.assertEqual(set(asset.layers), {"neck", "topwear"})
        self.assertEqual(asset.draw_order, ["neck", "topwear"])
        self.assertEqual(asset.source_id, "A001.assembly")

    def test_preserves_composer_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            manifest_path = root / "manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["provenance"] = {"composer": "2.1.0", "seed": "A002"}
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            asset = load_assembly_bundle(root)
        self.assertEqual(asset.provenance, {"composer": "2.1.0", "seed": "A002"})

    def test_invisible_instance_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.add_instance("hidden_i", semantic="hat", box=(0, 0, 10, 10), visible=False)
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertNotIn("hat", asset.layers)

    def test_zero_opacity_instance_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.add_instance("ghost_i", semantic="hat", box=(0, 0, 10, 10), opacity=0.0)
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertNotIn("hat", asset.layers)

    def test_partial_opacity_scales_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("v_i", semantic="veil", box=(0, 0, 40, 40), opacity=0.5,
                                 rgba=(10, 20, 30, 200))
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertEqual(asset.layers["veil"][20, 20, 3], round(200 * 0.5))

    def test_translated_instance_lands_at_its_offset_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            transform = {"x": 5.0, "y": 3.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0}
            builder.add_instance("m_i", semantic="mark", box=(0, 0, 4, 4), transform=transform)
            builder.write()
            asset = load_assembly_bundle(root)
        layer = asset.layers["mark"]
        self.assertTrue((layer[3:7, 5:9, 3] > 0).all())   # box (0,0,4,4) shifted by (5,3)
        self.assertFalse((layer[0:3, 0:5, 3] > 0).any())  # nothing left at the origin

    def test_two_instances_sharing_a_semantic_are_composited_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("acc1", semantic="accessory", box=(0, 0, 10, 10))
            builder.add_instance("acc2", semantic="accessory", box=(20, 20, 30, 30))
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertEqual(list(asset.layers), ["accessory"])
        combined = asset.layers["accessory"]
        self.assertTrue((combined[0:10, 0:10, 3] > 0).all())
        self.assertTrue((combined[20:30, 20:30, 3] > 0).all())

    def test_body_remainder_is_separated_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("br_i", semantic="body_remainder", box=(0, 0, 10, 10))
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertNotIn("body_remainder", asset.layers)
        self.assertIsNotNone(asset.body_remainder)
        self.assertEqual(asset.body_remainder.shape, (CANVAS, CANVAS, 4))

    def test_body_remainder_is_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertIsNone(asset.body_remainder)

    def test_rig_intent_and_variant_sets_pass_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.variant_sets = {"mouth": {"mode": "exclusive", "default": "neutral",
                                              "active": "neutral", "members": ["neutral"]}}
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertIn("mouth", asset.variant_sets)
        self.assertEqual(asset.rig_intent, {"regions": {}, "attachments": {}, "deformation_scopes": {}})

    def test_variant_members_keep_positioned_images_and_instance_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("base_i", semantic="head", box=(5, 5, 30, 30))
            builder.add_instance("mouth_neutral_i", semantic="mouth", box=(10, 20, 20, 24), visible=True)
            builder.add_instance("mouth_open_i", semantic="mouth", box=(10, 20, 22, 25), visible=False)
            builder.write()
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["variant_sets"] = {
                "mouth": {"mode": "exclusive", "default": "mouth_neutral_i",
                          "active": "mouth_neutral_i",
                          "members": ["mouth_neutral_i", "mouth_open_i"]}
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            asset = load_assembly_bundle(root)
        self.assertEqual(asset.instance_to_tag["mouth_open_i"], "mouth")
        self.assertEqual(set(asset.instance_layers), {"mouth_neutral_i", "mouth_open_i"})
        self.assertEqual(asset.expressions, {})

    def test_reference_png_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            asset = load_assembly_bundle(root)
        self.assertEqual(asset.reference.shape, (CANVAS, CANVAS, 4))

    def test_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_assembly_bundle(tmp)

    def test_wrong_format_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write(format="portrait-bundle")
            with self.assertRaises(ValueError):
                load_assembly_bundle(root)

    def test_unsupported_version_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write(version="1.0")
            with self.assertRaises(ValueError):
                load_assembly_bundle(root)

    def test_minor_version_bump_is_rejected_not_just_major(self):
        # Exact match, not a major-version prefix check: pre-1.0, 0.2 -> 0.3
        # can be a breaking contract change.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write(version="0.3")
            with self.assertRaises(ValueError):
                load_assembly_bundle(root)

    def test_missing_draw_order_is_rejected_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["composition"]["draw_order"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_assembly_bundle(root)

    def test_non_contiguous_same_semantic_instances_are_rejected(self):
        # neck_i / neck2_i share "neck" but topwear_i is drawn between them
        # -- flattening the two neck instances into one bitmap would lose
        # exactly which side of topwear each one belongs on.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 20, 30))
            builder.add_instance("topwear_i", semantic="topwear", box=(0, 25, 40, 40))
            builder.add_instance("neck2_i", semantic="neck", box=(20, 20, 30, 30))
            builder.write()
            with self.assertRaises(ValueError):
                load_assembly_bundle(root)

    def test_contiguous_same_semantic_instances_are_accepted(self):
        # Same shape as above, but the two "neck" instances are adjacent --
        # nothing is lost by flattening them together.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 20, 30))
            builder.add_instance("neck2_i", semantic="neck", box=(20, 20, 30, 30))
            builder.add_instance("topwear_i", semantic="topwear", box=(0, 25, 40, 40))
            builder.write()
            asset = load_assembly_bundle(root)  # must not raise
        self.assertEqual(set(asset.layers), {"neck", "topwear"})

    def test_an_invisible_instance_between_same_semantic_instances_does_not_break_contiguity(self):
        # The gap is only real if something *visible* was meant to draw
        # between them; an invisible/zero-opacity instance in between must
        # not trip the contiguity check.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 20, 30))
            builder.add_instance("hidden_i", semantic="topwear", box=(0, 25, 40, 40), visible=False)
            builder.add_instance("neck2_i", semantic="neck", box=(20, 20, 30, 30))
            builder.write()
            asset = load_assembly_bundle(root)  # must not raise
        self.assertEqual(set(asset.layers), {"neck"})

    def test_missing_layer_image_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write()
            (root / "layers" / "neck_i.png").unlink()
            with self.assertRaises(FileNotFoundError):
                load_assembly_bundle(root)

    def test_missing_reference_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A001.assembly"
            builder = AssemblyBundleBuilder(root)
            builder.add_instance("neck_i", semantic="neck", box=(10, 20, 30, 40))
            builder.write(omit_reference=True)
            with self.assertRaises(FileNotFoundError):
                load_assembly_bundle(root)


if __name__ == "__main__":
    unittest.main()
