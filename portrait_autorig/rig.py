"""Compile production-ready portrait layers into pseudo-2.5D rig parts.

Input layers are already repaired by the Portrait Bundle producer. This module
only derives motion-specific subdivisions, anchors, depth, meshes, and weights.
"""

from __future__ import annotations

import json
import os
from collections.abc import Collection, Sequence
from typing import Any

import cv2
import numpy as np
from PIL import Image

from . import soft_morph
from .capability import capability_report
from .image import composite_layers, crop_to_alpha, rest_fidelity
from .manifest import (
    RIG_MANIFEST_VERSION_01, physics_deformer_entries,
    upgrade_manifest_v01_to_v02,
)
from .mesh import contour_mesh_spec, mesh_spec, motion_aware_mesh_spec
from .strand_topology import build_strand_specs
from .constraints import boundary_stitch_spec, compile_clip_masks
from .physics import validate_physics_spec
from .semantic import SEMANTIC_Z_ORDER
from .topology import mesh_topology_hash
from .variant import _part_name, compile_variant_bindings, visible_variant_members

__all__ = [
    "GROUP_HEAD", "GROUP_NECK", "GROUP_BODY",
    "HEAD_REMAINDER", "NECK_REMAINDER", "BODY_REMAINDER",
    "EYE_SPLIT_TAGS", "RIG_Z_ORDER", "group_for_tag", "depth_owner_for_tag",
    "depth_table",
    "split_remainder", "split_eyes", "derive_missing_eyewhite",
    "rig_preflight", "detect_anchors", "detect_variant_eye_metadata",
    "render_rig_rest", "build_rig",
    "write_rig_project",
]

GROUP_HEAD = "head"
GROUP_NECK = "neck"
GROUP_BODY = "body"

HEAD_REMAINDER = "head_remainder"
NECK_REMAINDER = "neck_remainder"
BODY_REMAINDER = "body_remainder"

# Group membership is a table over the known tag vocabulary rather than the
# centroid heuristic a PSD-based rigger has to fall back on: Portrait Mode's
# tags are fixed by the model's `tag_version`, so guessing is never necessary.
# Both the v2 and v3 spellings are listed (see `layers.VALID_BODY_PARTS_*`).
HEAD_TAGS = frozenset({
    "back hair", "front hair", "hair", "hairb", "hairf",
    "head", "headwear", "face",
    "ears", "earl", "earr", "earwear",
    "eyewhite", "eyewhitel", "eyewhiter",
    "irides", "iridesl", "iridesr",
    "eyebrow", "eyebrowl", "eyebrowr", "browl", "browr",
    "eyelash", "eyelashl", "eyelashr",
    "eyes", "eyel", "eyer", "eyewear",
    "nose", "mouth", "mouth_open", "mouth_closed", "eye_closed",
    HEAD_REMAINDER,
})
NECK_TAGS = frozenset({"neck", "neckwear", NECK_REMAINDER})

# v3 packs both eyes into one layer per feature, so a rig that wants to blink
# or wink has to separate them itself. `eyes` is the v2 spelling of the same
# problem. The `l`/`r` suffixes match the names `DEFAULT_SPINE_NAMES` already
# knows, so a later Spine export maps them for free.
EYE_SPLIT_TAGS = ("eyewhite", "irides", "eyelash", "eyebrow", "eyes")
EYEWHITE_TAGS = frozenset({"eyewhite", "eyewhitel", "eyewhiter"})

# Head-follow weights. Starting values, expected to move once the preview
# exists -- see the feasibility doc's open risk on `back hair`.
HEAD_WEIGHT = 1.00
BODY_WEIGHT = 0.16

# The neck bridges the head and the body, so its gradient has to *end* on their
# weights exactly. These are not free parameters: a borrowed 0.55 at the top
# against a head at 1.00 put a 0.45 discontinuity right at the jaw, and with
# only the top quarter of the neck visible above a stand collar, the head
# visibly slid off a neck moving at half its speed.
NECK_TOP_WEIGHT = HEAD_WEIGHT
NECK_BOTTOM_WEIGHT = BODY_WEIGHT

# A stand collar (a gakuran, a turtleneck) touches the jaw, so leaving it fully
# rigid while the head tilts reads as the chin cutting into it. A garment whose
# top edge overlaps the neck therefore takes **the neck's own weight function**
# over that overlap, rather than a ramp of its own.
#
# That is not a stylistic choice. `reclaim_occluded` cuts a window in the
# garment for the neck to show through, so the window and its contents are two
# sides of one seam: give them different weights and the window's edge slices
# the neck as the head turns. An independent collar constant of 0.45 against a
# neck at 0.571 on the collar line opened a 2.05 px crack there; sharing the
# function leaves only what the two parts' different depths contribute, 0.43 px.
#
# Below the neck the gradient has already reached BODY_WEIGHT, so the rest of
# the garment is unaffected.
COLLAR_TAGS = frozenset({"topwear", "neckwear"})

# The head rotates about a point near the *bottom* of the neck, which is what
# makes a tilt read as a neck bending rather than a head sliding sideways.
NECK_PIVOT_RATIO = 0.85

# Mesh cell sizing now lives in mesh.py. `MANIFEST_VERSION` is the version
# this module's own Stage A-D construction below still builds (v0.1 shape,
# byte-for-byte unchanged); `build_rig` upgrades that to v0.2 via
# `manifest.upgrade_manifest_v01_to_v02` immediately before returning, so the
# upgrade path is exercised by every caller rather than being opt-in.
MANIFEST_VERSION = RIG_MANIFEST_VERSION_01
RIG_SUBDIR = "rig"

# `max_x` is measured, not chosen. Sweeping the turn on A-001 and counting the
# largest contiguous region where hair-dark pixels became skin-light -- the
# parallax sliding the hair off the head it used to cover -- the reveal stays
# scattered up to 0.8 (839 px) and merges into one visible gash by 1.0
# (2095 px). See the feasibility doc's H1 note.
DEFAULT_MOTION: dict[str, Any] = {
    "head_turn": {"max_x": 0.8, "max_y": 0.8},
    "head_tilt": {"max_deg": 2.0, "pivot": "neck_pivot"},
    "breathing": {"period_s": 4.0, "amplitude_px": 3.0},
    #  places the closed lid inside the eye opening: 1.0 is the
    # lower lid, 0.5 the centre. Closing onto the centre leaves the lash as a
    # bar floating in the socket with skin above and below, which reads as a
    # squint; a real lid comes down onto the lower one.
    "blink": {"close_s": 0.08, "hold_s": 0.34, "open_s": 0.16,
              "interval_s": [1.6, 5.4], "lid_ratio": 0.85, "lid_thickness": 0.18},
    # Conservative eye-ball travel.  This is a normalized local range; the
    # runtime clamps it to each eye opening so it cannot escape the socket.
    "gaze": {"max_x": 0.22, "max_y": 0.14, "safe_margin": 0.08},
}


def _rig_z_order() -> tuple[str, ...]:
    """`SEMANTIC_Z_ORDER` with the two new remainder regions inserted.

    Remainder subdivision changes motion ownership, never setup visibility.
    All three pieces therefore stay at the canonical remainder plane behind
    every semantic layer. Their group/weight/depth may differ during motion,
    but a pixel hidden in the producer composite remains hidden at rest.
    """
    order = list(SEMANTIC_Z_ORDER)
    insert_at = order.index(BODY_REMAINDER) + 1
    order[insert_at:insert_at] = [HEAD_REMAINDER, NECK_REMAINDER]
    return tuple(order)


RIG_Z_ORDER: tuple[str, ...] = _rig_z_order()


def group_for_tag(tag: str) -> str:
    """Which movement group a tag belongs to. Unknown tags fall to `body`,
    the conservative choice: a mystery layer that fails to follow the head is
    a missed opportunity, while one that follows it can tear off the torso."""
    if tag in HEAD_TAGS:
        return GROUP_HEAD
    if tag in NECK_TAGS:
        return GROUP_NECK
    return GROUP_BODY


def depth_owner_for_tag(tag: str) -> str:
    """Return the semantic depth plane for Composer expression donors.

    Variant labels such as ``eye_closed`` and ``mouth_open`` are visual
    states, not new motion surfaces. They must share the depth of the eye or
    mouth they replace, otherwise idle head motion makes the donor lag behind
    the face even though its group is correctly ``head``.
    """
    if tag.startswith("eye_") or tag in {"eyes_open", "eyes_closed"}:
        return "eyewhite"
    if tag.startswith("mouth_"):
        return "mouth"
    return tag


def depth_table() -> dict[str, float]:
    """Per-tag parallax depth, 0 near to 1 far, read straight off the
    canonical back-to-front order.

    This is the default depth source. Marigold is an override, not a
    prerequisite: parallax needs the layers' *relative* order, which the tag
    vocabulary already fixes, and estimating it costs a 3 GB model plus a pass
    per run (see `depth.estimate_layer_depths`).
    """
    last = len(SEMANTIC_Z_ORDER) - 1
    table = {tag: round(1.0 - i / last, 4)
             for i, tag in enumerate(SEMANTIC_Z_ORDER)}
    # Draw order and motion depth are intentionally independent. Remainder
    # pieces stay behind everything at rest while following their semantic
    # owner under head/neck motion.
    table[HEAD_REMAINDER] = table["head"]
    table[NECK_REMAINDER] = table["neck"]
    return table


