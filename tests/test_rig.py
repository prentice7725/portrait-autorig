import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from portrait_autorig.image import composite_layers
from portrait_autorig.rig import (
    BODY_REMAINDER, BODY_WEIGHT, EYE_SPLIT_TAGS,
    GROUP_BODY, GROUP_HEAD, GROUP_NECK,
    HEAD_REMAINDER, HEAD_WEIGHT, NECK_REMAINDER,
    RIG_Z_ORDER, build_rig, depth_table, derive_missing_eyewhite, detect_anchors,
    group_for_tag, render_rig_rest, rig_preflight, split_eyes, split_remainder,
    write_rig_project,
)

CANVAS = 128


def rgba(boxes, value=255):
    """Canvas-sized RGBA with `boxes` -- (x1, y1, x2, y2) -- filled opaque."""
    img = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
    for x1, y1, x2, y2 in boxes:
        img[y1:y2, x1:x2, :3] = value
        img[y1:y2, x1:x2, 3] = 255
    return img


def portrait_layers():
    """A crude upper-body portrait: head block on top, neck between, torso
    below, with both eyes inside one `eyewhite` layer the way v3 emits them."""
    return {
        "back hair": rgba([(40, 8, 88, 60)]),
        "head": rgba([(48, 12, 80, 56)]),
        "face": rgba([(52, 20, 76, 52)]),
        "eyewhite": rgba([(56, 30, 62, 36), (66, 30, 72, 36)]),
        "mouth": rgba([(61, 44, 67, 47)]),
        "neck": rgba([(58, 56, 70, 72)]),
        "topwear": rgba([(36, 72, 92, 124)]),
    }


def a002_like_layers():
    """Featureless face over an occlusion-complete head with sclera baked in."""
    skin = 176
    layers = {
        "head": rgba([(40, 8, 88, 68)], skin),
        "face": rgba([(44, 12, 84, 64)], skin),
        "irides": rgba([(51, 31, 55, 37), (73, 31, 77, 37)], 24),
        "eyelash": rgba([(46, 28, 60, 30), (68, 28, 82, 30)], 32),
        "eyebrow": rgba([(46, 22, 60, 24), (68, 22, 82, 24)], 48),
        "mouth": rgba([(59, 50, 69, 52)], 64),
        "neck": rgba([(58, 68, 70, 82)], skin),
        "topwear": rgba([(34, 82, 94, 124)], 112),
    }
    # Only head/original know the sclera; face is opaque skin over it.
    for x1, x2 in ((46, 60), (68, 82)):
        layers["head"][30:38, x1:x2, :3] = 235
        # The canonical stack reveals head's sclera through a face socket. The
        # rig fallback must preserve that rest image while changing ownership.
        layers["face"][30:38, x1:x2, 3] = 0
    original = np.array(layers["head"], copy=True)
    for tag in ("irides", "eyelash", "eyebrow", "mouth"):
        mask = layers[tag][..., 3] > 10
        original[mask] = layers[tag][mask]
    return layers, original


def full_rig_layers(manifest, images):
    out = {}
    h, w = manifest["canvas"]["height"], manifest["canvas"]["width"]
    for part in manifest["parts"]:
        full = np.zeros((h, w, 4), np.uint8)
        x1, y1, x2, y2 = part["xyxy"]
        full[y1:y2, x1:x2] = images[part["name"]]
        out[part["tag"]] = full
    return out


def composite_in_manifest_order(manifest, images):
    layers = full_rig_layers(manifest, images)
    h, w = manifest["canvas"]["height"], manifest["canvas"]["width"]
    rgb = np.zeros((h, w, 3), np.float32)
    alpha = np.zeros((h, w, 1), np.float32)
    for part in manifest["parts"]:
        src = layers[part["tag"]].astype(np.float32)
        src_alpha = src[..., 3:4] / 255.0
        rgb = src[..., :3] * src_alpha + rgb * (1.0 - src_alpha)
        alpha = src_alpha + alpha * (1.0 - src_alpha)
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = np.rint(rgb).astype(np.uint8)
    out[..., 3] = np.rint(alpha[..., 0] * 255).astype(np.uint8)
    return out


