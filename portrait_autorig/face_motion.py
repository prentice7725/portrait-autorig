"""Generated face-motion helpers shared by the compiler and runtime contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = ["build_jaw_open_spec", "build_mouth_form_spec"]


# These are normalized authoring heuristics, not character dimensions.  The
# compiler records them in the manifest so a runtime never needs a
# character-specific constant of its own.  They are deliberately modest:
# R6-A is intended for readable layer-free curvature, not teeth or tongue art.
MOUTH_FORM_HEURISTICS = {
    "corner_lift_ratio": 0.20,
    "corner_drop_ratio": 0.18,
    "corner_outward_ratio": 0.06,
    "corner_inward_ratio": 0.06,
    "center_drop_ratio": 0.025,
    "center_lift_ratio": 0.0,
    "face_lift_ratio": 0.10,
    "face_drop_ratio": 0.08,
    "face_outward_ratio": 0.08,
    "face_inward_ratio": 0.08,
    "face_gain": 0.22,
    "face_radius_x_ratio": 1.35,
    "face_radius_y_ratio": 1.40,
}


def _union_box(parts: Sequence[dict[str, Any]], tags: set[str]) -> list[float] | None:
    boxes = [part.get("xyxy") for part in parts if part.get("tag") in tags]
    boxes = [box for box in boxes if isinstance(box, Sequence) and len(box) == 4]
    if not boxes:
        return None
    return [
        min(float(box[0]) for box in boxes),
        min(float(box[1]) for box in boxes),
        max(float(box[2]) for box in boxes),
        max(float(box[3]) for box in boxes),
    ]


def build_mouth_form_spec(parts: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Derive the generated R6-A mouth-form field from this rig's geometry.

    The runtime consumes this normalized, manifest-owned field for both the
    mouth mesh and the subtle face corrective.  No sprite or per-character
    pixel constant is introduced.  The two endpoint keyforms are independent
    records so later Rig Studio authoring can override smile and frown
    separately without changing the runtime contract.
    """
    face = _union_box(parts, {"face"})
    mouth = _union_box(parts, {"mouth", "mouth_open", "mouth_closed"})
    if face is None or mouth is None:
        return None
    fx1, fy1, fx2, fy2 = face
    mx1, my1, mx2, my2 = mouth
    face_width = max(1.0, fx2 - fx1)
    face_height = max(1.0, fy2 - fy1)
    mouth_width = max(1.0, mx2 - mx1)
    mouth_height = max(1.0, my2 - my1)
    center_x = (mx1 + mx2) * 0.5
    center_y = (my1 + my2) * 0.5
    h = MOUTH_FORM_HEURISTICS
    return {
        "version": 1,
        "enabled": True,
        "target_tags": ["mouth", "mouth_open", "mouth_closed", "face"],
        "mouth_box": [round(value, 4) for value in mouth],
        "face_box": [round(value, 4) for value in face],
        "control_points": {
            "left_corner": [round(mx1, 4), round(center_y, 4)],
            "center": [round(center_x, 4), round(center_y, 4)],
            "right_corner": [round(mx2, 4), round(center_y, 4)],
        },
        "keyforms": {
            "-1": {
                "corner_drop_ratio": h["corner_drop_ratio"],
                "corner_inward_ratio": h["corner_inward_ratio"],
                "center_drop_ratio": h["center_drop_ratio"],
                "face_drop_ratio": h["face_drop_ratio"],
                "face_inward_ratio": h["face_inward_ratio"],
                "face_gain": h["face_gain"],
            },
            "+1": {
                "corner_lift_ratio": h["corner_lift_ratio"],
                "corner_outward_ratio": h["corner_outward_ratio"],
                "center_lift_ratio": h["center_lift_ratio"],
                "face_lift_ratio": h["face_lift_ratio"],
                "face_outward_ratio": h["face_outward_ratio"],
                "face_gain": h["face_gain"],
            },
        },
        "face_corrective": {
            "center": [round(center_x, 4), round(center_y, 4)],
            "radius_x": round(max(mouth_width * h["face_radius_x_ratio"], face_width * 0.16), 4),
            "radius_y": round(max(mouth_height * h["face_radius_y_ratio"], face_height * 0.06), 4),
            "gain": h["face_gain"],
        },
        "source": "autorig_r6_mouth_form",
    }


def build_jaw_open_spec(parts: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Derive a subtle lower-face response from compiled face/mouth boxes.

    The mouth drawing remains a separate variant/sprite. This spec only gives
    the runtime a normalized lower-face influence field, so a character's
    pixel dimensions never become constants in JavaScript.
    """
    face = next((part for part in parts if part.get("tag") == "face"), None)
    mouths = [part for part in parts
              if part.get("tag") in {"mouth", "mouth_open", "mouth_closed"}]
    if face is None or not mouths:
        return None
    fx1, fy1, fx2, fy2 = (float(value) for value in face["xyxy"])
    mx1 = min(float(part["xyxy"][0]) for part in mouths)
    my1 = min(float(part["xyxy"][1]) for part in mouths)
    mx2 = max(float(part["xyxy"][2]) for part in mouths)
    my2 = max(float(part["xyxy"][3]) for part in mouths)
    face_width = max(1.0, fx2 - fx1)
    mouth_height = max(1.0, my2 - my1)
    return {
        "version": 1,
        "enabled": True,
        "target_tag": "face",
        "mouth_box": [round(mx1, 4), round(my1, 4), round(mx2, 4), round(my2, 4)],
        "influence": {
            "start_y": round(my1 + mouth_height * 0.2, 4),
            "end_y": round(fy2, 4),
            "center_x": round((mx1 + mx2) * 0.5, 4),
            "radius_x": round(max(face_width * 0.42, (mx2 - mx1) * 2.0), 4),
            "edge_gain": 0.45,
        },
        # Normalized default; the runtime multiplies it by this character's
        # own face height and ParamMouthOpenY.
        "max_drop_ratio": 0.028,
        "source": "autorig_r5_face_motion",
    }