_DEPTH_TABLE = depth_table()
# Unknown tags sit at the back, matching how `spine.semantic_rank` ranks them.
UNKNOWN_DEPTH = 1.0


def _alpha_of(img: np.ndarray) -> np.ndarray:
    return np.asarray(img)[..., 3]


def _mask_of(img: np.ndarray, alpha_threshold: int) -> np.ndarray:
    return _alpha_of(img) > alpha_threshold


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """`(x1, y1, x2, y2)` around the True pixels, or None when there are none."""
    nz = cv2.findNonZero(mask.astype(np.uint8))
    if nz is None:
        return None
    x, y, w, h = cv2.boundingRect(nz)
    return int(x), int(y), int(x + w), int(y + h)


def _centroid(alpha: np.ndarray, alpha_threshold: int) -> tuple[float, float] | None:
    """Alpha-weighted centre of a layer, or None when it is empty. Weighting by
    alpha rather than by the binary mask keeps soft edges from pulling the
    centre outward, which matters for small parts like `irides`."""
    a = np.asarray(alpha, dtype=np.float32)
    a = np.where(a > alpha_threshold, a, 0.0)
    total = float(a.sum())
    if total <= 0.0:
        return None
    ys, xs = np.indices(a.shape, dtype=np.float32)
    return float((xs * a).sum() / total), float((ys * a).sum() / total)


def _union_alpha(layer_dict: dict[str, np.ndarray], tags: Collection[str],
                 alpha_threshold: int) -> np.ndarray | None:
    """Binary union of the named layers' alpha, or None when none are present."""
    out: np.ndarray | None = None
    for tag in tags:
        img = layer_dict.get(tag)
        if img is None:
            continue
        mask = _mask_of(img, alpha_threshold)
        out = mask if out is None else (out | mask)
    return out


def _group_tags(layer_dict: dict[str, np.ndarray], group: str) -> list[str]:
    return [tag for tag in layer_dict if group_for_tag(tag) == group]


def _rgba_with_alpha(source_rgba: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    out = np.array(source_rgba, dtype=np.uint8, copy=True)
    out[..., 3] = np.rint(np.clip(alpha, 0, 255)).astype(np.uint8)
    return out


def _distance_to(mask: np.ndarray) -> np.ndarray:
    """Per-pixel distance to the nearest True pixel of `mask`.

    `distanceTransform` measures distance to the nearest *zero*, so the mask is
    inverted on the way in.
    """
    return cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 3)


def split_remainder(remainder_rgba: np.ndarray, layer_dict: dict[str, np.ndarray], *,
                    alpha_threshold: int = 10) -> dict[str, np.ndarray]:
    """Partition the Silhouette Guard's recovered pixels into head, neck, and
    body regions, returned as full-canvas RGBA under the three remainder tags.
    Empty regions are omitted.

    A single canvas-wide `body_remainder` pinned to the torso is what leaves a
    ghost head silhouette behind when the head moves: the recovered pixels
    *around* the head stay put. Splitting by region lets each piece move with
    whatever it was recovered from.

    The split is by **nearest owner**, not by bounding box. Hair falling across
    a shoulder then divides along the actual boundary between the head and body
    layers instead of at an arbitrary horizontal cut. Neck ownership needs
    stronger evidence than merely landing inside the neck's rectangle: a
    connected candidate must be closest to the neck semantic, contact its
    actual alpha, and have enough contact support for the neck's scale. Failed
    neck candidates remain recoverable and fall through to head/body ownership.

    Note that this is a rig concern only. The Silhouette Guard's scoring and
    the portrait report keep seeing the single undivided remainder, so nothing
    about the verdict changes.
    """
    remainder = np.asarray(remainder_rgba)
    if remainder.ndim != 3 or remainder.shape[-1] != 4:
        raise ValueError(f"remainder must be HxWx4, got {remainder.shape}")
    alpha = remainder[..., 3].astype(np.float32)
    all_coverage = alpha > 0
    live = alpha > alpha_threshold
    if not np.any(all_coverage):
        return {}
    if not np.any(live):
        # A fully feathered remainder still contributes to the canonical rest
        # image. Keep it at the canonical back plane rather than losing alpha
        # solely because ownership evidence is too weak.
        return {BODY_REMAINDER: _rgba_with_alpha(remainder, alpha)}

    head_union = _union_alpha(layer_dict, _group_tags(layer_dict, GROUP_HEAD), alpha_threshold)
    body_union = _union_alpha(layer_dict, _group_tags(layer_dict, GROUP_BODY), alpha_threshold)
    neck_union = _union_alpha(layer_dict, _group_tags(layer_dict, GROUP_NECK), alpha_threshold)

    remaining = live.copy()
    have_head = head_union is not None and bool(head_union.any())
    have_body = body_union is not None and bool(body_union.any())
    have_neck = neck_union is not None and bool(neck_union.any())

    if have_neck:
        canvas_scale = max(live.shape) / 512.0
        contact_px = max(1, int(round(canvas_scale)))
        kernel = np.ones((2 * contact_px + 1, 2 * contact_px + 1), np.uint8)
        neck_contact = cv2.dilate(neck_union.astype(np.uint8), kernel).astype(bool)
        neck_distance = _distance_to(neck_union)
        head_distance = (_distance_to(head_union) if have_head
                         else np.full(live.shape, np.inf, np.float32))
        body_distance = (_distance_to(body_union) if have_body
                         else np.full(live.shape, np.inf, np.float32))
        neck_nearest = live & (neck_distance <= head_distance) & (neck_distance <= body_distance)

        # Connected ownership evidence is deliberately scaled from the actual
        # neck semantic rather than the canvas. A002's three-pixel residue has
        # neither the contact span nor the component support to pass, while a
        # real recovered neck patch remains comfortably above both bars.
        neck_box = _bbox(neck_union)
        assert neck_box is not None
        neck_short_side = min(neck_box[2] - neck_box[0], neck_box[3] - neck_box[1])
        min_contact = max(4, int(round(neck_short_side * 0.04)))
        min_component = max(8, min_contact * 2)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            neck_nearest.astype(np.uint8), 8
        )
        neck_part = np.zeros_like(live)
        for label in range(1, count):
            component = labels == label
            area = int(stats[label, cv2.CC_STAT_AREA])
            contact = int((component & neck_contact).sum())
            contact_ratio = contact / max(area, 1)
            if area < min_component or contact < min_contact or contact_ratio < 0.25:
                continue
            neck_part |= component
        if np.any(neck_part):
            remaining &= ~neck_part
    else:
        neck_part = np.zeros_like(live)

    if np.any(remaining) and have_head and have_body:
        head_part = remaining & (_distance_to(head_union) <= _distance_to(body_union))
    elif np.any(remaining) and have_head:
        head_part = remaining.copy()
    else:
        head_part = np.zeros_like(remaining)
    body_part = remaining & ~head_part

    # Ownership is decided on meaningful alpha, then extended to every faint
    # antialiased edge pixel by nearest connected owner. This is what makes
    # crop/subdivision lossless at rest instead of shaving alpha <= threshold.
    owner_masks = {
        NECK_REMAINDER: neck_part,
        HEAD_REMAINDER: head_part,
        BODY_REMAINDER: body_part,
    }
    faint = all_coverage & ~live
    populated = [(tag, mask) for tag, mask in owner_masks.items() if np.any(mask)]
    if np.any(faint):
        if not populated:
            owner_masks[BODY_REMAINDER] |= faint
        else:
            distances = np.stack([_distance_to(mask) for _, mask in populated], axis=0)
            nearest = np.argmin(distances, axis=0)
            for index, (tag, _) in enumerate(populated):
                owner_masks[tag] |= faint & (nearest == index)

    regions: dict[str, np.ndarray] = {}
    for tag, mask in owner_masks.items():
        if np.any(mask):
            regions[tag] = _rgba_with_alpha(remainder, alpha * mask)
    return regions