class GroupTests(unittest.TestCase):
    def test_known_tags_land_in_their_group(self):
        self.assertEqual(group_for_tag("face"), GROUP_HEAD)
        self.assertEqual(group_for_tag("back hair"), GROUP_HEAD)
        self.assertEqual(group_for_tag("neck"), GROUP_NECK)
        self.assertEqual(group_for_tag("topwear"), GROUP_BODY)

    def test_remainder_regions_follow_their_own_group(self):
        self.assertEqual(group_for_tag(HEAD_REMAINDER), GROUP_HEAD)
        self.assertEqual(group_for_tag(NECK_REMAINDER), GROUP_NECK)
        self.assertEqual(group_for_tag(BODY_REMAINDER), GROUP_BODY)

    def test_unknown_tag_falls_back_to_body(self):
        """A mystery layer that fails to follow the head is a missed
        opportunity; one that follows it can tear off the torso."""
        self.assertEqual(group_for_tag("no-such-tag"), GROUP_BODY)


class DepthTableTests(unittest.TestCase):
    def test_runs_from_far_to_near_over_the_z_order(self):
        table = depth_table()
        self.assertEqual(table[RIG_Z_ORDER[0]], 1.0)
        self.assertEqual(table[RIG_Z_ORDER[-1]], 0.0)

    def test_back_hair_is_further_than_front_hair(self):
        table = depth_table()
        self.assertGreater(table["back hair"], table["face"])
        self.assertGreater(table["face"], table["front hair"])

    def test_remainder_regions_sit_behind_what_they_move_with(self):
        table = depth_table()
        self.assertEqual(table[HEAD_REMAINDER], table["head"])
        self.assertEqual(table[NECK_REMAINDER], table["neck"])
        self.assertEqual(table[BODY_REMAINDER], 1.0)
        self.assertLess(RIG_Z_ORDER.index(HEAD_REMAINDER), RIG_Z_ORDER.index("back hair"))
        self.assertLess(RIG_Z_ORDER.index(NECK_REMAINDER), RIG_Z_ORDER.index("back hair"))


class SplitRemainderTests(unittest.TestCase):
    def test_pixels_are_assigned_to_the_nearest_group(self):
        layers = portrait_layers()
        # One patch beside the head, one beside the torso.
        remainder = rgba([(30, 20, 40, 30), (20, 90, 30, 100)])
        regions = split_remainder(remainder, layers)

        self.assertIn(HEAD_REMAINDER, regions)
        self.assertIn(BODY_REMAINDER, regions)
        self.assertTrue(regions[HEAD_REMAINDER][20:30, 30:40, 3].all())
        self.assertFalse(regions[BODY_REMAINDER][20:30, 30:40, 3].any())
        self.assertTrue(regions[BODY_REMAINDER][90:100, 20:30, 3].all())

    def test_neck_band_is_carved_out_first(self):
        layers = portrait_layers()
        remainder = rgba([(59, 58, 69, 70)])  # inside the neck bbox
        regions = split_remainder(remainder, layers)
        self.assertIn(NECK_REMAINDER, regions)
        self.assertNotIn(HEAD_REMAINDER, regions)
        self.assertNotIn(BODY_REMAINDER, regions)

    def test_tiny_isolated_neck_orphan_is_not_promoted(self):
        layers = portrait_layers()
        # Three disconnected pixels inside the neck bbox have location but no
        # connected semantic support. This is the A002 failure shape.
        remainder = rgba([(59, 59, 60, 60), (64, 63, 65, 64), (68, 69, 69, 70)])
        regions = split_remainder(remainder, layers)
        self.assertNotIn(NECK_REMAINDER, regions)
        self.assertEqual(sum(int((image[..., 3] > 10).sum()) for image in regions.values()), 3)

    def test_connected_neck_remainder_with_semantic_contact_is_preserved(self):
        layers = portrait_layers()
        remainder = rgba([(59, 58, 69, 70)])
        regions = split_remainder(remainder, layers)
        self.assertEqual(int((regions[NECK_REMAINDER][..., 3] > 10).sum()), 120)

    def test_neck_bbox_without_semantic_contact_does_not_claim_component(self):
        layers = portrait_layers()
        # Two neck rails create a bbox around an empty centre. A substantial
        # component in that rectangle still has no neck contact evidence.
        layers["neck"] = rgba([(56, 56, 58, 72), (70, 56, 72, 72)])
        remainder = rgba([(62, 62, 66, 66)])
        regions = split_remainder(remainder, layers)
        self.assertNotIn(NECK_REMAINDER, regions)
        self.assertEqual(sum(int((image[..., 3] > 10).sum()) for image in regions.values()), 16)

    def test_every_recovered_pixel_survives_exactly_one_region(self):
        """The split must not lose or duplicate recovered pixels -- losing them
        would undo the Silhouette Guard's whole point."""
        layers = portrait_layers()
        remainder = rgba([(30, 20, 40, 30), (20, 90, 30, 100), (59, 58, 69, 70)])
        regions = split_remainder(remainder, layers)
        total = np.zeros((CANVAS, CANVAS), dtype=np.int32)
        for img in regions.values():
            total += (img[..., 3] > 10).astype(np.int32)
        np.testing.assert_array_equal(total, (remainder[..., 3] > 10).astype(np.int32))

    def test_empty_remainder_produces_no_regions(self):
        self.assertEqual(split_remainder(np.zeros((CANVAS, CANVAS, 4), np.uint8),
                                         portrait_layers()), {})

    def test_rejects_non_rgba(self):
        with self.assertRaises(ValueError):
            split_remainder(np.zeros((CANVAS, CANVAS, 3), np.uint8), portrait_layers())


