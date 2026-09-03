import unittest

import numpy as np

from portrait_autorig.image import crop_to_alpha
from portrait_autorig.rig import build_rig, chest_occluder_alpha, rig_preflight
from portrait_autorig.soft_morph import (
    DEFAULT_HORIZONTAL_PX, DEFAULT_VERTICAL_PX, MIN_COVERAGE_RATIO,
    RESPONSE_PROFILE_CONFIG, SOFT_MORPH_TAG,
    authored_upper_torso_soft_morph_spec, derive_upper_torso_soft_region,
    find_authored_region, region_from_rig_intent, soft_morph_preflight,
    upper_torso_soft_morph_spec,
)

CANVAS = 128


def rgba(box, value=255, canvas=CANVAS):
    """Canvas-sized RGBA with `box` -- (x1, y1, x2, y2) -- filled opaque."""
    x1, y1, x2, y2 = box
    img = np.zeros((canvas, canvas, 4), dtype=np.uint8)
    img[y1:y2, x1:x2, :3] = value
    img[y1:y2, x1:x2, 3] = 255
    return img


TOPWEAR_BOX = (36, 72, 92, 124)  # width 56, height 52 -- the test_rig fixture's torso


def portrait_layers():
    """Minimal set that gives `topwear` a neck to clamp against."""
    return {
        "neck": rgba((58, 56, 70, 72)),
        "topwear": rgba(TOPWEAR_BOX),
    }