def split_eyes(layer_dict: dict[str, np.ndarray], face_center_x: float, *,
               tags: Collection[str] = EYE_SPLIT_TAGS, alpha_threshold: int = 10,
               min_area_ratio: float = 0.05, dilate_px: int = 2) -> dict[str, np.ndarray]:
    """Split each both-eyes-in-one-layer tag into `{tag}l` / `{tag}r`.

    Connected components on the layer's alpha, small ones discarded as noise,
    each remaining component assigned by its centroid X against the face
    centre. No face-detection model: at portrait framing the two eyes are
    reliably separate components on opposite sides of the face centre, and a
    detector would be a second model download to answer a question the alpha
    already answers.

    `l`/`r` are **image** left and right, not the character's -- the same sense
    `DEFAULT_SPINE_NAMES` uses.

    Returns only the tags that actually split into both sides; a tag that
    yields components on one side only is left alone for the caller to keep
    whole, which is the right outcome for a three-quarter view or a layer where
    one eye is occluded.
    """
    out: dict[str, np.ndarray] = {}
    kernel = np.ones((2 * dilate_px + 1, 2 * dilate_px + 1), np.uint8) if dilate_px > 0 else None

    for tag in tags:
        img = layer_dict.get(tag)
        if img is None:
            continue
        arr = np.asarray(img)
        alpha = arr[..., 3].astype(np.float32)
        mask = (alpha > alpha_threshold).astype(np.uint8)
        if not mask.any():
            continue

        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        if count <= 2:  # background plus at most one blob: nothing to split
            continue
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep_area = float(areas.max()) * min_area_ratio
        left = np.zeros(mask.shape, dtype=bool)
        right = np.zeros(mask.shape, dtype=bool)
        for label in range(1, count):
            if float(stats[label, cv2.CC_STAT_AREA]) < keep_area:
                continue
            side = left if float(centroids[label][0]) < face_center_x else right
            side |= labels == label
        if not left.any() or not right.any():
            continue

        # Keep faint anti-aliased edge pixels as well.  The connected
        # components above intentionally use `alpha_threshold` for stable
        # feature detection, but dropping alpha <= threshold changes the
        # Composer reference at rest (A002 has such pixels around eyebrow
        # features). Assign each faint pixel to its nearest detected side so
        # the two outputs remain disjoint and collectively preserve alpha.
        faint = (alpha > 0) & ~(mask > 0)
        if faint.any():
            distances = np.stack([_distance_to(left), _distance_to(right)], axis=0)
            nearest = np.argmin(distances, axis=0)
            left |= faint & (nearest == 0)
            right |= faint & (nearest == 1)

        for suffix, side in (("l", left), ("r", right)):
            side_mask = side
            if kernel is not None:
                # Dilate, then intersect with the layer's own alpha: the point
                # is to close the seam between adjacent components, not to
                # invent coverage the layer never had.
                side_mask = (cv2.dilate(side.astype(np.uint8), kernel).astype(bool)
                             & (mask > 0)) | (side & faint)
            out[f"{tag}{suffix}"] = _rgba_with_alpha(arr, alpha * side_mask)

    return out


def _eye_feature_halves(layer_dict: dict[str, np.ndarray], face_center_x: float, *,
                        alpha_threshold: int) -> dict[str, np.ndarray]:
    """Return a non-mutating view with every splittable eye feature divided."""
    working = dict(layer_dict)
    halves = split_eyes(working, face_center_x, alpha_threshold=alpha_threshold)
    for tag, image in halves.items():
        working[tag] = image
    for parent in {tag[:-1] for tag in halves}:
        working.pop(parent, None)
    return working