class SplitEyesTests(unittest.TestCase):
    def test_both_eyes_in_one_layer_are_separated(self):
        layers = portrait_layers()
        halves = split_eyes(layers, face_center_x=64.0)
        self.assertEqual(set(halves), {"eyewhitel", "eyewhiter"})
        self.assertTrue(halves["eyewhitel"][30:36, 56:62, 3].all())
        self.assertFalse(halves["eyewhitel"][30:36, 66:72, 3].any())
        self.assertTrue(halves["eyewhiter"][30:36, 66:72, 3].all())

    def test_single_component_layer_is_left_whole(self):
        """One eye visible (a three-quarter view, or an occluded eye) is not a
        failed split -- the caller keeps the layer intact."""
        layers = {"eyewhite": rgba([(56, 30, 62, 36)])}
        self.assertEqual(split_eyes(layers, face_center_x=64.0), {})

    def test_components_on_one_side_only_are_left_whole(self):
        layers = {"eyewhite": rgba([(20, 30, 26, 36), (30, 30, 36, 36)])}
        self.assertEqual(split_eyes(layers, face_center_x=64.0), {})

    def test_dilation_never_invents_alpha_outside_the_layer(self):
        layers = portrait_layers()
        halves = split_eyes(layers, face_center_x=64.0, dilate_px=4)
        source = layers["eyewhite"][..., 3] > 10
        for img in halves.values():
            self.assertFalse((img[..., 3] > 10)[~source].any())

    def test_every_split_tag_is_a_known_v3_eye_layer(self):
        self.assertIn("eyewhite", EYE_SPLIT_TAGS)
        self.assertIn("irides", EYE_SPLIT_TAGS)


class DerivedEyewhiteTests(unittest.TestCase):
    def setUp(self):
        self.layers, self.original = a002_like_layers()

    def test_missing_eyewhite_can_be_derived_bilaterally(self):
        center = detect_anchors(self.layers, (CANVAS, CANVAS))["face_center"][0]
        split = dict(self.layers)
        halves = split_eyes(split, center)
        split.update(halves)
        for parent in {tag[:-1] for tag in halves}:
            split.pop(parent, None)
        derived, report = derive_missing_eyewhite(self.original, split)
        self.assertEqual(set(derived), {"eyewhitel", "eyewhiter"})
        self.assertTrue(report["succeeded"])
        self.assertGreaterEqual(report["confidence"], 0.55)

    def test_native_eyewhite_uses_existing_split_path_without_fallback(self):
        original = np.array(self.layers["head"], copy=True)
        layers = portrait_layers()
        with patch("portrait_autorig.rig.derive_missing_eyewhite") as fallback:
            manifest, _ = build_rig(layers, original_rgba=original,
                                    frame_size=(CANVAS, CANVAS))
        fallback.assert_not_called()
        tags = {part["tag"] for part in manifest["parts"]}
        self.assertIn("eyewhitel", tags)
        self.assertIn("eyewhiter", tags)

    def test_derived_coverage_is_removed_from_head_working_copy(self):
        manifest, images = build_rig(self.layers, original_rgba=self.original,
                                     frame_size=(CANVAS, CANVAS))
        full = full_rig_layers(manifest, images)
        derived = ((full["eyewhitel"][..., 3] > 10)
                   | (full["eyewhiter"][..., 3] > 10))
        self.assertTrue(derived.any())
        self.assertFalse((full["head"][..., 3] > 10)[derived].any())

    def test_rest_composite_fidelity_improves(self):
        baseline_manifest, baseline_images = build_rig(
            self.layers, frame_size=(CANVAS, CANVAS)
        )
        derived_manifest, derived_images = build_rig(
            self.layers, original_rgba=self.original, frame_size=(CANVAS, CANVAS)
        )
        baseline = composite_in_manifest_order(baseline_manifest, baseline_images)
        derived = composite_in_manifest_order(derived_manifest, derived_images)
        subject = self.original[..., 3] > 10
        baseline_error = np.abs(baseline[..., :3].astype(int)
                                - self.original[..., :3].astype(int))[subject].mean()
        derived_error = np.abs(derived[..., :3].astype(int)
                               - self.original[..., :3].astype(int))[subject].mean()
        self.assertLessEqual(derived_error, baseline_error)

    def test_derived_eyewhite_tracks_face_during_head_turn(self):
        manifest, _ = build_rig(self.layers, original_rgba=self.original,
                                frame_size=(CANVAS, CANVAS))
        parts = {part["tag"]: part for part in manifest["parts"]}
        for tag in ("eyewhitel", "eyewhiter"):
            self.assertEqual(parts[tag]["depth"], parts["face"]["depth"])
            self.assertEqual(parts[tag]["weight"], parts["face"]["weight"])
            self.assertTrue(parts[tag]["derived"])

    def test_low_confidence_derivation_stays_degraded(self):
        flat = np.array(self.layers["face"], copy=True)
        preflight = rig_preflight(self.layers, original_rgba=flat)
        self.assertEqual(preflight["status"], "DEGRADED")
        self.assertEqual(preflight["checks"]["eyewhite"]["available"], "missing")

    def test_preflight_distinguishes_native_and_derived_readiness(self):
        derived = rig_preflight(self.layers, original_rgba=self.original)
        self.assertEqual(derived["status"], "READY_WITH_DERIVATION")
        native_layers = dict(self.layers)
        native_layers["eyewhite"] = rgba([(46, 30, 60, 38), (68, 30, 82, 38)], 235)
        native = rig_preflight(native_layers, original_rgba=self.original)
        self.assertEqual(native["status"], "READY")
        self.assertEqual(native["checks"]["eyewhite"]["available"], "native")

    def test_missing_head_or_face_is_incompatible_not_static_invalid(self):
        preflight = rig_preflight({"face": self.layers["face"]},
                                  original_rgba=self.original)
        self.assertEqual(preflight["status"], "INCOMPATIBLE")
        self.assertEqual(preflight["static_portrait_validity"], "not_evaluated")