class DeriveRegionTests(unittest.TestCase):
    def test_no_topwear_returns_none(self):
        self.assertIsNone(derive_upper_torso_soft_region(None))

    def test_region_bbox_matches_topwear_alpha(self):
        region = derive_upper_torso_soft_region(rgba(TOPWEAR_BOX))
        self.assertEqual(tuple(region["bbox"]), TOPWEAR_BOX)

    def test_lobes_are_ordered_left_to_right_and_symmetric(self):
        region = derive_upper_torso_soft_region(rgba(TOPWEAR_BOX))
        self.assertLess(region["left"]["center"][0], region["right"]["center"][0])
        # Symmetric about the part-local centre (0.5) since the box is a
        # centred rectangle.
        left_x, right_x = region["left"]["center"][0], region["right"]["center"][0]
        self.assertAlmostEqual(left_x + right_x, 1.0, places=3)
        self.assertEqual(region["left"]["radius"], region["right"]["radius"])

    def test_geometry_is_normalized_to_the_topwear_box(self):
        """Center/radius must be part-local fractions, not canvas pixels --
        that is what lets the same spec survive a crop change (design doc 13)."""
        region = derive_upper_torso_soft_region(rgba(TOPWEAR_BOX))
        for lobe in (region["left"], region["right"]):
            self.assertTrue(0.0 <= lobe["center"][0] <= 1.0)
            self.assertTrue(0.0 <= lobe["center"][1] <= 1.0)
            self.assertGreater(lobe["radius"][0], 0.0)
            self.assertGreater(lobe["radius"][1], 0.0)

    def test_chest_band_is_clamped_below_the_neckline(self):
        """8.1: the collar seam is the one non-negotiable lock -- the chest
        band must never creep above the bottom of the neck."""
        x1, y1, x2, y2 = TOPWEAR_BOX
        height = y2 - y1
        # A neck reaching almost to the natural chest_y forces the clamp.
        deep_neck_bottom = y1 + int(0.40 * height)
        region = derive_upper_torso_soft_region(
            rgba(TOPWEAR_BOX), neck_box=(58, 20, 70, deep_neck_bottom)
        )
        chest_y = y1 + region["left"]["center"][1] * height
        # `center` is rounded to 4dp before this multiplies it back out, so
        # allow for that quantization rather than requiring bit-exactness.
        self.assertGreaterEqual(chest_y, deep_neck_bottom - 0.01)

    def test_empty_topwear_returns_none(self):
        self.assertIsNone(derive_upper_torso_soft_region(
            np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
        ))

    def test_occluded_alpha_above_the_neck_does_not_inflate_the_region(self):
        """`reclaim_occluded` (rig.py) can leave real `topwear` alpha reaching
        up behind the neck/head for the head-turn window to draw over --
        hidden by z-order at rest, not absent. A raw-bbox-height reference
        blows the region up over the face in that case (this reproduces a
        real A002-shaped run); the neck's own bottom edge does not."""
        topwear = rgba((30, 8, 220, 250), canvas=256)
        neck_box = (108, 96, 148, 118)
        region = derive_upper_torso_soft_region(topwear, neck_box=neck_box)
        x1, y1, x2, y2 = region["bbox"]
        height = y2 - y1
        for side in ("left", "right"):
            cy = y1 + region[side]["center"][1] * height
            ry = region[side]["radius"][1] * height
            self.assertGreaterEqual(cy - ry, neck_box[3])
        neck_lock_y = y1 + region["neckline_lock"] * height
        self.assertGreaterEqual(neck_lock_y, neck_box[3])

    def test_region_bbox_matches_crop_to_alpha_exactly_even_with_faint_bleed(self):
        """The runtime always denormalizes against the manifest part's own
        `xyxy` -- which is `crop_to_alpha`'s box (image.py), alpha > 0, not
        > alpha_threshold. A real A002 run had faint (1-9) antialiasing/
        occlusion-bleed alpha reaching from the collar up behind the head,
        which made a *separately* thresholded bbox here disagree with
        `crop_to_alpha`'s -- the lobes were normalized against one box and
        re-expanded by the runtime against a much taller one, landing the
        whole region up over the face. The two boxes must always agree."""
        x1, y1, x2, y2 = TOPWEAR_BOX
        topwear = rgba(TOPWEAR_BOX)
        # A faint smear far above the meaningful garment -- alpha 5, under
        # the default threshold of 10 -- exactly like antialiasing/occlusion
        # bleed reaching up behind the head.
        topwear[0:y1, x1 + 4:x2 - 4, 3] = 5
        neck_box = (58, 56, 70, 72)

        _, crop_xyxy = crop_to_alpha(topwear)
        region = derive_upper_torso_soft_region(topwear, neck_box=neck_box)
        self.assertEqual(tuple(region["bbox"]), tuple(crop_xyxy))

        bx1, by1, bx2, by2 = region["bbox"]
        height = by2 - by1
        for side in ("left", "right"):
            cy = by1 + region[side]["center"][1] * height
            ry = region[side]["radius"][1] * height
            # Anchored to the *visible* torso below the neck, not smeared up
            # into the faint region above the real garment.
            self.assertGreaterEqual(cy - ry, neck_box[3])
            self.assertLessEqual(cy + ry, y2)

    def test_neckline_lock_matches_the_plain_constant_with_no_neck_anchor(self):
        """With nothing to anchor on, the derived release line must reduce to
        exactly the un-adjusted `NECKLINE_LOCK_WIDTH` constant -- the fix for
        occluded bboxes must not change the ordinary, unoccluded case."""
        from portrait_autorig.soft_morph import NECKLINE_LOCK_WIDTH
        region = derive_upper_torso_soft_region(rgba(TOPWEAR_BOX))
        self.assertAlmostEqual(region["neckline_lock"], NECKLINE_LOCK_WIDTH, places=4)