def derive_missing_eyewhite(original_rgba: np.ndarray,
                            layer_dict: dict[str, np.ndarray], *,
                            alpha_threshold: int = 10,
                            colour_margin: float = 12.0,
                            ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Conservatively recover bilateral sclera from an eyeless layer contract.

    This operates only on a rig working set. It compares the original against
    the occlusion-complete ``head`` and featureless ``face`` inside ROIs grown
    from existing iris anchors, removes pixels already owned by eye features,
    and accepts the result only when both sides contain plausible connected
    coverage. The returned images contain original pixels so the derived
    overlay reconstructs the rest pose rather than inventing new colour.
    """
    report: dict[str, Any] = {
        "source": "head_face_original_difference",
        "attempted": False,
        "succeeded": False,
        "confidence": 0.0,
        "failure": None,
        "parts": [],
        "sides": {},
    }
    if any(tag in layer_dict for tag in EYEWHITE_TAGS):
        report["failure"] = "native_eyewhite_present"
        return {}, report
    head = layer_dict.get("head")
    face = layer_dict.get("face")
    original = np.asarray(original_rgba)
    if head is None or face is None or original.shape != np.asarray(head).shape:
        report["failure"] = "original_head_face_required"
        return {}, report
    report["attempted"] = True

    iris_parts = {side: layer_dict.get(f"irides{side}") for side in ("l", "r")}
    if any(image is None for image in iris_parts.values()):
        report["failure"] = "bilateral_iris_anchors_required"
        return {}, report

    head_arr = np.asarray(head)
    face_arr = np.asarray(face)
    h, w = original.shape[:2]
    original_rgb = original[..., :3].astype(np.float32)
    head_rgb = head_arr[..., :3].astype(np.float32)
    face_rgb = face_arr[..., :3].astype(np.float32)
    head_error = np.linalg.norm(original_rgb - head_rgb, axis=2)
    face_error = np.linalg.norm(original_rgb - face_rgb, axis=2)
    explained_by_head = (face_error - head_error) >= colour_margin
    # Face RGB is still useful evidence where its alpha intentionally opens an
    # eye socket. Requiring face alpha here would make the exact rest-faithful
    # missing-eyewhite case impossible to derive.
    valid_surface = ((head_arr[..., 3] > alpha_threshold)
                     & (original[..., 3] > alpha_threshold))

    outputs: dict[str, np.ndarray] = {}
    side_confidences: list[float] = []
    for side, iris in iris_parts.items():
        assert iris is not None
        iris_mask = _mask_of(iris, alpha_threshold)
        iris_box = _bbox(iris_mask)
        iris_center = _centroid(_alpha_of(iris), alpha_threshold)
        if iris_box is None or iris_center is None:
            report["failure"] = f"empty_iris_{side}"
            return {}, report
        ix1, iy1, ix2, iy2 = iris_box
        iris_w, iris_h = max(1, ix2 - ix1), max(1, iy2 - iy1)
        cx, cy = iris_center
        roi_x = max(6, int(round(iris_w * 1.45)))
        roi_y = max(4, int(round(iris_h * 0.85)))
        x1, x2 = max(0, int(round(cx)) - roi_x), min(w, int(round(cx)) + roi_x + 1)
        y1, y2 = max(0, int(round(cy)) - roi_y), min(h, int(round(cy)) + roi_y + 1)
        roi = np.zeros((h, w), bool)
        roi[y1:y2, x1:x2] = True

        owned = np.zeros((h, w), bool)
        for prefix in ("irides", "eyelash", "eyebrow", "eyes"):
            feature = layer_dict.get(f"{prefix}{side}")
            if feature is not None:
                owned |= _mask_of(feature, alpha_threshold)
        owned = cv2.dilate(owned.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        candidate = roi & valid_surface & explained_by_head & ~owned
        candidate = cv2.morphologyEx(candidate.astype(np.uint8), cv2.MORPH_CLOSE,
                                     np.ones((3, 5), np.uint8)).astype(bool)
        candidate &= roi & valid_surface & ~owned

        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            candidate.astype(np.uint8), 8
        )
        kept = np.zeros((h, w), bool)
        iris_area = max(1, int(iris_mask.sum()))
        min_area = max(8, int(round(iris_area * 0.12)))
        max_area = max(min_area, int(round((x2 - x1) * (y2 - y1) * 0.55)))
        near_iris = cv2.dilate(iris_mask.astype(np.uint8),
                              np.ones((max(3, iris_h), max(3, iris_w * 2 + 1)), np.uint8)).astype(bool)
        for label in range(1, count):
            component = labels == label
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < min_area or area > max_area or not np.any(component & near_iris):
                continue
            kept |= component
        kept_area = int(kept.sum())
        if kept_area < min_area:
            report["failure"] = f"low_sclera_support_{side}"
            return {}, report
        advantage = float(np.mean((face_error - head_error)[kept]))
        # Repaired feature layers often carry the full eye disk (A002's iris
        # masks are ~650 px), while the two exposed sclera crescents total only
        # ~100 px. Fifteen percent is therefore the measured support scale, not
        # an expectation that sclera should rival the feature mask in area.
        coverage_score = min(1.0, kept_area / max(iris_area * 0.15, 1.0))
        colour_score = min(1.0, max(0.0, (advantage - colour_margin) / 32.0))
        side_confidence = 0.55 * coverage_score + 0.45 * colour_score
        side_confidences.append(side_confidence)
        report["sides"][side] = {
            "pixels": kept_area,
            "iris_pixels": iris_area,
            "mean_head_advantage": round(advantage, 3),
            "confidence": round(float(side_confidence), 3),
        }
        outputs[f"eyewhite{side}"] = _rgba_with_alpha(original, original[..., 3] * kept)

    confidence = round(float(min(side_confidences)), 3)
    if confidence < 0.55:
        report["failure"] = "confidence_below_threshold"
        report["confidence"] = confidence
        return {}, report
    report.update({
        "succeeded": True,
        "confidence": confidence,
        "failure": None,
        "parts": sorted(outputs),
        "removed_from": "head",
        "motion_reference": "face",
        "canonical_bundle_modified": False,
    })
    return outputs, report


def rig_preflight(layer_dict: dict[str, np.ndarray], *,
                  original_rgba: np.ndarray | None = None,
                  body_remainder: np.ndarray | None = None,
                  rig_intent: dict[str, Any] | None = None,
                  alpha_threshold: int = 10) -> dict[str, Any]:
    """Assess rig readiness without re-judging static Portrait validity.

    `rig_intent`, when given (Assembly Bundle input), is Composer's own
    authored RigIntent (`assembly.AssemblyAsset.rig_intent`). Its presence
    -- not just a matching region inside it -- is what tells
    `upper_torso_soft_morph` checking to use `soft_morph.find_authored_
    region` instead of `derive_upper_torso_soft_region`'s guess: an
    Assembly Bundle whose author simply did not author a region is still
    "AutoRig must not invent one" (Master doc #23 invariant #11), not a
    reason to fall back to Portrait Bundle's legacy auto-derivation. `None`
    (every Portrait Bundle caller) keeps today's auto-derivation exactly.
    """
    available = {
        tag for tag, image in layer_dict.items()
        if image is not None and np.asarray(image).ndim == 3
        and np.asarray(image).shape[-1] == 4
        and np.any(np.asarray(image)[..., 3] > alpha_threshold)
    }
    checks: dict[str, Any] = {
        tag: {"required": True, "available": tag in available}
        for tag in ("head", "face", "mouth")
    }
    for tag in ("neck", "topwear", "irides", "eyelash"):
        checks[tag] = {"required": True, "available": tag in available}
    warnings: list[dict[str, str]] = []
    missing_hard = [tag for tag in ("head", "face") if tag not in available]
    if missing_hard:
        warnings.append({"code": "missing_core_semantics",
                         "message": f"required rig semantics missing: {', '.join(missing_hard)}"})
        return {
            "status": "INCOMPATIBLE",
            "static_portrait_validity": "not_evaluated",
            "checks": checks,
            "missing": missing_hard,
            "recoverable": [],
            "warnings": warnings,
        }

    sample = next(np.asarray(layer_dict[tag]) for tag in available)
    anchors = detect_anchors(layer_dict, sample.shape[:2], alpha_threshold=alpha_threshold)
    face_center = anchors.get("face_center")
    probe = (_eye_feature_halves(layer_dict, face_center[0], alpha_threshold=alpha_threshold)
             if face_center is not None else dict(layer_dict))
    native = any(tag in available for tag in EYEWHITE_TAGS)
    bilateral_eyewhite = ("eyewhitel" in probe and "eyewhiter" in probe)
    bilateral_anchors = (("iridesl" in probe and "iridesr" in probe)
                         or ("eyel" in probe and "eyer" in probe))
    derivation_report: dict[str, Any] | None = None
    if not native and original_rgba is not None and bilateral_anchors:
        derived_images, derivation_report = derive_missing_eyewhite(
            original_rgba, probe, alpha_threshold=alpha_threshold
        )
        if derived_images:
            candidate = dict(probe)
            coverage = np.zeros(sample.shape[:2], bool)
            for tag, image in derived_images.items():
                candidate[tag] = image
                coverage |= image[..., 3] > alpha_threshold
            candidate_head = np.array(candidate["head"], copy=True)
            candidate_head[..., 3] = np.where(
                coverage, 0, candidate_head[..., 3]
            ).astype(np.uint8)
            candidate["head"] = candidate_head
            canonical = dict(layer_dict)
            if body_remainder is not None:
                canonical[BODY_REMAINDER] = np.asarray(body_remainder)
                candidate[BODY_REMAINDER] = np.asarray(body_remainder)
            reference = composite_layers(canonical, sample.shape[:2])
            candidate_rest = composite_layers(candidate, sample.shape[:2], order=RIG_Z_ORDER)
            candidate_fidelity = rest_fidelity(reference, candidate_rest,
                                               alpha_threshold=alpha_threshold)
            derivation_report["candidate_rest_fidelity"] = candidate_fidelity
            if candidate_fidelity["status"] != "pass":
                derivation_report.update({
                    "succeeded": False,
                    "accepted": False,
                    "failure": "rest_fidelity_rejected",
                })
            else:
                derivation_report["accepted"] = True
    derived = bool(derivation_report and derivation_report["succeeded"])
    checks["eyewhite"] = {
        "required": True,
        "available": "native" if native else ("derived" if derived else "missing"),
        "bilateral": bilateral_eyewhite or derived,
    }
    checks["eye_related_split"] = {
        "required": True,
        "bilateral_anchors": bilateral_anchors,
    }
    gaze_tags = {tag for tag in probe if tag in {"iridesl", "iridesr", "irides", "eyel", "eyer", "eyes"}}
    checks["gaze"] = {
        "required": False,
        "available": ("ready" if {"iridesl", "iridesr"}.issubset(gaze_tags)
                       else "degraded" if gaze_tags else "disabled"),
    }
    final_anchors = detect_anchors(probe, sample.shape[:2], alpha_threshold=alpha_threshold)
    required_anchors = ("face_center", "eye_left", "eye_right", "mouth",
                        "neck_pivot", "body_pivot")
    checks["anchors"] = {
        "required": list(required_anchors),
        "available": sorted(name for name in required_anchors if name in final_anchors),
        "missing": sorted(name for name in required_anchors if name not in final_anchors),
    }
    chest_neck_box = neck_bbox(probe, alpha_threshold=alpha_threshold)
    authored_region = soft_morph.find_authored_region(rig_intent)
    if rig_intent is not None:
        # Assembly path: authored region or nothing -- never a guess.
        chest_region = soft_morph.region_from_rig_intent(
            soft_morph.soft_morph_layer(probe), authored_region,
            alpha_threshold=alpha_threshold,
        )
    else:
        chest_region = soft_morph.derive_upper_torso_soft_region(
            soft_morph.soft_morph_layer(probe), neck_box=chest_neck_box,
            alpha_threshold=alpha_threshold,
        )
    checks["upper_torso_soft_morph"] = soft_morph.soft_morph_preflight(
        soft_morph.soft_morph_layer(probe), chest_region, frame_size=sample.shape[:2],
        neck_box=chest_neck_box, occluder_alpha=chest_occluder_alpha(probe),
        alpha_threshold=alpha_threshold,
    )
    remainder_pixels = (int((np.asarray(body_remainder)[..., 3] > alpha_threshold).sum())
                        if body_remainder is not None else 0)
    checks["body_remainder"] = {
        "required": False,
        "available": body_remainder is not None and remainder_pixels > 0,
        "alpha_pixels": remainder_pixels,
    }
    if body_remainder is not None and remainder_pixels:
        ownership = split_remainder(body_remainder, layer_dict,
                                    alpha_threshold=alpha_threshold)
        checks["body_remainder"]["derived_owners"] = {
            tag: int((image[..., 3] > alpha_threshold).sum())
            for tag, image in ownership.items()
        }
    if derivation_report is not None:
        checks["eyewhite"]["derivation"] = derivation_report

    if "mouth" not in available:
        warnings.append({"code": "missing_mouth",
                         "message": "mouth animation is unavailable"})
    if not bilateral_anchors:
        warnings.append({"code": "eye_split_unavailable",
                         "message": "bilateral iris anchors could not be established"})
    if not native and not derived:
        failure = ((derivation_report or {}).get("failure")
                   or "native eyewhite is absent and derivation was not possible")
        warnings.append({"code": "missing_eyewhite", "message": str(failure)})
    elif native and not bilateral_eyewhite:
        warnings.append({"code": "eyewhite_split_unavailable",
                         "message": "native eyewhite could not be split bilaterally"})

    for tag, capability in (("neck", "neck continuity"), ("topwear", "body motion"),
                            ("irides", "eye anchors"), ("eyelash", "blink")):
        if tag not in available:
            warnings.append({"code": f"missing_{tag.replace(' ', '_')}",
                             "message": f"{capability} is unavailable"})
    if checks["anchors"]["missing"]:
        warnings.append({"code": "missing_anchors",
                         "message": "anchors unavailable: "
                                    + ", ".join(checks["anchors"]["missing"])})

    fully_available = ("mouth" in available and "neck" in available
                       and "topwear" in available and "eyelash" in available
                       and bilateral_anchors
                       and (bilateral_eyewhite or derived))
    status = ("READY_WITH_DERIVATION" if fully_available and derived
              else "READY" if fully_available
              else "DEGRADED")
    missing = sorted(tag for tag, check in checks.items()
                     if isinstance(check, dict) and check.get("required") is True
                     and check.get("available") is False)
    if not native:
        missing.append("eyewhite")
    return {
        "status": status,
        "static_portrait_validity": "not_evaluated",
        "checks": checks,
        "missing": sorted(set(missing)),
        "recoverable": ["eyewhite"] if derived else [],
        "warnings": warnings,
    }


def detect_anchors(layer_dict: dict[str, np.ndarray], frame_size: tuple[int, int], *,
                   alpha_threshold: int = 10) -> dict[str, list[float]]:
    """Rig anchor points in canvas pixels, derived from layer alpha alone.

    Anchors that cannot be derived are **omitted rather than guessed**: a
    fabricated eye position is worse than an absent one, because the runtime
    can skip a motion it has no anchor for but cannot tell a wrong anchor from
    a right one.
    """
    canvas_h, canvas_w = int(frame_size[0]), int(frame_size[1])
    anchors: dict[str, list[float]] = {}

    def put(name: str, point: tuple[float, float] | None) -> None:
        if point is not None:
            anchors[name] = [round(point[0], 2), round(point[1], 2)]

    face_center = None
    for tag in ("face", "head"):
        img = layer_dict.get(tag)
        if img is not None:
            face_center = _centroid(_alpha_of(img), alpha_threshold)
            if face_center is not None:
                break
    if face_center is None:
        head_union = _union_alpha(layer_dict, _group_tags(layer_dict, GROUP_HEAD), alpha_threshold)
        if head_union is not None and head_union.any():
            face_center = _centroid(head_union.astype(np.float32) * 255.0, alpha_threshold)
    put("face_center", face_center)

    for name, candidates in (("eye_left", ("eyewhitel", "iridesl", "eyel")),
                             ("eye_right", ("eyewhiter", "iridesr", "eyer"))):
        for tag in candidates:
            img = layer_dict.get(tag)
            if img is not None:
                point = _centroid(_alpha_of(img), alpha_threshold)
                if point is not None:
                    put(name, point)
                    break

    mouth = layer_dict.get("mouth")
    if mouth is not None:
        put("mouth", _centroid(_alpha_of(mouth), alpha_threshold))

    neck_box = neck_bbox(layer_dict, alpha_threshold=alpha_threshold)
    if neck_box is not None:
        x1, y1, x2, y2 = neck_box
        put("neck_pivot", ((x1 + x2) / 2.0, y1 + (y2 - y1) * NECK_PIVOT_RATIO))
    elif face_center is not None:
        # No neck layer: hinge at the bottom of the head instead, which is at
        # least in the right place even if the lever arm is short.
        head_union = _union_alpha(layer_dict, _group_tags(layer_dict, GROUP_HEAD), alpha_threshold)
        head_box = _bbox(head_union) if head_union is not None else None
        if head_box is not None:
            put("neck_pivot", (face_center[0], float(head_box[3])))

    body_box = None
    topwear = layer_dict.get("topwear")
    if topwear is not None:
        body_box = _bbox(_mask_of(topwear, alpha_threshold))
    if body_box is None:
        body_union = _union_alpha(layer_dict, _group_tags(layer_dict, GROUP_BODY), alpha_threshold)
        body_box = _bbox(body_union) if body_union is not None else None
    if body_box is not None:
        put("body_pivot", ((body_box[0] + body_box[2]) / 2.0, float(body_box[3])))
    else:
        put("body_pivot", (canvas_w / 2.0, float(canvas_h)))

    return anchors


def detect_variant_eye_metadata(
    variant_layers: dict[str, np.ndarray] | None,
    instance_to_tag: dict[str, str] | None,
    *,
    alpha_threshold: int = 10,
) -> tuple[dict[str, list[float]], dict[str, list[int]]] | None:
    """Recover bilateral eye anchors/openings from one unsuffixed Composer
    variant member.

    Assembly semantic layers can omit ``eye_left``/``eye_right`` anchors and
    keep both eyes in a single variant image.  The alpha components of the
    eyewhite (or, conservatively, iris/eyes) are still an authoritative local
    signal.  Preserve their boxes in the manifest so the browser runtime does
    not mistake the member's full-canvas crop for an eye socket.
    """
    if not variant_layers or not instance_to_tag:
        return None
    candidates = [(member, image) for member, image in variant_layers.items()
                  if instance_to_tag.get(member) in {"eyewhite", "irides", "eyes"}]
    candidates.sort(key=lambda item: 0 if instance_to_tag.get(item[0]) == "eyewhite" else 1)
    for _member, image in candidates:
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[-1] != 4:
            continue
        mask = (arr[..., 3] > alpha_threshold).astype(np.uint8)
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        components = [i for i in range(1, count)
                      if int(stats[i, cv2.CC_STAT_AREA]) >= 8]
        if len(components) < 2:
            continue
        components.sort(key=lambda i: int(stats[i, cv2.CC_STAT_AREA]), reverse=True)
        components = sorted(components[:2], key=lambda i: float(centroids[i][0]))
        boxes: dict[str, list[int]] = {}
        anchors: dict[str, list[float]] = {}
        for side, i in zip(("l", "r"), components):
            x, y, w, h = (int(stats[i, key]) for key in (
                cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
            boxes[side] = [x, y, x + w, y + h]
            anchors[f"eye_{'left' if side == 'l' else 'right'}"] = [
                round(float(centroids[i][0]), 2),
                round(float(centroids[i][1]), 2),
            ]
        return anchors, boxes
    return None


def neck_bbox(layer_dict: dict[str, np.ndarray], *,
              alpha_threshold: int = 10) -> tuple[int, int, int, int] | None:
    """Bounds of the whole neck group, which is what the neck weight gradient
    is measured against. Taken over the group rather than per part so that
    `neck` and `neck_remainder` share one gradient -- give them their own and
    the two deform differently along the seam between them."""
    union = _union_alpha(layer_dict, _group_tags(layer_dict, GROUP_NECK), alpha_threshold)
    return _bbox(union) if union is not None else None


def chest_occluder_alpha(layer_dict: dict[str, np.ndarray]) -> np.ndarray | None:
    """Union alpha of whatever draws *over* `topwear` at rest -- crossed-arm
    `handwear`, a `neckwear` layered on top, and anything like them.

    A soft-morph lobe sitting entirely under one of these is invisible at
    rest, but `topwear` still deforms underneath it; since the static prop
    does not move with it, its edge can crack loose from the garment right
    at the seam between them (see `soft_morph.soft_morph_preflight`, which
    reads this as `occluder_alpha`). None when nothing draws over it, or when
    `topwear` is not in the canonical z-order at all.
    """
    target = soft_morph.SOFT_MORPH_TAG
    if target not in RIG_Z_ORDER:
        return None
    target_rank = RIG_Z_ORDER.index(target)
    tags = [tag for tag in layer_dict
            if tag != target and tag in RIG_Z_ORDER and RIG_Z_ORDER.index(tag) > target_rank
            and group_for_tag(tag) in (GROUP_BODY, GROUP_NECK)]
    if not tags:
        return None
    sample = next(iter(layer_dict.values()))
    occluder = np.zeros(np.asarray(sample).shape[:2], dtype=np.float32)
    for tag in tags:
        occluder = np.maximum(occluder, _alpha_of(layer_dict[tag]))
    return occluder


def _weight_for(tag: str, group: str, box: tuple[int, int, int, int],
                neck_box: tuple[int, int, int, int] | None,
                gradient_tags: Collection[str]) -> dict[str, Any]:
    """Head-follow weight for one part.

    The neck is the reason this is per-vertex at all: its top has to follow the
    head and its bottom has to stay with the body, which no arrangement of two
    rigid bones produces without a visible seam.
    """
    if tag in gradient_tags:
        # Explicit caller override, so it wins: the documented `back hair` risk,
        # where hair reaching past the shoulder line tears at full head weight.
        return {"mode": "gradient_y", "top": HEAD_WEIGHT, "bottom": BODY_WEIGHT,
                "y_top": float(box[1]), "y_bottom": float(box[3])}
    if group == GROUP_NECK and neck_box is not None:
        return {"mode": "gradient_y", "top": NECK_TOP_WEIGHT, "bottom": NECK_BOTTOM_WEIGHT,
                "y_top": float(neck_box[1]), "y_bottom": float(neck_box[3])}
    if tag in COLLAR_TAGS and neck_box is not None and box[1] < neck_box[3]:
        # The garment overlaps the neck, so its top edge is a collar: it shares
        # the neck's gradient exactly, which is what keeps the reclaimed window
        # and the neck showing through it moving together.
        return {"mode": "gradient_y", "top": NECK_TOP_WEIGHT, "bottom": NECK_BOTTOM_WEIGHT,
                "y_top": float(neck_box[1]), "y_bottom": float(neck_box[3])}
    if group == GROUP_HEAD:
        return {"mode": "constant", "value": HEAD_WEIGHT}
    if group == GROUP_NECK:
        return {"mode": "constant", "value": NECK_TOP_WEIGHT}
    return {"mode": "constant", "value": BODY_WEIGHT}


def render_rig_rest(parts: Collection[dict[str, Any]], images: dict[str, np.ndarray],
                    frame_size: tuple[int, int]) -> np.ndarray:
    """Composite cropped rig parts exactly as the runtime draws motion=0."""
    canvas_h, canvas_w = int(frame_size[0]), int(frame_size[1])
    # Use an ordered list rather than a tag->image dict: VariantSet members
    # intentionally share a semantic tag but are separate runtime sprites.
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for part in sorted(parts, key=lambda item: item["z"]):
        if part.get("visible", True) is False:
            continue
        image = images.get(part["name"])
        if image is None:
            raise ValueError(f"missing rig image for {part['name']!r}")
        x1, y1, x2, y2 = (int(value) for value in part["xyxy"])
        if image.shape != (y2 - y1, x2 - x1, 4):
            raise ValueError(f"rig crop shape disagrees with xyxy for {part['name']!r}")
        full = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        full.paste(Image.fromarray(image, mode="RGBA"), (x1, y1))
        canvas.alpha_composite(full)
    return np.array(canvas, dtype=np.uint8)


def _draw_rank(tag: str, draw_order: Sequence[str] | None,
               depth_parent: dict[str, str]) -> tuple[int, int]:
    """Paint-order sort key for one tag (`draw_order != motion_depth`).

    With no `draw_order` supplied, this is exactly today's canonical
    semantic table lookup -- the existing Portrait Bundle path is
    untouched. With one supplied (Assembly Bundle input), a tag `draw_order`
    itself lists ranks first; a tag it never saw -- a remainder split, an
    eye split, a derived-eyewhite overlay, all AutoRig-only derivations
    Composer has no concept of -- walks `depth_parent` up to whichever
    ancestor *is* listed and inherits its rank, with the canonical table as
    a tiebreak among several derived tags sharing one parent (so e.g.
    `eyewhitel`/`eyewhiter` stay adjacent rather than landing in dict
    iteration order). A tag with no listed ancestor at all sorts after
    everything Composer authored, rather than being silently dropped to the
    back or the front.
    """
    if draw_order is None:
        return (RIG_Z_ORDER.index(tag) if tag in RIG_Z_ORDER else -1, 0)
    lookup = tag
    seen: set[str] = set()
    while lookup not in draw_order:
        parent = depth_parent.get(lookup, lookup)
        if parent == lookup or parent in seen:
            break
        seen.add(lookup)
        lookup = parent
    if lookup in draw_order:
        return (draw_order.index(lookup), RIG_Z_ORDER.index(tag) if tag in RIG_Z_ORDER else 0)
    return (len(draw_order), RIG_Z_ORDER.index(tag) if tag in RIG_Z_ORDER else -1)


def build_rig(layer_dict: dict[str, np.ndarray], *,
              original_rgba: np.ndarray | None = None,
              body_remainder: np.ndarray | None = None,
              depth_dict: dict[str, np.ndarray] | None = None,
              frame_size: tuple[int, int] | None = None,
              alpha_threshold: int = 10,
              gradient_tags: Collection[str] = (),
              contour_tags: Collection[str] = (),
              island_policy: str = "separate",
              draw_order: Sequence[str] | None = None,
              rest_reference: np.ndarray | None = None,
              rig_intent: dict[str, Any] | None = None,
              run_id: str = "", tag_version: str = "",
              image_prefix: str = f"{RIG_SUBDIR}/images",
              motion: dict[str, Any] | None = None,
              preflight: dict[str, Any] | None = None,
              variant_sets: dict[str, Any] | None = None,
              expression_presets: dict[str, Any] | None = None,
              variant_layers: dict[str, np.ndarray] | None = None,
              instance_to_tag: dict[str, str] | None = None,
              variant_draw_order: Sequence[str] | None = None,
              provenance: dict[str, Any] | None = None,
                  source_instance_ids: dict[str, str] | None = None,
                  visibility_curves: Sequence[dict[str, Any]] | None = None,
                  clip_masks: Sequence[dict[str, Any]] | None = None,
                  boundary_stitches: Sequence[dict[str, Any]] | None = None,
                  physics: dict[str, Any] | None = None,
              ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Stages A-D: turn `{tag: full-canvas RGBA}` into `(manifest, images)`.

    `images` maps part name to the cropped RGBA the manifest references, so the
    caller decides where they land on disk (`write_rig_project` is the default
    answer). `depth_dict`, when given, overrides the tag depth table per layer
    with the median Marigold depth over that layer's visible pixels -- the same
    statistic `spine.layers_to_parts` uses, so a run can be compared against
    its own Spine export.

    `gradient_tags` forces a head-to-body vertical falloff onto tags that would
    otherwise follow the head rigidly; `("back hair",)` is the case the
    feasibility doc calls out.

    `contour_tags` opts specific tags into the experimental contour mesh
    backend (absorption plan #8, P1-A) instead of the grid default, for A/B
    comparison against it (`preview/check_mesh_quality.mjs`, P1-B). A tag
    `island_policy` is passed to the contour backend (`separate` by default;
    `connect_nearest`, `largest_only`, or `reject` are explicit alternatives).
    A contour result that cannot be triangulated still falls back to grid.

    `draw_order` is Composer's own authored paint order (`assembly.
    AssemblyAsset.draw_order`) -- `draw_order != motion_depth`
    (`PORTRAIT_AUTORIG_IMPLEMENTATION_DIRECTIVE_v0.2.md` #5, Master doc #7,
    #23 invariant #5): `parts[].z` (paint order) follows it when given,
    while `parts[].depth` (parallax strength) is still computed from
    `_DEPTH_TABLE`/`depth_dict` exactly as always -- AutoRig's own motion
    semantics never redefine Composer's draw order. A tag `draw_order`
    never saw (a remainder split, an eye split, a derived-eyewhite overlay --
    all AutoRig-only derivations Composer has no concept of) inherits its
    parent's position instead of an arbitrary fallback; see `_draw_rank`.
    None (the default, and every existing Portrait Bundle caller) reproduces
    today's canonical-semantic-table ordering exactly.

    `rest_reference`, when given, replaces the internally-recomposited
    canonical reference `rest_fidelity` is checked against with this exact
    array instead -- the Assembly path passes `AssemblyAsset.reference`
    (Composer's own rendered `reference.png`), so the check is against the
    real Assembly Truth (Master doc #2) rather than a composite rebuilt
    from the same already-flattened per-tag layers the rig itself was
    built from, which could agree with itself while both were still wrong
    relative to what Composer actually authored. None (the default, and
    every Portrait Bundle caller) keeps today's self-recomposited check.

    `rig_intent`, when given (Assembly Bundle input, `AssemblyAsset.
    rig_intent`), replaces `upper_torso_soft_morph`'s alpha-guessed region
    with whatever Composer's C4 `secondary_regions.py` actually authored
    (`soft_morph.find_authored_region`/`region_from_rig_intent`) -- geometry,
    locks, author_strength, and response_profile all come from there, not
    from `derive_upper_torso_soft_region`'s guess; a bundle whose author did
    not author a region compiles with the field disabled rather than
    falling back to a guess (Master doc #23 invariant #11). `soft_morph_
    preflight` still runs unchanged against the authored geometry and the
    real compiled art -- AutoRig keeps owning geometry/deformation safety
    even though it no longer decides where the lobes are centred. None (the
    default, every Portrait Bundle caller) keeps today's auto-derivation.
    """
    working: dict[str, np.ndarray] = {}
    for tag, img in layer_dict.items():
        if img is None:
            continue
        arr = np.asarray(img)
        if arr.ndim != 3 or arr.shape[-1] != 4 or not np.any(arr[..., 3] > alpha_threshold):
            continue
        working[tag] = arr

    if frame_size is None:
        if not working:
            raise ValueError("frame_size is required when no layer has content")
        sample = next(iter(working.values()))
        frame_size = (int(sample.shape[0]), int(sample.shape[1]))
    canvas_h, canvas_w = int(frame_size[0]), int(frame_size[1])
    canonical_layers = dict(layer_dict)
    if body_remainder is not None:
        canonical_layers[BODY_REMAINDER] = np.asarray(body_remainder)
    # With no draw_order this is composite_layers' own default
    # (SEMANTIC_Z_ORDER) -- today's Portrait Bundle behaviour, unchanged.
    # With one supplied, the canonical reference has to be composited in
    # *that* order too, or rest_fidelity below would be comparing the rig's
    # own draw_order-ordered rest render against a differently-ordered
    # reference and could fail spuriously on a correctly-compiled rig.
    if rest_reference is not None:
        canonical_reference = np.asarray(rest_reference)
        if canonical_reference.shape != (canvas_h, canvas_w, 4):
            raise ValueError(f"rest_reference shape {canonical_reference.shape} does not match "
                             f"canvas {(canvas_h, canvas_w, 4)}")
    else:
        canonical_order = (tuple(draw_order) if draw_order is not None else SEMANTIC_Z_ORDER)
        canonical_reference = composite_layers(canonical_layers, (canvas_h, canvas_w),
                                               order=canonical_order)
    if preflight is None:
        preflight = rig_preflight(layer_dict, original_rgba=original_rgba,
                                  body_remainder=body_remainder, rig_intent=rig_intent,
                                  alpha_threshold=alpha_threshold)
    preflight = json.loads(json.dumps(preflight))

    # Stage B: remainder next, so the eye split and the anchors below see the
    # same layer set the manifest will describe.
    depth_parent = {tag: tag for tag in working}
    if body_remainder is not None:
        for tag, img in split_remainder(body_remainder, working,
                                        alpha_threshold=alpha_threshold).items():
            working[tag] = img
            # Remainder subdivision changes motion ownership, not the
            # Composer-authored setup plane.  In an Assembly compile the
            # supplied draw order contains `body_remainder` but not the
            # AutoRig-only split tags; inherit that authored rank so a split
            # head/neck fragment cannot jump in front of the portrait at rest.
            depth_parent[tag] = BODY_REMAINDER if draw_order is not None else tag

    anchors = detect_anchors(working, (canvas_h, canvas_w), alpha_threshold=alpha_threshold)
    face_center = anchors.get("face_center")
    if face_center is not None:
        halves = split_eyes(working, face_center[0], alpha_threshold=alpha_threshold)
        for tag, img in halves.items():
            working[tag] = img
            depth_parent[tag] = tag[:-1]
        # Drop the undivided originals -- keeping both would double-draw the eyes.
        for parent in {tag[:-1] for tag in halves}:
            working.pop(parent, None)
            depth_parent.pop(parent, None)
        if halves:
            # The eye anchors only exist once the split has run.
            anchors = detect_anchors(working, (canvas_h, canvas_w),
                                     alpha_threshold=alpha_threshold)

    derived_report: dict[str, Any] | None = None
    preflight_derivation = (preflight.get("checks", {}).get("eyewhite", {})
                            .get("derivation", {}))
    derivation_blocked = preflight_derivation.get("failure") == "rest_fidelity_rejected"
    if (original_rgba is not None and not any(tag in working for tag in EYEWHITE_TAGS)
            and not derivation_blocked):
        head_before_derivation = np.array(working["head"], copy=True)
        derived, derived_report = derive_missing_eyewhite(
            original_rgba, working, alpha_threshold=alpha_threshold
        )
        if derived:
            coverage = np.zeros((canvas_h, canvas_w), bool)
            for tag, image in derived.items():
                working[tag] = image
                # Derived sclera is an overlay cut out of head, but it belongs
                # to the face surface for motion. Matching face depth prevents
                # the fallback from recreating A002's head/face parallax loss.
                depth_parent[tag] = "face"
                coverage |= image[..., 3] > alpha_threshold
            head = np.array(working["head"], copy=True)
            head[..., 3] = np.where(coverage, 0, head[..., 3]).astype(np.uint8)
            working["head"] = head
            anchors = detect_anchors(working, (canvas_h, canvas_w),
                                     alpha_threshold=alpha_threshold)

            candidate_rest = composite_layers(working, (canvas_h, canvas_w),
                                              order=RIG_Z_ORDER)
            candidate_fidelity = rest_fidelity(canonical_reference, candidate_rest,
                                               alpha_threshold=alpha_threshold)
            derived_report["candidate_rest_fidelity"] = candidate_fidelity
            if candidate_fidelity["status"] != "pass":
                for tag in derived:
                    working.pop(tag, None)
                    depth_parent.pop(tag, None)
                working["head"] = head_before_derivation
                derived_report.update({
                    "accepted": False,
                    "succeeded": False,
                    "failure": "rest_fidelity_rejected",
                })
                eye_check = preflight.get("checks", {}).get("eyewhite", {})
                eye_check.update({"available": "missing", "bilateral": False,
                                  "derivation": derived_report})
                preflight["status"] = "DEGRADED"
                preflight["recoverable"] = []
                preflight["warnings"] = list(preflight.get("warnings", [])) + [{
                    "code": "eyewhite_derivation_rest_fidelity",
                    "message": "derived eyewhite changed the canonical setup pose",
                }]
                anchors = detect_anchors(working, (canvas_h, canvas_w),
                                         alpha_threshold=alpha_threshold)
            else:
                derived_report["accepted"] = True

    # Stage D.
    neck_box = neck_bbox(working, alpha_threshold=alpha_threshold)
    depths: dict[str, float] = {}
    for tag, arr in working.items():
        parent = depth_parent.get(tag, tag)
        is_derived = bool(derived_report and derived_report.get("succeeded")
                          and tag in derived_report["parts"])
        depth = (_DEPTH_TABLE.get(parent, UNKNOWN_DEPTH) if is_derived
                 else _DEPTH_TABLE.get(tag, _DEPTH_TABLE.get(parent, UNKNOWN_DEPTH)))
        if depth_dict is not None and parent in depth_dict:
            visible = arr[..., 3] > alpha_threshold
            estimated = np.asarray(depth_dict[parent])
            if np.any(visible):
                depth = float(np.median(estimated[visible]))
        depths[tag] = round(float(depth), 4)

    ordered = sorted(working, key=lambda tag: _draw_rank(tag, draw_order, depth_parent))

    parts: list[dict[str, Any]] = []
    images: dict[str, np.ndarray] = {}
    for z, tag in enumerate(ordered):
        cropped = crop_to_alpha(working[tag], alpha_threshold)
        if cropped is None:
            continue
        crop_img, xyxy = cropped
        name = tag.replace(" ", "_")
        group = group_for_tag(tag)
        weight = _weight_for(tag, group, tuple(xyxy), neck_box, gradient_tags)
        images[name] = crop_img
        # Anything deforming along a gradient gets the finer cell: that is
        # where a coarse grid shows up as faceting. Opted-in tags try the
        # contour backend first and fall back to grid when it declines
        # (multi-island alpha; see mesh.contour_mesh).
        deformation_kinds = {"parallax_turn", "shell_turn", "weighted_rotation", "continuous_field"}
        if tag in {"eyewhite", "eyewhitel", "eyewhiter", "irides", "iridesl", "iridesr",
                   "eyes", "eyel", "eyer", "eyelash", "eyelashl", "eyelashr", "mouth"}:
            deformation_kinds.update({"eye_fold", "gaze"})
        # Topwear is the runtime target of the optional upper-torso soft field.
        # The authored/derived spec is assembled below, after parts are built,
        # so use the semantic target here rather than a not-yet-created local
        # spec. This only selects a finer mesh; enabling the deformer remains
        # controlled by the motion payload.
        if tag in soft_morph.SOFT_MORPH_TAGS:
            deformation_kinds.add("local_soft_field")
        part_mesh = (
            (tag in contour_tags
             and contour_mesh_spec(crop_img[..., 3], tuple(int(v) for v in xyxy),
                                   island_policy=island_policy))
            or motion_aware_mesh_spec((canvas_h, canvas_w), tag=tag, group=group,
                                      deformation_kinds=deformation_kinds,
                                      weight_mode=weight["mode"])
        )
        # Topology freeze (directive v0.2 #11-12): generate mesh -> hash ->
        # freeze. Downstream weights/keyforms/constraints/physics bindings
        # (once they exist) invalidate on a hash mismatch rather than being
        # silently reused; see topology.topology_changed.
        part_mesh["topology_hash"] = mesh_topology_hash(part_mesh, tuple(int(v) for v in xyxy))
        part_spec = {
            "name": name,
            "tag": tag,
            "image": f"{image_prefix}/{name}.png" if image_prefix else f"{name}.png",
            "xyxy": [int(v) for v in xyxy],
            "group": group,
            "depth": depths[tag],
            "z": z,
            "weight": weight,
            "mesh": part_mesh,
        }
        if (part_mesh.get("kind") == "contour"
                and tag in {"front hair", "back hair", "hair_secondary"}
                and part_mesh.get("vertices") and part_mesh.get("triangles")):
            part_spec["strand_topology"] = {
                "version": "p1",
                "specs": build_strand_specs(
                    part_mesh["vertices"], part_mesh["triangles"],
                    min_area=1.0,
                ),
            }
        if source_instance_ids and tag in source_instance_ids:
            part_spec["source_instance_id"] = source_instance_ids[tag]
        parts.append(part_spec)
        if derived_report and derived_report.get("succeeded") and tag in derived_report["parts"]:
            parts[-1]["derived"] = True

    # Composer VariantSet members are compiled as separate runtime parts.  The
    # Assembly reader excluded them from the flattened semantic layers, so the
    # active member remains present in the canonical reference without being
    # double-drawn by the ordinary semantic part.
    variant_part_names: dict[str, str] = {}
    eye_opening_metadata: dict[str, list[int]] | None = None
    if variant_sets:
        if not variant_layers or not instance_to_tag:
            raise ValueError("VariantSets require positioned instance layers and instance-to-tag mappings")
        for spec in variant_sets.values():
            for member in spec.get("members", []):
                member = str(member)
                if member not in variant_layers:
                    raise ValueError(f"VariantSet member {member!r} has no layer image")
                cropped = crop_to_alpha(variant_layers[member], alpha_threshold)
                if cropped is None:
                    raise ValueError(f"VariantSet member {member!r} has no visible pixels")
                crop_img, xyxy = cropped
                tag = instance_to_tag.get(member)
                if tag is None:
                    raise ValueError(f"VariantSet member {member!r} has no semantic tag")
                name = _part_name(member)
                if name in images:
                    raise ValueError(f"VariantSet member {member!r} collides with a rig part name")
                variant_part_names[member] = name
                group = group_for_tag(tag)
                weight = _weight_for(tag, group, tuple(xyxy), neck_box, gradient_tags)
                part_mesh = mesh_spec((canvas_h, canvas_w), fine=weight["mode"] == "gradient_y")
                part_mesh["topology_hash"] = mesh_topology_hash(part_mesh, tuple(int(v) for v in xyxy))
                # Keep variants at their Composer semantic plane.  All members
                # in one set are exclusive, so sharing this z is intentional.
                base_z = next((p["z"] for p in parts if p["tag"] == tag),
                              _draw_rank(tag, variant_draw_order or draw_order, {tag: tag})[0])
                parts.append({
                    "name": name, "tag": tag, "image": f"{image_prefix}/{name}.png" if image_prefix else f"{name}.png",
                    "xyxy": [int(v) for v in xyxy], "group": group,
                    "depth": round(float(_DEPTH_TABLE.get(depth_owner_for_tag(tag), UNKNOWN_DEPTH)), 4),
                    "z": float(base_z), "weight": weight, "mesh": part_mesh,
                    "variant_member": member,
                    "source_instance_id": member,
                    "visible": False,
                })
                images[name] = crop_img

        # Assembly variants may be the only source of bilateral eye geometry.
        # Preserve a compact alpha-component contract for the runtime instead
        # of making it infer socket bounds from a full-canvas member crop.
        variant_eye_metadata = detect_variant_eye_metadata(
            variant_layers, instance_to_tag, alpha_threshold=alpha_threshold
        )
        if variant_eye_metadata is not None:
            variant_anchors, eye_opening_metadata = variant_eye_metadata
            for key, value in variant_anchors.items():
                anchors.setdefault(key, value)

        compiled_variants, compiled_presets, variant_deformers, variant_report = compile_variant_bindings(
            variant_sets, expression_presets, instance_to_tag, variant_part_names
        )
        # Rest/reference validation uses Composer's authored `active` member;
        # runtime is reset to VariantSet.default immediately after that check.
        for set_id, spec in compiled_variants.items():
            active_members = visible_variant_members(spec, spec["active"])
            for member in spec["members"]:
                part = next(p for p in parts if p.get("variant_member") == member)
                part["visible"] = member in active_members
                part["variant_set"] = set_id
    else:
        compiled_variants, compiled_presets, variant_deformers, variant_report = {}, {}, [], {
            "status": "disabled", "warnings": [], "errors": []
        }

    motion_payload = json.loads(json.dumps(motion if motion is not None else DEFAULT_MOTION))
    if visibility_curves:
        motion_payload["visibility_curves"] = json.loads(json.dumps(list(visibility_curves)))
    manifest = {
        "version": MANIFEST_VERSION,
        "canvas": {"width": canvas_w, "height": canvas_h},
        "source": {
            "run_id": run_id,
            "tag_version": tag_version,
            "depth": "marigold" if depth_dict else "table",
            # draw_order != motion_depth: which one decided parts[].z for
            # this compile -- Composer's authored order, or AutoRig's own
            # canonical semantic table (the Portrait Bundle path's only
            # option, and every draw_order-less caller's default).
            "draw_order": "assembly" if draw_order is not None else "table",
        },
        "anchors": anchors,
        "parts": parts,
        "motion": motion_payload,
        "rig_preflight": json.loads(json.dumps(preflight)),
    }
    if eye_opening_metadata is not None:
        manifest["eye_opening"] = eye_opening_metadata
    constraints: list[dict[str, Any]] = []
    if clip_masks:
        constraints.extend(compile_clip_masks(clip_masks))
    if boundary_stitches:
        constraints.append(boundary_stitch_spec(boundary_stitches))
    if constraints:
        manifest["constraints"] = constraints
    if physics is not None:
        if not isinstance(physics, dict):
            raise ValueError("physics must be an object when provided")
        physics_errors = validate_physics_spec(physics)
        if physics_errors:
            raise ValueError("invalid physics spec: " + "; ".join(physics_errors))
        manifest["physics"] = json.loads(json.dumps(physics))
    if provenance is not None:
        # Provenance is a Composer-owned opaque payload.  AutoRig forwards it
        # verbatim and only adds operation provenance for derived semantics.
        manifest["source"]["provenance"] = json.loads(json.dumps(provenance))
        manifest["provenance"] = json.loads(json.dumps(provenance))
    if "upper_torso_soft_morph" not in manifest["motion"]:
        if rig_intent is not None:
            # Assembly path: Composer's authored region, or explicitly
            # disabled -- never `derive_upper_torso_soft_region`'s guess
            # (Master doc #23 invariant #11).
            authored_region = soft_morph.find_authored_region(rig_intent)
            manifest["motion"]["upper_torso_soft_morph"] = (
                soft_morph.authored_upper_torso_soft_morph_spec(
                    authored_region, working, frame_size=(canvas_h, canvas_w),
                    neck_box=neck_box, occluder_alpha=chest_occluder_alpha(working),
                    alpha_threshold=alpha_threshold,
                ) if authored_region is not None else {
                    "enabled": False, "mode": "two_lobe", "strength": 0.0,
                    "source": "assembly_rig_intent", "status": "DISABLED",
                    "status_reasons": ["no_authored_region"],
                }
            )
        else:
            # Data-derived, not a static default: recomputed every run
            # against this character's own `topwear` geometry, the way
            # anchors are.
            manifest["motion"]["upper_torso_soft_morph"] = soft_morph.upper_torso_soft_morph_spec(
                working, frame_size=(canvas_h, canvas_w), neck_box=neck_box,
                occluder_alpha=chest_occluder_alpha(working), alpha_threshold=alpha_threshold,
            )
    # P2.1 local adaptive refinement: only the authored two-lobe chest region
    # gets a finer grid. The surrounding topwear keeps its motion-aware cell,
    # avoiding a dense full-garment mesh while preserving neckline/center locks.
    soft_spec = manifest["motion"].get("upper_torso_soft_morph") or {}
    if soft_spec.get("enabled") and soft_spec.get("left") and soft_spec.get("right"):
        topwear_part = next((part for part in parts if part.get("tag") in soft_morph.SOFT_MORPH_TAGS), None)
        if topwear_part and topwear_part["mesh"].get("kind") == "grid":
            tx1, ty1, tx2, ty2 = topwear_part["xyxy"]
            if soft_spec.get("coordinate_space") == "canvas_normalized":
                bx1, by1, bw, bh = 0.0, 0.0, float(canvas_w), float(canvas_h)
            else:
                bx1, by1, bw, bh = float(tx1), float(ty1), float(tx2 - tx1), float(ty2 - ty1)
            boxes = []
            for lobe in (soft_spec["left"], soft_spec["right"]):
                cx, cy = lobe["center"]
                rx, ry = lobe["radius"]
                boxes.append((bx1 + (cx - rx) * bw, by1 + (cy - ry) * bh,
                              bx1 + (cx + rx) * bw, by1 + (cy + ry) * bh))
            region = [max(tx1, min(box[0] for box in boxes) - 8),
                      max(ty1, min(box[1] for box in boxes) - 8),
                      min(tx2, max(box[2] for box in boxes) + 8),
                      min(ty2, max(box[3] for box in boxes) + 8)]
            if region[2] > region[0] and region[3] > region[1]:
                topwear_part["mesh"]["refinement"] = {"region": region, "cell": 18}
                topwear_part["mesh"]["topology_hash"] = mesh_topology_hash(
                    topwear_part["mesh"], tuple(int(v) for v in topwear_part["xyxy"]))
    if derived_report and derived_report.get("succeeded"):
        manifest["derived_semantics"] = {
            "eyewhite": json.loads(json.dumps(derived_report))
        }
    rig_rest = render_rig_rest(parts, images, (canvas_h, canvas_w))
    manifest["rest_fidelity"] = rest_fidelity(
        canonical_reference, rig_rest, alpha_threshold=alpha_threshold
    )
    # Composer's active member is reference-only.  The runtime initial state
    # is the independent VariantSet.default contract.
    for set_id, spec in compiled_variants.items():
        default_members = visible_variant_members(spec, spec["default"])
        for member in spec["members"]:
            part = next(p for p in parts if p.get("variant_member") == member)
            part["visible"] = member in default_members
    # Capability Report (directive v0.2 #34-35, Master doc #19): what this
    # *compiled* rig can actually do, separate from whether the compile
    # itself succeeded (QA) -- derived from the final parts and preflight,
    # never re-run against the input.
    manifest["capabilities"] = capability_report(parts, preflight, variant_report["status"])
    # Every v0.1 field constructed above (parts/anchors/motion/rest_fidelity/
    # rig_preflight/derived_semantics/...) is preserved verbatim; this only
    # adds parameters[]/deformers[]/drivers[] and bumps `version` to "0.2".
    manifest = upgrade_manifest_v01_to_v02(manifest)
    if physics:
        manifest["deformers"].extend(physics_deformer_entries(physics))
    if variant_deformers:
        manifest["deformers"].extend(variant_deformers)
    if compiled_variants:
        manifest["variant_sets"] = compiled_variants
        manifest["expression_presets"] = compiled_presets
        manifest["variant_bindings"] = variant_report
    return manifest, images


def write_rig_project(output_dir: str, base_name: str, manifest: dict[str, Any],
                      images: dict[str, np.ndarray], *, subdir: str = RIG_SUBDIR) -> str:
    """Write `{output_dir}/{base_name}_rig_manifest.json` plus the part PNGs
    under `{output_dir}/{subdir}/images/`. Returns the manifest path.

    The manifest sits at the run root beside `portrait_report.json` so that
    motion can be re-tuned by editing one file, without re-running the
    decomposition; the images it names are relative to that root, so zipping
    the run carries a self-contained rig.
    """
    images_dir = os.path.join(output_dir, subdir, "images")
    os.makedirs(images_dir, exist_ok=True)
    for name, img in images.items():
        Image.fromarray(img).save(os.path.join(images_dir, f"{name}.png"))

    manifest_path = os.path.join(output_dir, f"{base_name}_rig_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path