class RestFidelityTests(unittest.TestCase):
    def test_rig_rest_matches_canonical_layer_reference(self):
        layers = portrait_layers()
        remainder = rgba([(30, 20, 40, 30), (59, 58, 69, 70)])
        manifest, images = build_rig(layers, body_remainder=remainder,
                                     frame_size=(CANVAS, CANVAS))
        canonical = dict(layers)
        canonical[BODY_REMAINDER] = remainder
        reference = composite_layers(canonical, (CANVAS, CANVAS))
        rest = render_rig_rest(manifest["parts"], images, (CANVAS, CANVAS))
        np.testing.assert_array_equal(rest, reference)
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")
        self.assertEqual(manifest["rest_fidelity"]["visibility_changed_px"], 0)

    def test_hidden_remainder_does_not_become_visible_after_subdivision(self):
        layers = portrait_layers()
        layers["topwear"] = rgba([(36, 50, 92, 124)], 90)
        remainder = rgba([(59, 58, 69, 70)], 240)
        manifest, images = build_rig(layers, body_remainder=remainder,
                                     frame_size=(CANVAS, CANVAS))
        tags = {part["tag"] for part in manifest["parts"]}
        self.assertIn(NECK_REMAINDER, tags)
        rest = render_rig_rest(manifest["parts"], images, (CANVAS, CANVAS))
        self.assertEqual(tuple(rest[62, 64, :3]), (90, 90, 90))
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")

    def test_crop_and_reposition_preserve_faint_alpha_edges(self):
        layers = portrait_layers()
        mouth = np.zeros((CANVAS, CANVAS, 4), np.uint8)
        mouth[43:49, 58:70, :3] = 35
        mouth[43:49, 58:70, 3] = 3
        mouth[44:48, 59:69, 3] = 255
        layers["mouth"] = mouth
        manifest, images = build_rig(layers, frame_size=(CANVAS, CANVAS))
        mouth_part = next(part for part in manifest["parts"] if part["tag"] == "mouth")
        self.assertEqual(mouth_part["xyxy"], [58, 43, 70, 49])
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")
        self.assertEqual(manifest["rest_fidelity"]["visibility_changed_px"], 0)

    def test_neck_topwear_draw_order_matches_canonical_stack(self):
        layers = portrait_layers()
        layers["neck"] = rgba([(58, 56, 70, 76)], 210)
        layers["topwear"] = rgba([(50, 66, 78, 100)], 70)
        manifest, images = build_rig(layers, frame_size=(CANVAS, CANVAS))
        rest = render_rig_rest(manifest["parts"], images, (CANVAS, CANVAS))
        self.assertEqual(tuple(rest[70, 64, :3]), (70, 70, 70))
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")


