"""Upper-torso soft morph: a local two-lobe deformation field over `topwear`.

See docs/PORTRAIT_AUTORIG_CHEST_SOFT_MORPH_DESIGN_v0.1.md for the design
rationale this module implements. In short: the existing breathing field
already lifts the whole upper body on a continuous vertical ramp and gives
`body` a uniform horizontal widen (`CHEST_WIDEN` in the preview), and both
stay exactly as they are. This module adds one more thing on top -- a small,
garment-local volume response confined to `topwear` -- rather than
generalizing either into something it was not designed for.

Like the rest of `rig.py`, this module only *derives* the region and writes
its geometry into the manifest, under `motion.upper_torso_soft_morph`. The
per-frame deformation itself runs in preview/runtime, exactly as breathing
does (see `deform()` in preview/index.html) -- nothing here touches pixels.

Rest-pose invariance is the one hard constraint carried by every function
here: a rig with this feature on renders byte-identical to one without it
until something actually moves. `derive_*` and `*_preflight` therefore both
take read-only layer data and return plain JSON-safe geometry.

A character this module is unsure about gets *no visible change* rather than
a half-strength guess (design doc 15, 17): `upper_torso_soft_morph_spec`
folds every preflight verdict into `strength`, so DISABLED is strength 0.0
exactly, not a small number the runtime has to know to suppress.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

__all__ = [
    "SOFT_MORPH_TAG", "derive_upper_torso_soft_region", "soft_morph_preflight",
    "upper_torso_soft_morph_spec",
    "RESPONSE_PROFILES", "RESPONSE_PROFILE_CONFIG", "TARGET_ALIASES",
    "find_authored_region", "region_from_rig_intent", "authored_upper_torso_soft_morph_spec",
]

# The garment layer this deforms. Phase 1's scope is `topwear` alone -- see
# the design doc's 5 and 24: no separate breast semantic layer, no splitting
# topwear into more pieces, no touching neck/head/face/hair/eyewhite.
SOFT_MORPH_TAG = "topwear"

# --- Geometry defaults ---------------------------------------------------
#
# Every fraction below is measured against the `topwear` bounding box, not
# the canvas, so the region survives a crop change or a resolution swap
# unchanged (design doc 13). Comments give the doc's suggested authoring
# range; the picked value is its midpoint unless noted.
CHEST_Y_RATIO = 0.36            # 0.30~0.42 of topwear height, down from its top
LOBE_CENTER_OFFSET = 0.185      # +/-, 0.15~0.22 of topwear width from centre
LOBE_RADIUS_X = 0.26            # 0.22~0.30 of topwear width
LOBE_RADIUS_Y = 0.20            # 0.16~0.24 of topwear height
CENTER_LOCK_WIDTH = 0.10        # fraction of topwear width, half-width each side
NECKLINE_LOCK_WIDTH = 0.16      # fraction of topwear height, down from its top

# Conservative starting amplitudes (design doc 4.4, 21): the goal is "it
# breathes", not "how far can this go". Canvas pixels, exactly like
# `motion.breathing.amplitude_px` -- neither field is resolution-normalized.
DEFAULT_HORIZONTAL_PX = 2.0
DEFAULT_VERTICAL_PX = 0.6        # ~30% of horizontal, inside 9.2's 20~40% cap

# --- Preflight thresholds -------------------------------------------------
#
# `MIN_TORSO_HEIGHT_PX` is quoted against a 768px canvas and scaled from
# there, the same way `rig._mesh_cell` scales cell size.
MESH_REFERENCE_SIZE = 768
MIN_TORSO_HEIGHT_PX = 90      # below this a crop is too short to localize a chest band
MIN_COVERAGE_RATIO = 0.55     # region alpha coverage below this reads as a loose/gapped garment
MIN_CONFIDENCE = 0.40         # below this: no visible change is the correct answer


def _alpha_of(img: np.ndarray) -> np.ndarray:
    return np.asarray(img)[..., 3].astype(np.float32)


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    nz = cv2.findNonZero(mask.astype(np.uint8))
    if nz is None:
        return None
    x, y, w, h = cv2.boundingRect(nz)
    return int(x), int(y), int(x + w), int(y + h)


def _visible_top_height(bbox: tuple[int, int, int, int],
                        neck_box: tuple[int, int, int, int] | None) -> tuple[float, float]:
    """Where the *visible* torso actually starts, and how tall it is.

    `topwear`'s own alpha bbox is not a safe height reference on its own:
    `reclaim_occluded` (rig.py) keeps garment pixels underneath the neck and
    head so the head-turn window has something to draw over, which is real
    alpha reaching well above the collar rather than an absent garment.
    Anchoring on the neck's own bottom edge instead is what keeps the chest
    band and its radius sized to the garment that is actually on screen,
    independent of how tall the raw bbox is.
    """
    x1, y1, x2, y2 = bbox
    visible_top = max(float(neck_box[3]), float(y1)) if neck_box is not None else float(y1)
    return visible_top, max(1.0, y2 - visible_top)


def derive_upper_torso_soft_region(topwear: np.ndarray | None, *,
                                   neck_box: tuple[int, int, int, int] | None = None,
                                   alpha_threshold: int = 10,
                                   ) -> dict[str, Any] | None:
    """Two-lobe chest region derived from `topwear` alpha alone (design doc 6).

    Returns part-local-normalized geometry -- `center`/`radius` as fractions
    of the `topwear` bounding box, which is also returned in pixels for
    `soft_morph_preflight` to measure coverage against. None means "not
    applicable" (no topwear present), which the caller reads as DISABLED
    rather than a degraded derivation.
    """
    if topwear is None:
        return None
    alpha = _alpha_of(topwear)
    if not np.any(alpha > alpha_threshold):
        return None
    # The bbox has to be `crop_to_alpha`'s own box (image.py) -- alpha > 0,
    # not > alpha_threshold -- because that is the only box the runtime ever
    # has (the manifest part's own `xyxy`). `alpha_threshold` decides whether
    # the layer is meaningful at all, exactly as it does there; it must not
    # also decide which edge pixels the box includes, or a lobe normalized
    # against a *different*, tighter box here lands somewhere else entirely
    # once the runtime re-expands it against the wider one it actually has.
    box = _bbox(alpha > 0)
    assert box is not None  # the alpha_threshold check above guarantees this
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    if width <= 0 or height <= 0:
        return None

    visible_top, visible_height = _visible_top_height(box, neck_box)
    chest_y = min(visible_top + CHEST_Y_RATIO * visible_height, y2 - 1.0)

    center_x = (x1 + x2) / 2.0
    offset = LOBE_CENTER_OFFSET * width
    rx = LOBE_RADIUS_X * width
    # Scaled off the *visible* torso span, not the raw bbox height: `topwear`
    # alpha legitimately reaches above the collar for `reclaim_occluded`'s
    # turn window (rig.py), hidden behind the neck/head at rest but still
    # real alpha -- sizing the radius off the raw bbox in that case inflates
    # the lobes up over the face instead of keeping them at the chest.
    ry = LOBE_RADIUS_Y * visible_height

    def normalize(x: float, y: float) -> list[float]:
        return [round((x - x1) / width, 4), round((y - y1) / height, 4)]

    radius = [round(rx / width, 4), round(ry / height, 4)]
    # `neckline_lock` is stored the same way as the lobe centres -- an
    # absolute release line, normalized against the raw bbox -- rather than a
    # bare width fraction, so it lands at the same *visible* offset below the
    # neck regardless of how tall the raw bbox is. With no neck to anchor on
    # (visible_top == y1) this reduces to exactly `NECKLINE_LOCK_WIDTH`.
    neckline_release_y = visible_top + NECKLINE_LOCK_WIDTH * visible_height
    neckline_lock = round((neckline_release_y - y1) / height, 4)
    return {
        "mode": "two_lobe",
        "left": {"center": normalize(center_x - offset, chest_y), "radius": radius},
        "right": {"center": normalize(center_x + offset, chest_y), "radius": radius},
        "center_lock": CENTER_LOCK_WIDTH,
        "neckline_lock": neckline_lock,
        "bbox": [x1, y1, x2, y2],
    }


def soft_morph_preflight(topwear: np.ndarray | None, region: dict[str, Any] | None, *,
                         frame_size: tuple[int, int],
                         neck_box: tuple[int, int, int, int] | None = None,
                         occluder_alpha: np.ndarray | None = None,
                         alpha_threshold: int = 10) -> dict[str, Any]:
    """READY / DEGRADED / DISABLED verdict for a derived region (design doc 15).

    Confidence is what the caller scales strength by rather than a bare
    pass/fail: DEGRADED still moves, just less, while DISABLED -- or any
    confidence under `MIN_CONFIDENCE` -- plays no part of the field at all.

    `occluder_alpha`, when given, is the union alpha of whatever else is
    drawn *over* `topwear` at rest (crossed-arm `handwear`, a `neckwear`
    layered on top, ...). A lobe sitting entirely under a static prop like
    that is invisible at rest, but `topwear` still deforms underneath it --
    and since the prop does not move with it, its edge can crack loose from
    the garment right at the seam between them. Coverage is measured on what
    is actually *visible*, not on `topwear`'s alpha alone, so a heavily
    covered lobe degrades instead of silently animating out of sight.
    """
    if topwear is None or region is None:
        reason = "no_topwear" if topwear is None else "no_region"
        return {"status": "DISABLED", "confidence": 0.0, "reasons": [reason]}

    x1, y1, x2, y2 = region["bbox"]
    width, height = x2 - x1, y2 - y1
    scale = max(frame_size) / MESH_REFERENCE_SIZE
    min_height = max(24, int(round(MIN_TORSO_HEIGHT_PX * scale)))
    # Measured on the *visible* span (see `_visible_top_height`): a raw bbox
    # inflated upward by occluded alpha would otherwise mask a garment that
    # barely peeks out below the collar.
    _, visible_height = _visible_top_height(region["bbox"], neck_box)
    if visible_height < min_height:
        return {"status": "DISABLED", "confidence": 0.0, "reasons": ["torso_crop_too_short"]}

    fabric_mask = _alpha_of(topwear) > alpha_threshold
    occluded = (occluder_alpha is not None and np.asarray(occluder_alpha).shape == fabric_mask.shape)
    mask = fabric_mask & ~(np.asarray(occluder_alpha) > alpha_threshold) if occluded else fabric_mask
    ys, xs = np.indices(mask.shape, dtype=np.float32)

    def ellipse_mask(lobe: dict[str, Any]) -> np.ndarray:
        cx = x1 + lobe["center"][0] * width
        cy = y1 + lobe["center"][1] * height
        rx = max(1e-6, lobe["radius"][0] * width)
        ry = max(1e-6, lobe["radius"][1] * height)
        return ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1.0

    region_mask = ellipse_mask(region["left"]) | ellipse_mask(region["right"])
    region_area = int(region_mask.sum())
    if region_area == 0:
        return {"status": "DISABLED", "confidence": 0.0, "reasons": ["empty_region"]}
    coverage_ratio = float((mask & region_mask).sum()) / region_area
    fabric_ratio = float((fabric_mask & region_mask).sum()) / region_area
    # Of the fabric that is actually *there*, how much of it is hidden under
    # something drawn on top -- as opposed to `coverage_ratio`, which also
    # falls for fabric that is simply missing (a loose/gapped garment).
    occlusion_ratio = max(0.0, 1.0 - coverage_ratio / fabric_ratio) if occluded and fabric_ratio > 0 else 0.0

    reasons: list[str] = []
    confidence = coverage_ratio
    if occlusion_ratio > 0.05:
        # A prop drawn *over* topwear at rest does not move with it, so what
        # is missing here is a rigid edge that can crack loose right at the
        # seam -- a sharper risk than an equivalent amount of merely-sparse
        # fabric, so it is penalized on its own even short of
        # `MIN_COVERAGE_RATIO` rather than waiting for that to trip.
        reasons.append("occluded_by_overlay")
        confidence *= max(0.0, 1.0 - occlusion_ratio)
    elif coverage_ratio < MIN_COVERAGE_RATIO:
        # A loose robe or a coat with a wide gap down the front reads as
        # ambiguous local geometry -- exactly the DEGRADED case the design
        # doc calls out, not a hard failure.
        reasons.append("sparse_topwear_geometry")
    if neck_box is not None:
        top_edge = min(y1 + region["left"]["center"][1] * height
                       - region["left"]["radius"][1] * height,
                       y1 + region["right"]["center"][1] * height
                       - region["right"]["radius"][1] * height)
        if top_edge < neck_box[3]:
            reasons.append("neckline_overlap")
            confidence *= 0.7

    status = "READY" if not reasons else "DEGRADED"
    if confidence < MIN_CONFIDENCE:
        status = "DISABLED"
        if "low_confidence" not in reasons:
            reasons.append("low_confidence")

    return {
        "status": status,
        "confidence": round(float(confidence), 3),
        "reasons": reasons,
        "coverage_ratio": round(coverage_ratio, 3),
    }


def upper_torso_soft_morph_spec(layer_dict: dict[str, np.ndarray], *,
                                frame_size: tuple[int, int],
                                neck_box: tuple[int, int, int, int] | None = None,
                                occluder_alpha: np.ndarray | None = None,
                                alpha_threshold: int = 10) -> dict[str, Any]:
    """The full `motion.upper_torso_soft_morph` manifest entry (design doc 13).

    Combines derivation and preflight, then folds the verdict into
    `enabled`/`strength` so the runtime never has to know the preflight
    rules -- it only ever reads a strength, and a DISABLED character's is
    exactly zero.
    """
    topwear = layer_dict.get(SOFT_MORPH_TAG)
    region = derive_upper_torso_soft_region(topwear, neck_box=neck_box,
                                            alpha_threshold=alpha_threshold)
    verdict = soft_morph_preflight(topwear, region, frame_size=frame_size, neck_box=neck_box,
                                   occluder_alpha=occluder_alpha, alpha_threshold=alpha_threshold)

    if verdict["status"] == "DISABLED":
        enabled, strength = False, 0.0
    elif verdict["status"] == "DEGRADED":
        enabled, strength = True, verdict["confidence"]
    else:
        enabled, strength = True, 1.0

    spec: dict[str, Any] = {
        "enabled": enabled,
        "mode": "two_lobe",
        "strength": round(float(strength), 3),
        "horizontal_px": DEFAULT_HORIZONTAL_PX,
        "vertical_px": DEFAULT_VERTICAL_PX,
        "center_lock": (region or {}).get("center_lock", CENTER_LOCK_WIDTH),
        "neckline_lock": (region or {}).get("neckline_lock", NECKLINE_LOCK_WIDTH),
        "confidence": verdict["confidence"],
        "source": "topwear_geometry",
        "status": verdict["status"],
    }
    if verdict.get("reasons"):
        spec["status_reasons"] = verdict["reasons"]
    if region is not None:
        spec["left"] = region["left"]
        spec["right"] = region["right"]
    return spec


# --- Authored region (Assembly Bundle RigIntent, v0.2) ---------------------
#
# Everything above this point is Phase 1's original alpha-guessing path,
# unchanged, and stays the Portrait Bundle fallback (no RigIntent concept
# exists there). `portrait-composer`'s C4 `secondary_regions.py` now
# authors this exact region shape -- geometry/locks/author_strength/
# response_profile/enabled -- so an Assembly Bundle compile must use *that*
# instead of guessing (Master doc #23 invariant #11-12: Composer defines
# WHERE/WHAT/response class, AutoRig computes HOW; "AutoRig가 auto region
# 발명 안 함" once RigIntent exists to author one).

# Composer's own logical label for the same physical surface this module
# already calls `topwear` (Phase 1 scope: single tag, #5/#24 above) --
# `PORTRAIT_COMPOSER_IMPLEMENTATION_DIRECTIVE_v0.2.md` #18 names
# "topwear_with_arms" as its export-profile grouping label for exactly this
# surface. Generalizing beyond one tag is future work.
TARGET_ALIASES = frozenset({"topwear_with_arms", "topwear", SOFT_MORPH_TAG})

RESPONSE_PROFILES = ("soft", "firm_bounce", "springy")

# Directive v0.2 #16's schema-example numeric config, verbatim: AutoRig's
# own data-driven preset per qualitative response_profile ID, never a
# per-character hardcode. Production tuning is separate config/corpus
# calibration -- this is the starting point, not the final word. #17:
# firm_bounce != larger motion -- higher restoring force, shorter lag,
# clear overshoot, faster rebound, smaller sustained wobble; its own
# max_displacement is smaller than soft's, not larger. Not yet consumed by
# any solver (P2); carried on the spec today so the eventual
# UpperTorsoSecondaryDriver has real authored data waiting for it instead
# of another migration.
RESPONSE_PROFILE_CONFIG: dict[str, dict[str, float]] = {
    "soft": {"stiffness": 0.45, "damping": 0.55, "overshoot": 0.20, "max_displacement": 1.00},
    "firm_bounce": {"stiffness": 0.82, "damping": 0.36, "overshoot": 0.42, "max_displacement": 0.72},
    "springy": {"stiffness": 0.64, "damping": 0.24, "overshoot": 0.55, "max_displacement": 0.90},
}


def find_authored_region(rig_intent: dict[str, Any] | None) -> dict[str, Any] | None:
    """The first RigIntent region (enabled or not -- callers decide what to
    do with a disabled one) whose `target` names the surface this module's
    Phase 1 scope can act on. None when there is no `rig_intent` at all, or
    none of its regions target `topwear` -- both cases mean "AutoRig must
    not invent a region" for that compile (see
    `authored_upper_torso_soft_morph_spec`'s caller in `rig.py`), never a
    reason to fall back to `derive_upper_torso_soft_region`'s guess."""
    if not rig_intent:
        return None
    for region in (rig_intent.get("regions") or {}).values():
        if region.get("target") in TARGET_ALIASES:
            return region
    return None


