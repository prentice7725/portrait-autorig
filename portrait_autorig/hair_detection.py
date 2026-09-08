"""Deterministic R5 hair motion-zone detection.

R5 owns inspection data only: it derives internal zones from the real hair
semantic layers that an Assembly Bundle provides.  It does not create new
Composer semantics, edit pixels, or simulate a chain.  R6 can consume the
stable zone ids and author root/tip/cage/keyform corrections on top.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

import cv2
import numpy as np

HAIR_SEMANTIC_TAGS = ("front hair", "back hair", "hair")
HAIR_ZONE_CLASSES = ("SHORT_SWAY", "LONG_STRAND", "MASS_SWAY")

__all__ = [
    "HAIR_SEMANTIC_TAGS", "HAIR_ZONE_CLASSES", "detect_hair_zones",
]


def _alpha_mask(image: np.ndarray, alpha_threshold: int) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("hair layer must have shape (H, W, 4)")
    if not 0 <= int(alpha_threshold) <= 255:
        raise ValueError("alpha_threshold must be between 0 and 255")
    return array[..., 3] > int(alpha_threshold)


def _root_seed(coords: np.ndarray) -> tuple[int, int]:
    """Pick a stable attachment seed from the upper local contour band."""
    y_min = int(np.min(coords[:, 0]))
    y_max = int(np.max(coords[:, 0]))
    band = coords[coords[:, 0] <= y_min + max(1, round((y_max - y_min) * 0.12))]
    x = int(round(float(np.median(band[:, 1]))))
    row = band[np.argmin(np.abs(band[:, 1] - x))]
    return int(row[0]), int(row[1])


def _geodesic_tip(mask: np.ndarray, component: np.ndarray,
                  root: tuple[int, int]) -> tuple[tuple[int, int], int]:
    """Find the furthest reachable pixel, not simply the lowest pixel."""
    height, width = mask.shape
    distances = np.full((height, width), -1, dtype=np.int32)
    queue: deque[tuple[int, int]] = deque([root])
    distances[root] = 0
    allowed = np.zeros_like(mask, dtype=bool)
    allowed[component[:, 0], component[:, 1]] = True
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and allowed[ny, nx] and distances[ny, nx] < 0:
                distances[ny, nx] = distances[y, x] + 1
                queue.append((ny, nx))
    reachable = component[distances[component[:, 0], component[:, 1]] >= 0]
    if len(reachable) == 0:
        return root, 0
    values = distances[reachable[:, 0], reachable[:, 1]]
    maximum = int(np.max(values))
    candidates = reachable[values == maximum]
    # Tie-break toward the furthest-down contour, then left, so ids are stable
    # across platforms and do not depend on connected-component traversal.
    tip = sorted(
        [(int(y), int(x)) for y, x in candidates],
        key=lambda item: (-item[0], item[1]),
    )[0]
    return tip, maximum


def _zone_class(width: int, height: int, area: int) -> str:
    aspect = float(height) / max(float(width), 1.0)
    fill = float(area) / max(float(width * height), 1.0)
    if aspect >= 1.65 and height >= 96:
        return "LONG_STRAND"
    if aspect <= 1.15 or fill >= 0.52:
        return "MASS_SWAY"
    return "SHORT_SWAY"


def _component_zone(mask: np.ndarray, labels: np.ndarray, label: int,
                    canvas_size: tuple[int, int], semantic_tag: str,
                    zone_index: int, alpha_threshold: int) -> dict[str, Any]:
    coords = np.argwhere(labels == label)
    y1, x1 = np.min(coords, axis=0)
    y2, x2 = np.max(coords, axis=0)
    root_y, root_x = _root_seed(coords)
    (tip_y, tip_x), geodesic_length = _geodesic_tip(mask, coords, (root_y, root_x))
    width, height = int(x2 - x1 + 1), int(y2 - y1 + 1)
    canvas_w, canvas_h = canvas_size
    area = int(len(coords))
    confidence = min(1.0, max(0.0,
        0.45 + min(0.35, geodesic_length / max(canvas_w + canvas_h, 1))
        + min(0.20, area / max(canvas_w * canvas_h, 1) * 4.0)))
    return {
        "zone_id": f"{semantic_tag.replace(' ', '_')}.zone_{zone_index}",
        "semantic_tag": semantic_tag,
        "class": _zone_class(width, height, area),
        "alpha_threshold": int(alpha_threshold),
        "area_px": area,
        "bbox": [int(x1), int(y1), int(x2 + 1), int(y2 + 1)],
        "root": {
            "position": [int(root_x), int(root_y)],
            "uv": [round(root_x / max(canvas_w, 1), 6), round(root_y / max(canvas_h, 1), 6)],
        },
        "tip": {
            "position": [int(tip_x), int(tip_y)],
            "uv": [round(tip_x / max(canvas_w, 1), 6), round(tip_y / max(canvas_h, 1), 6)],
        },
        "effective_length_px": int(geodesic_length),
        "width_px": width,
        "confidence": round(float(confidence), 4),
        "status": "AUTO_DETECTED",
    }


def detect_hair_zones(layers: Mapping[str, np.ndarray], *,
                      frame_size: tuple[int, int] | None = None,
                      alpha_threshold: int = 10,
                      min_component_ratio: float = 0.001) -> dict[str, Any]:
    """Return generated R5 zones for the available hair semantic layers.

    ``frame_size`` is ``(height, width)`` like the rest of the rig compiler.
    Component filtering is relative to each layer's visible area, so no
    character-specific pixel threshold is embedded in the output.
    """
    if not 0 <= float(min_component_ratio) <= 1:
        raise ValueError("min_component_ratio must be between 0 and 1")
    result: dict[str, Any] = {
        "version": 1,
        "source_semantics": list(HAIR_SEMANTIC_TAGS),
        "zones": {},
        "status": "DISABLED",
        "warnings": [],
    }
    for tag in HAIR_SEMANTIC_TAGS:
        image = layers.get(tag)
        if image is None:
            continue
        array = np.asarray(image)
        mask = _alpha_mask(array, alpha_threshold)
        height, width = mask.shape
        if frame_size is not None and tuple(frame_size) != (height, width):
            raise ValueError(f"hair layer {tag!r} shape does not match frame_size")
        visible = int(mask.sum())
        if visible == 0:
            result["warnings"].append({"tag": tag, "code": "empty_hair_layer"})
            continue
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        minimum = max(4, int(round(visible * float(min_component_ratio))))
        components = [
            (label, int(stats[label, cv2.CC_STAT_AREA]))
            for label in range(1, count) if int(stats[label, cv2.CC_STAT_AREA]) >= minimum
        ]
        # Spatial ordering makes zone_0/zone_1 stable when component area
        # changes slightly after a source revision; ids must not depend on
        # OpenCV's label allocation or a size tie.
        components.sort(key=lambda item: (
            int(stats[item[0], cv2.CC_STAT_TOP]),
            int(stats[item[0], cv2.CC_STAT_LEFT]),
            -item[1], item[0],
        ))
        zones = [_component_zone(mask, labels, label, (width, height), tag, index, alpha_threshold)
                 for index, (label, _) in enumerate(components)]
        result["zones"][tag] = zones
        if zones:
            result["status"] = "READY"
    if result["status"] == "DISABLED":
        result["warnings"].append({"code": "no_supported_hair_semantic"})
    return result