class PreflightTests(unittest.TestCase):
    def test_missing_topwear_is_disabled(self):
        verdict = soft_morph_preflight(None, None, frame_size=(CANVAS, CANVAS))
        self.assertEqual(verdict["status"], "DISABLED")
        self.assertEqual(verdict["confidence"], 0.0)
        self.assertIn("no_topwear", verdict["reasons"])

    def test_solid_topwear_is_ready_with_full_coverage(self):
        topwear = rgba(TOPWEAR_BOX)
        region = derive_upper_torso_soft_region(topwear)
        verdict = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS))
        self.assertEqual(verdict["status"], "READY")
        self.assertEqual(verdict["coverage_ratio"], 1.0)
        self.assertEqual(verdict["reasons"], [])

    def test_short_torso_crop_is_disabled(self):
        tiny_box = (36, 72, 92, 78)  # 6px tall
        topwear = rgba(tiny_box)
        region = derive_upper_torso_soft_region(topwear)
        verdict = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS))
        self.assertEqual(verdict["status"], "DISABLED")
        self.assertIn("torso_crop_too_short", verdict["reasons"])

    def test_sparse_garment_geometry_degrades_rather_than_fails(self):
        """A loose robe with a gap down the front covers only part of the
        derived ellipses -- ambiguous, not absent (design doc 15)."""
        x1, y1, x2, y2 = TOPWEAR_BOX
        topwear = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
        # Only a thin strip along the very top of the box is opaque; most of
        # the chest band itself is empty.
        topwear[y1:y1 + 3, x1:x2, 3] = 255
        region = derive_upper_torso_soft_region(rgba(TOPWEAR_BOX))
        verdict = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS))
        self.assertIn(verdict["status"], ("DEGRADED", "DISABLED"))
        self.assertIn("sparse_topwear_geometry", verdict["reasons"])

    def test_neckline_overlap_is_flagged_and_penalized(self):
        topwear = rgba(TOPWEAR_BOX)
        region = derive_upper_torso_soft_region(topwear)
        baseline = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS))
        # A neck reaching below the ellipse's own top edge, well past where
        # `derive` would have clamped chest_y to accommodate it.
        x1, y1, x2, y2 = region["bbox"]
        height = y2 - y1
        ellipse_top = y1 + (region["left"]["center"][1] - region["left"]["radius"][1]) * height
        intrusive_neck = (58, 20, 70, int(ellipse_top) + 5)
        overlapped = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS),
                                          neck_box=intrusive_neck)
        self.assertIn("neckline_overlap", overlapped["reasons"])
        self.assertLess(overlapped["confidence"], baseline["confidence"])

    def test_occluding_prop_degrades_even_short_of_the_coverage_floor(self):
        """A004-shaped run: `handwear` (crossed arms) drawn *over* `topwear`
        covers real fabric, not missing fabric -- `topwear` still deforms
        underneath it, and since the static prop does not move with it, its
        edge can crack loose right at their seam. This has to be flagged and
        penalized on its own, even when overall coverage still clears
        `MIN_COVERAGE_RATIO` (unlike a loose/gapped garment, which is fine to
        leave at full strength as long as coverage clears the floor)."""
        topwear = rgba(TOPWEAR_BOX)
        region = derive_upper_torso_soft_region(topwear)
        baseline = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS))
        self.assertEqual(baseline["status"], "READY")

        x1, y1, x2, y2 = region["bbox"]
        height = y2 - y1
        cy = y1 + region["left"]["center"][1] * height
        occluder = np.zeros((CANVAS, CANVAS), dtype=np.uint8)
        # A band crossing roughly a quarter of the ellipse pair's height,
        # like an arm passing over the chest -- not enough to sink overall
        # coverage below MIN_COVERAGE_RATIO on its own.
        band_half = max(1, int(round(height * 0.06)))
        occluder[int(cy) - band_half:int(cy) + band_half, x1:x2] = 255

        verdict = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS),
                                       occluder_alpha=occluder)
        self.assertGreater(verdict["coverage_ratio"], MIN_COVERAGE_RATIO)  # would pass unflagged otherwise
        self.assertEqual(verdict["status"], "DEGRADED")
        self.assertIn("occluded_by_overlay", verdict["reasons"])
        self.assertLess(verdict["confidence"], baseline["confidence"])

    def test_no_occluder_is_unaffected(self):
        """`occluder_alpha=None` -- the default -- must reproduce the
        original, occlusion-unaware verdict exactly."""
        topwear = rgba(TOPWEAR_BOX)
        region = derive_upper_torso_soft_region(topwear)
        with_none = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS),
                                         occluder_alpha=None)
        without_arg = soft_morph_preflight(topwear, region, frame_size=(CANVAS, CANVAS))
        self.assertEqual(with_none, without_arg)