def region_from_rig_intent(topwear: np.ndarray | None, region: dict[str, Any] | None, *,
                           alpha_threshold: int = 10) -> dict[str, Any] | None:
    """The `soft_morph_preflight`-shaped region dict built from a Composer-
    authored RigIntent region -- same shape `derive_upper_torso_soft_region`
    returns (`left`/`right`/`center_lock`/`neckline_lock`/`bbox`), only
    where the center/radius/locks come from differs. `bbox` still comes
    from the actual compiled `topwear` alpha, never from Composer's
    normalized geometry alone -- AutoRig keeps owning geometry/deformation
    *safety* (`soft_morph_preflight` runs unchanged against this), even
    when it no longer owns *where* the lobes are centred.
    """
    if topwear is None or region is None:
        return None
    geometry = region.get("geometry") or {}
    left, right = geometry.get("left"), geometry.get("right")
    if not left or not right:
        return None
    box = _bbox(_alpha_of(topwear) > 0)
    if box is None:
        return None
    locks = region.get("locks") or {}
    return {
        "mode": "two_lobe", "left": left, "right": right,
        "center_lock": locks.get("center", CENTER_LOCK_WIDTH),
        "neckline_lock": locks.get("neckline", NECKLINE_LOCK_WIDTH),
        "bbox": list(box),
    }