class AnchorTests(unittest.TestCase):
    def test_neck_pivot_sits_near_the_bottom_of_the_neck(self):
        """Hinging at the bottom is what makes a tilt read as a neck bending
        rather than a head sliding sideways."""
        layers = portrait_layers()
        anchors = detect_anchors(layers, (CANVAS, CANVAS))
        x, y = anchors["neck_pivot"]
        self.assertAlmostEqual(x, 64.0, places=1)
        self.assertAlmostEqual(y, 56 + (72 - 56) * 0.85, places=1)

    def test_body_pivot_is_the_bottom_of_the_torso(self):
        anchors = detect_anchors(portrait_layers(), (CANVAS, CANVAS))
        self.assertAlmostEqual(anchors["body_pivot"][1], 124.0, places=1)

    def test_missing_anchors_are_omitted_not_guessed(self):
        """A fabricated eye position is worse than an absent one: the runtime
        can skip a motion it has no anchor for."""
        anchors = detect_anchors({"face": rgba([(52, 20, 76, 52)])}, (CANVAS, CANVAS))
        self.assertNotIn("eye_left", anchors)
        self.assertNotIn("mouth", anchors)
        self.assertIn("face_center", anchors)

    def test_eye_anchors_appear_once_the_eyes_are_split(self):
        layers = portrait_layers()
        layers.update(split_eyes(layers, face_center_x=64.0))
        anchors = detect_anchors(layers, (CANVAS, CANVAS))
        self.assertLess(anchors["eye_left"][0], anchors["eye_right"][0])