class SpecTests(unittest.TestCase):
    def test_no_topwear_is_disabled_with_zero_strength(self):
        spec = upper_torso_soft_morph_spec({}, frame_size=(CANVAS, CANVAS))
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["strength"], 0.0)
        self.assertEqual(spec["status"], "DISABLED")
        self.assertNotIn("left", spec)

    def test_ready_topwear_is_enabled_at_full_strength(self):
        spec = upper_torso_soft_morph_spec(
            {SOFT_MORPH_TAG: rgba(TOPWEAR_BOX)}, frame_size=(CANVAS, CANVAS)
        )
        self.assertTrue(spec["enabled"])
        self.assertEqual(spec["strength"], 1.0)
        self.assertEqual(spec["status"], "READY")
        self.assertEqual(spec["mode"], "two_lobe")
        self.assertEqual(spec["horizontal_px"], DEFAULT_HORIZONTAL_PX)
        self.assertEqual(spec["vertical_px"], DEFAULT_VERTICAL_PX)
        self.assertIn("left", spec)
        self.assertIn("right", spec)
        self.assertEqual(spec["source"], "topwear_geometry")

    def test_degraded_strength_is_scaled_by_confidence_not_binary(self):
        x1, y1, x2, y2 = TOPWEAR_BOX
        sparse = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
        sparse[y1:y1 + 3, x1:x2, 3] = 255
        spec = upper_torso_soft_morph_spec({SOFT_MORPH_TAG: sparse},
                                           frame_size=(CANVAS, CANVAS))
        if spec["status"] == "DEGRADED":
            self.assertTrue(spec["enabled"])
            self.assertGreater(spec["strength"], 0.0)
            self.assertLess(spec["strength"], 1.0)
        else:
            # Coverage this sparse can also legitimately fall under the
            # confidence floor straight to DISABLED -- either is a pass as
            # long as it is never a full-strength guess.
            self.assertEqual(spec["status"], "DISABLED")
            self.assertEqual(spec["strength"], 0.0)