def authored_upper_torso_soft_morph_spec(region: dict[str, Any],
                                         layer_dict: dict[str, np.ndarray], *,
                                         frame_size: tuple[int, int],
                                         neck_box: tuple[int, int, int, int] | None = None,
                                         occluder_alpha: np.ndarray | None = None,
                                         alpha_threshold: int = 10) -> dict[str, Any]:
    """The full `motion.upper_torso_soft_morph` manifest entry built from a
    Composer-authored RigIntent region (`find_authored_region`) instead of
    `upper_torso_soft_morph_spec`'s alpha guess. Folds `region["enabled"]`,
    AutoRig's own `soft_morph_preflight` safety verdict, and the author's
    own `author_strength` into `strength` the same way the auto-derived
    path folds preflight confidence alone -- an author-disabled region, a
    preflight DISABLED, or missing geometry/topwear are all exactly
    strength 0.0, never a partial guess.
    """
    topwear = layer_dict.get(SOFT_MORPH_TAG)
    region_geometry = region_from_rig_intent(topwear, region, alpha_threshold=alpha_threshold)
    verdict = soft_morph_preflight(topwear, region_geometry, frame_size=frame_size,
                                   neck_box=neck_box, occluder_alpha=occluder_alpha,
                                   alpha_threshold=alpha_threshold)

    author_enabled = bool(region.get("enabled", True))
    author_strength = float(region.get("author_strength", 0.9))
    if not author_enabled or verdict["status"] == "DISABLED":
        enabled, strength = False, 0.0
    elif verdict["status"] == "DEGRADED":
        enabled, strength = True, verdict["confidence"] * author_strength
    else:
        enabled, strength = True, author_strength

    response_profile = region.get("response_profile", "soft")
    if response_profile not in RESPONSE_PROFILES:
        response_profile = "soft"

    spec: dict[str, Any] = {
        "enabled": enabled,
        "mode": "two_lobe",
        "strength": round(float(strength), 3),
        "horizontal_px": DEFAULT_HORIZONTAL_PX,
        "vertical_px": DEFAULT_VERTICAL_PX,
        "center_lock": (region_geometry or {}).get("center_lock", CENTER_LOCK_WIDTH),
        "neckline_lock": (region_geometry or {}).get("neckline_lock", NECKLINE_LOCK_WIDTH),
        "confidence": verdict["confidence"],
        "source": "assembly_rig_intent",
        "status": verdict["status"] if author_enabled else "DISABLED",
        "response_profile": response_profile,
        "response_config": dict(RESPONSE_PROFILE_CONFIG[response_profile]),
    }
    reasons = list(verdict.get("reasons") or [])
    if not author_enabled:
        reasons = ["author_disabled"] + reasons
    if reasons:
        spec["status_reasons"] = reasons
    if region_geometry is not None:
        spec["left"] = region_geometry["left"]
        spec["right"] = region_geometry["right"]
    return spec
