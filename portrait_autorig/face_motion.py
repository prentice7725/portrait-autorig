"""Generated face-motion helpers shared by the compiler and runtime contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = ["build_jaw_open_spec"]


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