class BuildRigIntegrationTests(unittest.TestCase):
    def test_manifest_carries_a_derived_soft_morph_spec(self):
        manifest, _ = build_rig(portrait_layers(), frame_size=(CANVAS, CANVAS))
        spec = manifest["motion"]["upper_torso_soft_morph"]
        self.assertTrue(spec["enabled"])
        self.assertEqual(spec["status"], "READY")
        self.assertIn("left", spec)

    def test_rest_pose_is_unaffected_by_the_derived_spec(self):
        """20.A: the field is derived and recorded, never applied here -- the
        rig's own rest_fidelity check must still pass exactly as before."""
        manifest, _ = build_rig(portrait_layers(), frame_size=(CANVAS, CANVAS))
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")

    def test_no_topwear_layer_disables_the_field(self):
        layers = {"neck": rgba((58, 56, 70, 72))}
        manifest, _ = build_rig(layers, frame_size=(CANVAS, CANVAS))
        spec = manifest["motion"]["upper_torso_soft_morph"]
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["strength"], 0.0)
        self.assertEqual(spec["status"], "DISABLED")

    def test_a_caller_supplied_motion_block_is_not_overwritten(self):
        custom = {
            "head_turn": {"max_x": 0.8, "max_y": 0.8},
            "head_tilt": {"max_deg": 2.0, "pivot": "neck_pivot"},
            "breathing": {"period_s": 4.0, "amplitude_px": 3.0},
            "blink": {"close_s": 0.08, "hold_s": 0.34, "open_s": 0.16,
                     "interval_s": [1.6, 5.4], "lid_ratio": 0.85, "lid_thickness": 0.18},
            "upper_torso_soft_morph": {"enabled": False, "mode": "two_lobe",
                                       "strength": 0.0, "source": "hand_authored"},
        }
        manifest, _ = build_rig(portrait_layers(), frame_size=(CANVAS, CANVAS), motion=custom)
        self.assertEqual(manifest["motion"]["upper_torso_soft_morph"],
                         custom["upper_torso_soft_morph"])

    def test_handwear_drawn_over_the_chest_degrades_the_manifest_entry(self):
        """Reproduces the reported A004 case: `handwear` (crossed arms) sits
        over `topwear` in the canonical z-order and overlaps the derived
        region -- the manifest has to come out DEGRADED with a reason, not
        silently READY at full strength."""
        layers = dict(portrait_layers())
        x1, y1, x2, y2 = TOPWEAR_BOX
        # A band across the middle of the torso, like crossed arms/gloves
        # resting over the chest -- enough to degrade, not so much that it
        # also trips the separate low-confidence -> DISABLED floor.
        band_top = y1 + int(round((y2 - y1) * 0.45))
        band_bottom = y1 + int(round((y2 - y1) * 0.55))
        layers["handwear"] = rgba((x1, band_top, x2, band_bottom))
        manifest, _ = build_rig(layers, frame_size=(CANVAS, CANVAS))
        spec = manifest["motion"]["upper_torso_soft_morph"]
        self.assertEqual(spec["status"], "DEGRADED")
        self.assertIn("occluded_by_overlay", spec["status_reasons"])
        self.assertLess(spec["strength"], 1.0)
        self.assertGreater(spec["strength"], 0.0)
        # The occluder must never change what actually renders at rest.
        self.assertEqual(manifest["rest_fidelity"]["status"], "pass")

    def test_a_prop_drawn_before_topwear_is_not_treated_as_an_occluder(self):
        """`objects`/`bottomwear`/etc. sit *behind* `topwear` in the
        canonical z-order (semantic.py) -- overlapping alpha there is
        already hidden by `topwear` itself and is not a moving-edge risk."""
        layers = dict(portrait_layers())
        x1, y1, x2, y2 = TOPWEAR_BOX
        layers["bottomwear"] = rgba((x1, y1, x2, y2))
        manifest, _ = build_rig(layers, frame_size=(CANVAS, CANVAS))
        spec = manifest["motion"]["upper_torso_soft_morph"]
        self.assertEqual(spec["status"], "READY")
        self.assertNotIn("status_reasons", spec)


class ChestOccluderAlphaTests(unittest.TestCase):
    def test_no_occluding_tags_returns_none(self):
        self.assertIsNone(chest_occluder_alpha(portrait_layers()))

    def test_a_tag_drawn_after_topwear_is_picked_up(self):
        layers = dict(portrait_layers())
        x1, y1, x2, y2 = TOPWEAR_BOX
        layers["handwear"] = rgba((x1, y1, x2, y2))
        occluder = chest_occluder_alpha(layers)
        self.assertIsNotNone(occluder)
        self.assertTrue((occluder[y1:y2, x1:x2] > 0).all())

    def test_a_tag_drawn_before_topwear_is_excluded(self):
        layers = dict(portrait_layers())
        layers["bottomwear"] = rgba(TOPWEAR_BOX)
        self.assertIsNone(chest_occluder_alpha(layers))


def authored_region(**overrides):
    """The exact shape `portrait_composer.secondary_regions.add_upper_
    torso_secondary` authors -- verified against real Composer output."""
    region = {
        "target": "topwear",
        "geometry": {"kind": "two_lobe",
                    "left": {"center": [0.39, 0.36], "radius": [0.24, 0.20]},
                    "right": {"center": [0.61, 0.36], "radius": [0.24, 0.20]}},
        "locks": {"center": 0.10, "neckline": 0.16, "shoulder": 0.08},
        "exclusions": [],
        "author_strength": 0.85,
        "response_profile": "firm_bounce",
        "enabled": True,
    }
    region.update(overrides)
    return region


