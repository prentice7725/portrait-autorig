"""Standard parameter registry for Rig Manifest v0.2 `parameters[]`.

IDs follow the naming convention Live2D-family tooling (Iki and others) uses
-- `ParamAngleX`, `ParamEyeLOpen`, `ParamMouthOpenY`, `ParamBreath`, ... --
purely so a host that already knows that convention does not need
model-specific wiring. This is a *naming* borrow only: portrait-autorig owns
its own deformation semantics and is not targeting Iki format compatibility
(see `PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1` #3).

This module only owns the registry -- which parameters exist, their id,
range, and default. What moves them (deformers) and what drives them
(drivers) are `rig.py`/`manifest.py`'s concern, not this one's.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PARAM_ANGLE_X", "PARAM_ANGLE_Y", "PARAM_ANGLE_Z",
    "PARAM_EYE_L_OPEN", "PARAM_EYE_R_OPEN",
    "PARAM_EYEBALL_X", "PARAM_EYEBALL_Y",
    "PARAM_MOUTH_OPEN", "PARAM_MOUTH_FORM", "PARAM_BREATH",
    "PARAM_UPPER_TORSO_SECONDARY", "PARAM_HAIR_FRONT", "PARAM_HAIR_SIDE", "PARAM_HAIR_BACK",
    "STANDARD_PARAMETERS", "parameter_descriptor", "standard_parameter_registry",
]

PARAM_ANGLE_X = "ParamAngleX"
PARAM_ANGLE_Y = "ParamAngleY"
PARAM_ANGLE_Z = "ParamAngleZ"
PARAM_EYE_L_OPEN = "ParamEyeLOpen"
PARAM_EYE_R_OPEN = "ParamEyeROpen"
PARAM_EYEBALL_X = "ParamEyeBallX"
PARAM_EYEBALL_Y = "ParamEyeBallY"
PARAM_MOUTH_OPEN = "ParamMouthOpenY"
PARAM_MOUTH_FORM = "ParamMouthForm"
PARAM_BREATH = "ParamBreath"

# Secondary-output candidates (directive v0.2 #7): unlike STANDARD_
# PARAMETERS, these are conditional -- a driver's *output*, not a host
# input -- and only belong in a manifest's parameters[] when the deformer/
# driver that actually produces them is present
# (manifest.upper_torso_secondary_entries). hair_front/side/back are named
# here for the vocabulary; nothing produces them yet (P1/P2 strand work).
PARAM_UPPER_TORSO_SECONDARY = "ParamUpperTorsoSecondary"
PARAM_HAIR_FRONT = "ParamHairFront"
PARAM_HAIR_SIDE = "ParamHairSide"
PARAM_HAIR_BACK = "ParamHairBack"

# (id, min, max, default), in the order a parameter panel should render them.
STANDARD_PARAMETERS: tuple[tuple[str, float, float, float], ...] = (
    (PARAM_ANGLE_X, -1.0, 1.0, 0.0),
    (PARAM_ANGLE_Y, -1.0, 1.0, 0.0),
    (PARAM_ANGLE_Z, -1.0, 1.0, 0.0),
    (PARAM_EYE_L_OPEN, 0.0, 1.0, 1.0),
    (PARAM_EYE_R_OPEN, 0.0, 1.0, 1.0),
    (PARAM_EYEBALL_X, -1.0, 1.0, 0.0),
    (PARAM_EYEBALL_Y, -1.0, 1.0, 0.0),
    (PARAM_MOUTH_OPEN, 0.0, 1.0, 0.0),
    (PARAM_MOUTH_FORM, -1.0, 1.0, 0.0),
    (PARAM_BREATH, -1.0, 1.0, 0.0),
)


def parameter_descriptor(id_: str, min_: float, max_: float, default: float) -> dict[str, Any]:
    return {"id": id_, "min": min_, "max": max_, "default": default}


def standard_parameter_registry() -> list[dict[str, Any]]:
    """The full `parameters[]` manifest block, in standard order."""
    return [parameter_descriptor(*row) for row in STANDARD_PARAMETERS]