class BuildRigTests(unittest.TestCase):
    def setUp(self):
        self.layers = portrait_layers()
        self.remainder = rgba([(30, 20, 40, 30), (20, 90, 30, 100)])

    def test_manifest_shape(self):
        manifest, images = build_rig(self.layers, body_remainder=self.remainder,
                                     frame_size=(CANVAS, CANVAS), run_id="r1",
                                     tag_version="v3")
        # build_rig constructs the v0.1 shape (parts/anchors/motion/...) and
        # then upgrades it to v0.2 in place (PORTRAIT_AUTORIG_PRIOR_ART_
        # ABSORPTION_PLAN v0.1 #7, #18): every v0.1 field survives, and
        # parameters[]/deformers[]/drivers[] are added on top.
        self.assertEqual(manifest["version"], "0.2")
        self.assertEqual(manifest["canvas"], {"width": CANVAS, "height": CANVAS})
        self.assertEqual(manifest["source"]["depth"], "table")
        self.assertTrue(manifest["parts"])
        for part in manifest["parts"]:
            self.assertIn(part["name"], images)
            self.assertEqual(part["image"], f"rig/images/{part['name']}.png")
        self.assertTrue(manifest["parameters"])
        self.assertTrue(manifest["deformers"])
        self.assertEqual(manifest["drivers"], [])
        deformer_kinds = {d["kind"] for d in manifest["deformers"]}
        self.assertEqual(deformer_kinds,
                         {"parallax_turn", "shell_turn", "weighted_rotation",
                          "continuous_field", "eye_fold", "gaze"})

    def test_every_part_carries_a_frozen_mesh_topology_hash(self):
        # directive v0.2 #11-12 (P0-G): generate mesh -> hash -> freeze.
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        for part in manifest["parts"]:
            self.assertIn("topology_hash", part["mesh"])
            self.assertTrue(part["mesh"]["topology_hash"].startswith("sha256:"))

    def test_manifest_has_an_evaluation_phase_contract(self):
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        self.assertIn("evaluation", manifest)
        self.assertIn("phases", manifest["evaluation"])
        for deformer in manifest["deformers"]:
            self.assertIn(deformer["phase"], manifest["evaluation"]["phases"])

    def test_manifest_has_a_capability_report(self):
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        self.assertIn("capabilities", manifest)
        self.assertEqual(manifest["capabilities"]["head_turn"], "ready")
        self.assertIn(manifest["capabilities"]["mouth_open"], {"ready", "degraded", "disabled"})

    def test_provenance_is_forwarded_opaquely(self):
        provenance = {"composer": "2.1.0", "seed": "A002"}
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS), provenance=provenance)
        self.assertEqual(manifest["source"]["provenance"], provenance)
        self.assertEqual(manifest["provenance"], provenance)

    def test_preflight_reports_gaze_readiness_without_gating_compile(self):
        preflight = rig_preflight(self.layers, body_remainder=self.remainder)
        self.assertIn("gaze", preflight["checks"])
        self.assertEqual(preflight["checks"]["gaze"]["available"], "disabled")

    def test_visibility_curves_compile_into_visibility_deformers(self):
        manifest, _ = build_rig(
            self.layers, frame_size=(CANVAS, CANVAS),
            visibility_curves=[{
                "parameter": "ParamEyeLOpen", "targets": ["eyewhitel"],
                "points": [{"value": 0.0, "alpha": 1.0}, {"value": 1.0, "alpha": 0.0}],
            }],
        )
        curves = [d for d in manifest["deformers"] if d["kind"] == "visibility_curve"]
        self.assertEqual(len(curves), 1)
        self.assertEqual(curves[0]["phase"], "visibility")

    def test_default_draw_order_matches_the_canonical_semantic_table(self):
        # No draw_order supplied (every Portrait Bundle caller) reproduces
        # today's ordering exactly -- draw_order != motion_depth, directive
        # v0.2 #5, but with nothing supplied there is only ever one source.
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        self.assertEqual(manifest["source"]["draw_order"], "table")
        tags_by_z = [p["tag"] for p in sorted(manifest["parts"], key=lambda p: p["z"])]
        expected = sorted(tags_by_z, key=lambda t: RIG_Z_ORDER.index(t) if t in RIG_Z_ORDER else -1)
        self.assertEqual(tags_by_z, expected)

    def test_explicit_draw_order_overrides_the_canonical_paint_order(self):
        # A deliberately non-canonical order: topwear painted (and hence
        # z-ordered) ahead of neck/head, the reverse of RIG_Z_ORDER.
        order = ["topwear", "neck", "eyewhite", "face", "head", "back hair", "mouth"]
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS), draw_order=order)
        self.assertEqual(manifest["source"]["draw_order"], "assembly")
        tags_by_z = [p["tag"] for p in sorted(manifest["parts"], key=lambda p: p["z"])]
        self.assertLess(tags_by_z.index("topwear"), tags_by_z.index("neck"))
        self.assertLess(tags_by_z.index("neck"), tags_by_z.index("head"))

    def test_a_tag_draw_order_never_saw_inherits_its_parents_position(self):
        # "eyewhite" (undivided) is what draw_order names; the compiled rig
        # only ever has eyewhitel/eyewhiter (an AutoRig-only derivation
        # Composer has no concept of), which must inherit "eyewhite"'s slot
        # -- adjacent to "face", not silently dropped to the back.
        order = ["back hair", "head", "face", "eyewhite", "neck", "topwear", "mouth"]
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS), draw_order=order)
        tags_by_z = [p["tag"] for p in sorted(manifest["parts"], key=lambda p: p["z"])]
        self.assertNotIn("eyewhite", tags_by_z)  # replaced by its halves
        self.assertIn("eyewhitel", tags_by_z)
        self.assertIn("eyewhiter", tags_by_z)
        self.assertLess(tags_by_z.index("face"), tags_by_z.index("eyewhitel"))
        self.assertLess(tags_by_z.index("eyewhitel"), tags_by_z.index("neck"))

    def test_a_tag_with_no_ancestor_in_draw_order_sorts_after_everything_authored(self):
        order = ["neck", "topwear"]  # deliberately incomplete
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS), draw_order=order)
        tags_by_z = [p["tag"] for p in sorted(manifest["parts"], key=lambda p: p["z"])]
        self.assertLess(tags_by_z.index("neck"), tags_by_z.index("topwear"))
        for unlisted in ("head", "face", "back hair", "mouth"):
            self.assertGreater(tags_by_z.index(unlisted), tags_by_z.index("topwear"))

    def test_rest_reference_none_keeps_the_self_recomposited_check(self):
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")

    def test_rest_reference_matching_the_natural_composite_still_passes(self):
        # A caller-supplied reference that agrees with what AutoRig would
        # have recomposited itself changes nothing.
        natural = composite_layers(self.layers, (CANVAS, CANVAS))
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS), rest_reference=natural)
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")

    def test_rest_reference_overrides_the_internal_composite_and_can_fail(self):
        # This is the actual point of the parameter (Assembly Truth, Master
        # doc #2): a rest_reference that disagrees with the rig's own rest
        # render must be able to fail the check, not be silently ignored in
        # favour of a self-consistent internal recomposite.
        wrong_reference = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)  # fully transparent
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS),
                                rest_reference=wrong_reference)
        self.assertEqual(manifest["rest_fidelity"]["status"], "fail")

    def test_rest_reference_shape_mismatch_raises(self):
        wrong_shape = np.zeros((CANVAS, CANVAS, 3), dtype=np.uint8)  # missing alpha channel
        with self.assertRaises(ValueError):
            build_rig(self.layers, frame_size=(CANVAS, CANVAS), rest_reference=wrong_shape)

    def test_contour_tags_opts_a_part_into_the_contour_mesh_backend(self):
        # absorption plan #8 (P1-A): grid stays the default everywhere else,
        # only the opted-in tag's own part switches.
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS),
                                contour_tags=("face",))
        by_tag = {part["tag"]: part for part in manifest["parts"]}
        self.assertEqual(by_tag["face"]["mesh"]["kind"], "contour")
        self.assertIn("vertices", by_tag["face"]["mesh"])
        self.assertIn("triangles", by_tag["face"]["mesh"])
        self.assertEqual(by_tag["head"]["mesh"]["kind"], "grid")

    def test_contour_tags_does_not_change_output_for_unlisted_tags(self):
        default_manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        contour_manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS),
                                        contour_tags=("face",))
        for tag in ("head", "neck", "topwear"):
            default_part = next(p for p in default_manifest["parts"] if p["tag"] == tag)
            contour_part = next(p for p in contour_manifest["parts"] if p["tag"] == tag)
            self.assertEqual(default_part, contour_part)

    def test_undivided_eye_layer_is_replaced_by_its_halves(self):
        manifest, images = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        names = {part["tag"] for part in manifest["parts"]}
        self.assertIn("eyewhitel", names)
        self.assertIn("eyewhiter", names)
        self.assertNotIn("eyewhite", names)  # would double-draw the eyes

    def test_remainder_regions_become_parts_in_their_own_groups(self):
        manifest, _ = build_rig(self.layers, body_remainder=self.remainder,
                                frame_size=(CANVAS, CANVAS))
        groups = {part["tag"]: part["group"] for part in manifest["parts"]}
        self.assertEqual(groups[HEAD_REMAINDER], GROUP_HEAD)
        self.assertEqual(groups[BODY_REMAINDER], GROUP_BODY)

    def test_head_remainder_is_drawn_behind_the_head_but_follows_it(self):
        """This is the ghost-silhouette fix: behind in z, head weight in motion."""
        manifest, _ = build_rig(self.layers, body_remainder=self.remainder,
                                frame_size=(CANVAS, CANVAS))
        parts = {part["tag"]: part for part in manifest["parts"]}
        self.assertLess(parts[HEAD_REMAINDER]["z"], parts["head"]["z"])
        self.assertEqual(parts[HEAD_REMAINDER]["weight"],
                         {"mode": "constant", "value": HEAD_WEIGHT})

    def test_parts_are_ordered_back_to_front(self):
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        zs = [part["z"] for part in manifest["parts"]]
        depths = [part["depth"] for part in manifest["parts"]]
        self.assertEqual(zs, sorted(zs))
        self.assertEqual(depths, sorted(depths, reverse=True))

    def test_neck_gets_a_gradient_spanning_the_whole_neck_group(self):
        manifest, _ = build_rig(self.layers, body_remainder=rgba([(59, 58, 69, 70)]),
                                frame_size=(CANVAS, CANVAS))
        weights = {part["tag"]: part["weight"] for part in manifest["parts"]}
        self.assertEqual(weights["neck"]["mode"], "gradient_y")
        self.assertGreater(weights["neck"]["top"], weights["neck"]["bottom"])
        # neck and neck_remainder must share one gradient or they deform
        # differently along the seam between them.
        self.assertEqual(weights["neck"], weights[NECK_REMAINDER])

    def test_the_neck_gradient_ends_exactly_on_the_head_and_the_body(self):
        """These endpoints are not free parameters. A neck top below
        HEAD_WEIGHT puts a step at the jaw, and a bottom that is not
        BODY_WEIGHT puts one at the collar -- and with a stand collar hiding
        three quarters of the neck, the jaw step is all you see."""
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        weights = {part["tag"]: part["weight"] for part in manifest["parts"]}
        self.assertEqual(weights["neck"]["top"], HEAD_WEIGHT)
        self.assertEqual(weights["neck"]["bottom"], BODY_WEIGHT)
        self.assertEqual(weights["face"], {"mode": "constant", "value": HEAD_WEIGHT})

    def test_a_collar_shares_the_neck_gradient_exactly(self):
        """`reclaim_occluded` cuts a window in the garment for the neck to show
        through, so the window and its contents are two sides of one seam. Two
        different weight functions there and the window's edge slices the neck
        as the head turns -- a 2.05 px crack on the collar line, measured."""
        layers = dict(self.layers)
        layers["topwear"] = rgba([(36, 66, 92, 124)])  # collar rides up over the neck
        manifest, _ = build_rig(layers, frame_size=(CANVAS, CANVAS))
        weights = {part["tag"]: part["weight"] for part in manifest["parts"]}
        self.assertEqual(weights["topwear"], weights["neck"])
        self.assertEqual(weights["topwear"]["top"], HEAD_WEIGHT)
        self.assertEqual(weights["topwear"]["bottom"], BODY_WEIGHT)

    def test_a_garment_clear_of_the_neck_stays_rigid(self):
        """A low neckline is not a collar; ramping it would wobble the torso."""
        layers = dict(self.layers)
        layers["topwear"] = rgba([(36, 80, 92, 124)])
        manifest, _ = build_rig(layers, frame_size=(CANVAS, CANVAS))
        weights = {part["tag"]: part["weight"] for part in manifest["parts"]}
        self.assertEqual(weights["topwear"], {"mode": "constant", "value": BODY_WEIGHT})

    def test_gradient_parts_get_the_finer_mesh(self):
        """At CANVAS=128 both cells clamp to the 8px floor, so this has to run
        at a realistic size to say anything."""
        big = {tag: np.kron(img, np.ones((6, 6, 1), np.uint8)) for tag, img in self.layers.items()}
        manifest, _ = build_rig(big, frame_size=(CANVAS * 6, CANVAS * 6))
        parts = {part["tag"]: part for part in manifest["parts"]}
        self.assertLess(parts["neck"]["mesh"]["cell"], parts["face"]["mesh"]["cell"])

    def test_body_follows_the_head_a_little(self):
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS))
        weights = {part["tag"]: part["weight"] for part in manifest["parts"]}
        self.assertEqual(weights["topwear"], {"mode": "constant", "value": BODY_WEIGHT})

    def test_gradient_tags_opt_a_head_layer_into_a_falloff(self):
        """The documented `back hair` risk: hair reaching past the shoulder
        line tears if it follows the head at full weight."""
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS),
                                gradient_tags=("back hair",))
        weights = {part["tag"]: part["weight"] for part in manifest["parts"]}
        self.assertEqual(weights["back hair"]["mode"], "gradient_y")
        self.assertEqual(weights["back hair"]["top"], HEAD_WEIGHT)
        self.assertEqual(weights["back hair"]["bottom"], BODY_WEIGHT)
        self.assertEqual(weights["face"]["mode"], "constant")

    def test_marigold_depth_overrides_the_table(self):
        depth = {"face": np.full((CANVAS, CANVAS), 0.9, dtype=np.float32)}
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS),
                                depth_dict=depth)
        parts = {part["tag"]: part for part in manifest["parts"]}
        self.assertEqual(manifest["source"]["depth"], "marigold")
        self.assertAlmostEqual(parts["face"]["depth"], 0.9, places=4)

    def test_split_eyes_inherit_their_parent_depth(self):
        depth = {"eyewhite": np.full((CANVAS, CANVAS), 0.4, dtype=np.float32)}
        manifest, _ = build_rig(self.layers, frame_size=(CANVAS, CANVAS),
                                depth_dict=depth)
        parts = {part["tag"]: part for part in manifest["parts"]}
        self.assertAlmostEqual(parts["eyewhitel"]["depth"], 0.4, places=4)
        self.assertAlmostEqual(parts["eyewhiter"]["depth"], 0.4, places=4)

    def test_empty_layers_are_dropped(self):
        layers = dict(self.layers)
        layers["headwear"] = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
        manifest, images = build_rig(layers, frame_size=(CANVAS, CANVAS))
        self.assertNotIn("headwear", {part["tag"] for part in manifest["parts"]})
        self.assertNotIn("headwear", images)

    def test_frame_size_is_inferred_from_the_layers(self):
        manifest, _ = build_rig(self.layers)
        self.assertEqual(manifest["canvas"], {"width": CANVAS, "height": CANVAS})

    def test_frame_size_is_required_when_nothing_has_content(self):
        with self.assertRaises(ValueError):
            build_rig({"face": np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)})


class WriteRigProjectTests(unittest.TestCase):
    def test_writes_manifest_and_images_where_it_says_they_are(self):
        manifest, images = build_rig(portrait_layers(), frame_size=(CANVAS, CANVAS))
        with tempfile.TemporaryDirectory() as out_dir:
            path = write_rig_project(out_dir, "a001", manifest, images)
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as f:
                written = json.load(f)
            for part in written["parts"]:
                self.assertTrue(os.path.isfile(os.path.join(out_dir, part["image"])),
                                part["image"])