class FindAuthoredRegionTests(unittest.TestCase):
    def test_none_rig_intent_returns_none(self):
        self.assertIsNone(find_authored_region(None))

    def test_empty_rig_intent_returns_none(self):
        self.assertIsNone(find_authored_region({}))

    def test_finds_a_region_targeting_topwear(self):
        rig_intent = {"regions": {"upper_torso_secondary": authored_region()}}
        self.assertEqual(find_authored_region(rig_intent), authored_region())

    def test_finds_a_region_targeting_the_topwear_with_arms_alias(self):
        rig_intent = {"regions": {"x": authored_region(target="topwear_with_arms")}}
        self.assertIsNotNone(find_authored_region(rig_intent))

    def test_a_region_targeting_something_else_is_ignored(self):
        rig_intent = {"regions": {"x": authored_region(target="handwear")}}
        self.assertIsNone(find_authored_region(rig_intent))

    def test_a_disabled_region_is_still_found(self):
        # Callers decide what a disabled region means; resolution itself
        # does not filter on enabled.
        rig_intent = {"regions": {"x": authored_region(enabled=False)}}
        self.assertIsNotNone(find_authored_region(rig_intent))


class RegionFromRigIntentTests(unittest.TestCase):
    def test_builds_the_preflight_shaped_region(self):
        region = region_from_rig_intent(rgba(TOPWEAR_BOX), authored_region())
        self.assertEqual(region["mode"], "two_lobe")
        self.assertEqual(region["left"], authored_region()["geometry"]["left"])
        self.assertEqual(region["right"], authored_region()["geometry"]["right"])
        self.assertEqual(region["center_lock"], 0.10)
        self.assertEqual(region["neckline_lock"], 0.16)
        self.assertEqual(tuple(region["bbox"]), TOPWEAR_BOX)

    def test_bbox_comes_from_the_real_alpha_not_the_authored_geometry(self):
        # Composer's geometry never carries a bbox; AutoRig keeps deciding
        # that from the actual compiled art (its own geometry safety).
        smaller_box = (40, 80, 80, 110)
        region = region_from_rig_intent(rgba(smaller_box), authored_region())
        self.assertEqual(tuple(region["bbox"]), smaller_box)

    def test_none_topwear_returns_none(self):
        self.assertIsNone(region_from_rig_intent(None, authored_region()))

    def test_none_region_returns_none(self):
        self.assertIsNone(region_from_rig_intent(rgba(TOPWEAR_BOX), None))

    def test_missing_geometry_returns_none(self):
        broken = authored_region(geometry={})
        self.assertIsNone(region_from_rig_intent(rgba(TOPWEAR_BOX), broken))


class AuthoredUpperTorsoSoftMorphSpecTests(unittest.TestCase):
    def test_ready_region_is_enabled_at_author_strength(self):
        layers = portrait_layers()
        spec = authored_upper_torso_soft_morph_spec(
            authored_region(), layers, frame_size=(CANVAS, CANVAS))
        self.assertTrue(spec["enabled"])
        self.assertEqual(spec["status"], "READY")
        self.assertAlmostEqual(spec["strength"], 0.85, places=3)
        self.assertEqual(spec["source"], "assembly_rig_intent")

    def test_author_disabled_is_always_strength_zero_even_if_geometry_is_ready(self):
        layers = portrait_layers()
        spec = authored_upper_torso_soft_morph_spec(
            authored_region(enabled=False), layers, frame_size=(CANVAS, CANVAS))
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["strength"], 0.0)
        self.assertEqual(spec["status"], "DISABLED")
        self.assertIn("author_disabled", spec["status_reasons"])

    def test_preflight_disabled_overrides_an_enabled_author(self):
        # AutoRig's own safety check still governs even when the author
        # said enabled=True -- geometry/deformation safety is not
        # Composer's to override.
        spec = authored_upper_torso_soft_morph_spec(
            authored_region(), {"topwear": rgba((36, 72, 92, 78))},  # 6px tall: too short
            frame_size=(CANVAS, CANVAS))
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["strength"], 0.0)
        self.assertEqual(spec["status"], "DISABLED")

    def test_response_profile_and_config_are_carried_through(self):
        for profile in ("soft", "firm_bounce", "springy"):
            spec = authored_upper_torso_soft_morph_spec(
                authored_region(response_profile=profile), portrait_layers(),
                frame_size=(CANVAS, CANVAS))
            self.assertEqual(spec["response_profile"], profile)
            self.assertEqual(spec["response_config"], RESPONSE_PROFILE_CONFIG[profile])

    def test_unknown_response_profile_falls_back_to_soft(self):
        spec = authored_upper_torso_soft_morph_spec(
            authored_region(response_profile="not_a_real_profile"), portrait_layers(),
            frame_size=(CANVAS, CANVAS))
        self.assertEqual(spec["response_profile"], "soft")
        self.assertEqual(spec["response_config"], RESPONSE_PROFILE_CONFIG["soft"])

    def test_firm_bounce_max_displacement_is_smaller_than_soft(self):
        # Absorption plan #17 / directive #17: firm_bounce != larger motion.
        self.assertLess(RESPONSE_PROFILE_CONFIG["firm_bounce"]["max_displacement"],
                        RESPONSE_PROFILE_CONFIG["soft"]["max_displacement"])


