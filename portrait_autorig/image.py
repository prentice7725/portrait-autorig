"""Static full-canvas RGBA operations for canonical portrait layers."""

from __future__ import annotations

import cv2
import numpy as np

from .semantic import SEMANTIC_Z_ORDER, semantic_rank


def crop_to_alpha(img: np.ndarray, alpha_threshold: int = 10) -> tuple[np.ndarray, list[int]] | None:
    """Return the visible crop and its full-canvas ``xyxy`` box."""
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[-1] != 4:
        raise ValueError(f"img must be HxWx4, got {arr.shape}")
    if not np.any(arr[..., 3] > alpha_threshold):
        return None
    # The threshold decides whether a layer is meaningful, not which edge
    # pixels survive. Cropping to >threshold shaved faint antialiasing and made
    # a lossless setup reconstruction impossible.
    nz = cv2.findNonZero((arr[..., 3] > 0).astype(np.uint8))
    assert nz is not None
    x, y, width, height = cv2.boundingRect(nz)
    return arr[y:y + height, x:x + width], [int(x), int(y), int(x + width), int(y + height)]


def composite_layers(layer_dict: dict[str, np.ndarray], frame_size: tuple[int, int], *,
                     order: tuple[str, ...] = SEMANTIC_Z_ORDER,
                     alpha_threshold: int = 10) -> np.ndarray:
    """Alpha-blend full-canvas straight-alpha layers back to front."""
    canvas_h, canvas_w = int(frame_size[0]), int(frame_size[1])
    rgb = np.zeros((canvas_h, canvas_w, 3), np.float32)
    acc = np.zeros((canvas_h, canvas_w, 1), np.float32)
    rank = {tag: index for index, tag in enumerate(order)}

    for tag in sorted(layer_dict, key=lambda item: rank.get(item, -1)):
        img = layer_dict.get(tag)
        if img is None:
            continue
        arr = np.asarray(img)
        if arr.shape != (canvas_h, canvas_w, 4):
            raise ValueError(
                f"layer {tag!r} must match canvas {(canvas_h, canvas_w, 4)}, got {arr.shape}"
            )
        if not np.any(arr[..., 3] > alpha_threshold):
            continue
        src_a = arr[..., 3:4].astype(np.float32) / 255.0
        rgb = arr[..., :3].astype(np.float32) * src_a + rgb * acc * (1.0 - src_a)
        acc = src_a + acc * (1.0 - src_a)
        rgb = rgb / np.maximum(acc, 1e-6)

    out = np.zeros((canvas_h, canvas_w, 4), np.uint8)
    out[..., :3] = np.rint(np.clip(rgb, 0, 255)).astype(np.uint8)
    out[..., 3] = np.rint(np.clip(acc[..., 0] * 255.0, 0, 255)).astype(np.uint8)
    return out


def composite_fidelity(original_rgba: np.ndarray, composite: np.ndarray,
                       subject_mask: np.ndarray, *, bad_threshold: int = 30) -> dict[str, float]:
    """Measure RGB reconstruction error inside the subject silhouette."""
    original = np.asarray(original_rgba)[..., :3].astype(np.int32)
    made = np.asarray(composite)[..., :3].astype(np.int32)
    if original.shape != made.shape:
        raise ValueError(f"original and composite shapes differ: {original.shape} != {made.shape}")
    mask = np.asarray(subject_mask)
    if mask.dtype != bool:
        mask = mask > (0.5 if mask.size and mask.max() <= 1.0 else 127)
    total = int(mask.sum())
    if total == 0:
        return {"mae": 0.0, "bad_ratio": 0.0, "bad_px": 0, "subject_px": 0}
    diff = np.abs(original - made).sum(axis=2)[mask]
    bad = int((diff > bad_threshold).sum())
    return {
        "mae": round(float(diff.mean()), 3),
        "bad_ratio": round(bad / total, 5),
        "bad_px": bad,
        "subject_px": total,
    }


def rest_fidelity(reference_rgba: np.ndarray, rig_rest_rgba: np.ndarray, *,
                  alpha_threshold: int = 10, bad_threshold: int = 8) -> dict[str, float | int | str]:
    """Compare a rig setup pose to the producer's canonical layer composite.

    This deliberately does not compare either image to the original portrait:
    static fidelity belongs to the producer. The compiler invariant begins at
    the canonical composite and measures RGB error, alpha/visibility changes,
    and high-percentile local error over the union of both visible regions.
    """
    reference = np.asarray(reference_rgba)
    rest = np.asarray(rig_rest_rgba)
    if reference.shape != rest.shape or reference.ndim != 3 or reference.shape[-1] != 4:
        raise ValueError(f"rest images must be matching HxWx4 arrays: {reference.shape} != {rest.shape}")
    visible_reference = reference[..., 3] > alpha_threshold
    visible_rest = rest[..., 3] > alpha_threshold
    subject = visible_reference | visible_rest
    subject_px = int(subject.sum())
    visibility_changed = int((visible_reference ^ visible_rest).sum())
    if subject_px:
        rgb_abs = np.abs(reference[..., :3].astype(np.int16)
                         - rest[..., :3].astype(np.int16))
        alpha_abs = np.abs(reference[..., 3].astype(np.int16)
                           - rest[..., 3].astype(np.int16))
        pixel_error = rgb_abs.max(axis=2)[subject]
        mae = float(rgb_abs[subject].mean())
        alpha_mae = float(alpha_abs[subject].mean())
        bad = int(((rgb_abs.max(axis=2) > bad_threshold)
                   | (alpha_abs > bad_threshold))[subject].sum())
        p95 = float(np.percentile(pixel_error, 95))
        p99 = float(np.percentile(pixel_error, 99))
        maximum = int(pixel_error.max())
    else:
        mae = alpha_mae = p95 = p99 = 0.0
        bad = maximum = 0
    bad_ratio = bad / subject_px if subject_px else 0.0
    if (mae <= 0.25 and alpha_mae <= 0.25 and bad_ratio <= 0.0005
            and visibility_changed == 0 and p99 <= 2.0):
        status = "pass"
    elif (mae <= 1.0 and alpha_mae <= 1.0 and bad_ratio <= 0.005
          and visibility_changed <= max(2, int(subject_px * 0.0001)) and p99 <= 8.0):
        status = "degraded"
    else:
        status = "fail"
    return {
        "reference": "portrait_bundle_canonical_composite",
        "metric_version": "1.0",
        "status": status,
        "mae": round(mae, 4),
        "alpha_mae": round(alpha_mae, 4),
        "bad_ratio": round(bad_ratio, 6),
        "bad_px": bad,
        "subject_px": subject_px,
        "visibility_changed_px": visibility_changed,
        "p95_error": round(p95, 3),
        "p99_error": round(p99, 3),
        "max_error": maximum,
        "bad_threshold": bad_threshold,
    }

