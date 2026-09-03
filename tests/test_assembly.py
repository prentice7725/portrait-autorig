"""Tests for assembly.py -- the Assembly Bundle v0.2 reader (Master doc
STEP 2, "AutoRig Assembly input seam").

Positioning is verified against real `portrait-composer` output directly in
a manual smoke test (byte-exact vs `reference.png`, including a real
translate+scale+rotate transform) rather than here, since that repo is not
a dependency of this one. These tests cover the reader's own contract: the
manifest shape it accepts, what it does with visibility/opacity/multi-
instance tags, and what it rejects.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from portrait_autorig.assembly import load_assembly_bundle

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
            # A plausible-enough reference: composite of everything visible,
            # matching what render_reference would produce for these
            # fixtures. Not exercised for pixel equality here (see module
            # docstring) -- just needs to exist and be readable.
            ref = Image.new("RGBA", self.canvas, (0, 0, 0, 0))
            for inst in self.instances.values():
                if not inst["visible"] or inst["opacity"] <= 0:
                    continue
                with Image.open(self.root / "layers" / f"{inst['id']}.png") as im:
                    ref.alpha_composite(im.convert("RGBA"))
            ref.save(self.root / "reference.png")
        return self.root


class LoadAssemblyBundleTests(unittest.TestCase):
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