class RigPreflightAuthoredRegionTests(unittest.TestCase):
    """rig.rig_preflight's own upper_torso_soft_morph check, not just the
    soft_morph.py functions it calls."""

    def _layers(self):
        return {
            "head": rgba((10, 10, 90, 90)),
            "face": rgba((20, 20, 80, 80)),
            "neck": rgba((58, 56, 70, 72)),
            "topwear": rgba(TOPWEAR_BOX),
        }

    def test_no_rig_intent_uses_the_auto_derived_guess(self):
        preflight = rig_preflight(self._layers())
        self.assertEqual(preflight["checks"]["upper_torso_soft_morph"]["status"], "READY")

    def test_rig_intent_with_a_matching_region_uses_it(self):
        rig_intent = {"regions": {"upper_torso_secondary": authored_region()}}
        preflight = rig_preflight(self._layers(), rig_intent=rig_intent)
        self.assertEqual(preflight["checks"]["upper_torso_soft_morph"]["status"], "READY")

    def test_rig_intent_present_but_no_matching_region_is_disabled_not_guessed(self):
        # Master doc invariant #11: an Assembly Bundle whose author did not
        # author a region must not fall back to the auto-derived guess.
        preflight = rig_preflight(self._layers(), rig_intent={})
        self.assertEqual(preflight["checks"]["upper_torso_soft_morph"]["status"], "DISABLED")
        self.assertIn("no_region", preflight["checks"]["upper_torso_soft_morph"]["reasons"])


class BuildRigAuthoredRegionTests(unittest.TestCase):
    def _layers(self):
        return {
            "head": rgba((10, 10, 90, 90)),
            "face": rgba((20, 20, 80, 80)),
            "neck": rgba((58, 56, 70, 72)),
            "topwear": rgba(TOPWEAR_BOX),
        }

    def test_rig_intent_none_keeps_the_auto_derived_path(self):
        manifest, _ = build_rig(self._layers(), frame_size=(CANVAS, CANVAS))
        spec = manifest["motion"]["upper_torso_soft_morph"]
        self.assertEqual(spec["source"], "topwear_geometry")

    def test_rig_intent_with_authored_region_drives_the_spec(self):
        rig_intent = {"regions": {"upper_torso_secondary": authored_region()}}
        manifest, _ = build_rig(self._layers(), frame_size=(CANVAS, CANVAS), rig_intent=rig_intent)
        spec = manifest["motion"]["upper_torso_soft_morph"]
        self.assertEqual(spec["source"], "assembly_rig_intent")
        self.assertEqual(spec["response_profile"], "firm_bounce")
        self.assertTrue(spec["enabled"])
        self.assertEqual(manifest["capabilities"]["upper_torso_secondary"], "ready")

    def test_rig_intent_given_but_no_region_authored_disables_rather_than_guesses(self):
        manifest, _ = build_rig(self._layers(), frame_size=(CANVAS, CANVAS), rig_intent={})
        spec = manifest["motion"]["upper_torso_soft_morph"]
        self.assertEqual(spec["source"], "assembly_rig_intent")
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["status"], "DISABLED")
        self.assertEqual(manifest["capabilities"]["upper_torso_secondary"], "disabled")
