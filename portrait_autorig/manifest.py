"""Rig Manifest version constants.

`rig.py` builds the manifest; this module is the only place that is meant to
know the manifest's own version numbers, so `rig.py` does not have to hold a
schema literal itself (see `PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1`
#4). Schema validation and the v0.1 -> v0.2 upgrade path land here in a later
step (P0-B); this first step only extracts the version constant that already
existed as a literal in `rig.py`, with no change to what gets written.
"""

from __future__ import annotations

from typing import Any

from .parameters import (
    PARAM_ANGLE_X, PARAM_ANGLE_Y, PARAM_ANGLE_Z,
    PARAM_BREATH, PARAM_EYE_L_OPEN, PARAM_EYE_R_OPEN,
    standard_parameter_registry,
)

__all__ = [
    "RIG_MANIFEST_VERSION_01", "RIG_MANIFEST_VERSION_02", "RIG_MANIFEST_VERSION",
    "DEFORMER_PARALLAX_TURN", "DEFORMER_SHELL_TURN", "DEFORMER_WEIGHTED_ROTATION",
    "DEFORMER_CONTINUOUS_FIELD", "DEFORMER_EYE_FOLD", "DEFORMER_GAZE",
    "DEFORMER_SPRITE_SWAP", "DEFORMER_KINDS",
    "PHASE_BASE", "PHASE_PRIMARY", "PHASE_CORRECTIVE", "PHASE_SECONDARY",
    "PHASE_CONSTRAINTS", "PHASE_VISIBILITY", "PHASE_RENDER", "EVALUATION_PHASES",
    "evaluation_block", "validate_deformer_phases",
    "deformers_from_motion", "upgrade_manifest_v01_to_v02",
]

RIG_MANIFEST_VERSION_01 = "0.1"
RIG_MANIFEST_VERSION_02 = "0.2"

# Current output version: rig.build_rig now writes v0.2 (parameters[]/
# deformers[]/drivers[] added on top of the untouched v0.1 fields).
RIG_MANIFEST_VERSION = RIG_MANIFEST_VERSION_02

# P0 deformer kind vocabulary (PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN
# v0.1 #6). This module only knows the names, for reference/schema
# validation -- evaluation semantics live in the runtime.
DEFORMER_PARALLAX_TURN = "parallax_turn"
DEFORMER_SHELL_TURN = "shell_turn"
DEFORMER_WEIGHTED_ROTATION = "weighted_rotation"
DEFORMER_CONTINUOUS_FIELD = "continuous_field"
DEFORMER_EYE_FOLD = "eye_fold"
DEFORMER_GAZE = "gaze"
DEFORMER_SPRITE_SWAP = "sprite_swap"
DEFORMER_KINDS = frozenset({
    DEFORMER_PARALLAX_TURN, DEFORMER_SHELL_TURN, DEFORMER_WEIGHTED_ROTATION,
    DEFORMER_CONTINUOUS_FIELD, DEFORMER_EYE_FOLD, DEFORMER_GAZE, DEFORMER_SPRITE_SWAP,
})

# Explicit evaluation phases (directive v0.2 #13; Master doc #15). Every
# deformer/driver/constraint declares which phase it runs in, in this fixed
# order -- a rig runtime's own call order must never be the implicit
# contract. P0-G locks the vocabulary and tags every synthesized deformer
# with one; the runtime consuming *this* field (rather than the P0-D
# motion{} adapter's hardcoded sequence) is later work -- see runtime.mjs's
# module docstring for exactly where that stands today.
PHASE_BASE = "base"
PHASE_PRIMARY = "primary"
PHASE_CORRECTIVE = "corrective"
PHASE_SECONDARY = "secondary"
PHASE_CONSTRAINTS = "constraints"
PHASE_VISIBILITY = "visibility"
PHASE_RENDER = "render"
EVALUATION_PHASES: tuple[str, ...] = (
    PHASE_BASE, PHASE_PRIMARY, PHASE_CORRECTIVE, PHASE_SECONDARY,
    PHASE_CONSTRAINTS, PHASE_VISIBILITY, PHASE_RENDER,
)


def evaluation_block() -> dict[str, Any]:
    """The manifest's `"evaluation"` entry: the canonical phase order every
    deformer/driver/constraint's own `"phase"` field must be drawn from."""
    return {"phases": list(EVALUATION_PHASES)}


def validate_deformer_phases(deformers: list[dict[str, Any]]) -> list[str]:
    """Every `deformers[]` entry's `"phase"` in one call: field missing, or
    naming something outside `EVALUATION_PHASES`, one message per offender.
    Empty means valid. `rig.build_rig` never produces an invalid phase
    itself (`deformers_from_motion` always tags one); this is for an
    external tool checking a hand-edited or foreign manifest."""
    errors: list[str] = []
    for deformer in deformers:
        phase = deformer.get("phase")
        if phase is None:
            errors.append(f"deformer {deformer.get('id', '?')!r} has no \"phase\"")
        elif phase not in EVALUATION_PHASES:
            errors.append(f"deformer {deformer.get('id', '?')!r} has unknown phase {phase!r}")
    return errors


def deformers_from_motion(motion: dict[str, Any]) -> list[dict[str, Any]]:
    """Declarative `deformers[]` describing exactly what `motion{}` already
    parametrizes -- additive, not a rewrite (absorption plan #7): `motion{}`
    keeps driving today's runtime unchanged, and this re-expresses the same
    tuning against the standard parameter vocabulary for a future runtime
    (P0-D) to consume instead. Each entry's `config` is a copy of the
    corresponding `motion{}` sub-object, so it is self-contained.
    """
    deformers: list[dict[str, Any]] = []

    head_turn = motion.get("head_turn")
    if head_turn:
        config = dict(head_turn)
        deformers.append({
            "id": "head_turn_parallax", "kind": DEFORMER_PARALLAX_TURN,
            "parameters": [PARAM_ANGLE_X, PARAM_ANGLE_Y],
            "targets": {"scope": "all"}, "config": config, "phase": PHASE_PRIMARY,
        })
        deformers.append({
            "id": "head_turn_shell", "kind": DEFORMER_SHELL_TURN,
            "parameters": [PARAM_ANGLE_X, PARAM_ANGLE_Y],
            "targets": {"group": "head"}, "config": config, "phase": PHASE_PRIMARY,
        })

    head_tilt = motion.get("head_tilt")
    if head_tilt:
        deformers.append({
            "id": "head_tilt", "kind": DEFORMER_WEIGHTED_ROTATION,
            "parameters": [PARAM_ANGLE_Z],
            "targets": {"scope": "all"}, "config": dict(head_tilt), "phase": PHASE_PRIMARY,
        })

    breathing = motion.get("breathing")
    if breathing:
        deformers.append({
            "id": "breathing", "kind": DEFORMER_CONTINUOUS_FIELD,
            "parameters": [PARAM_BREATH],
            "targets": {"scope": "all"}, "config": dict(breathing), "phase": PHASE_PRIMARY,
        })

    blink = motion.get("blink")
    if blink:
        for side, param in (("l", PARAM_EYE_L_OPEN), ("r", PARAM_EYE_R_OPEN)):
            deformers.append({
                "id": f"blink_{side}", "kind": DEFORMER_EYE_FOLD,
                "parameters": [param],
                "targets": {"side": side}, "config": dict(blink), "phase": PHASE_PRIMARY,
            })

    return deformers


def upgrade_manifest_v01_to_v02(manifest: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a v0.1 rig manifest dict to v0.2, or pass an already-v0.2 one
    through unchanged (idempotent).

    Every v0.1 field (`parts`/`anchors`/`motion`/`canvas`/`source`/
    `rig_preflight`/`rest_fidelity`/`expressions`/`derived_semantics`/...) is
    preserved verbatim -- this only adds `parameters[]`/`deformers[]`/
    `drivers[]` on top and bumps `version`. Nothing here re-derives geometry;
    `deformers_from_motion` reads the same `motion{}` `rig.build_rig` already
    computed.
    """
    if manifest.get("version") == RIG_MANIFEST_VERSION_02:
        return manifest
    out = dict(manifest)
    out["version"] = RIG_MANIFEST_VERSION_02
    out["parameters"] = standard_parameter_registry()
    out["deformers"] = deformers_from_motion(manifest.get("motion") or {})
    # Real driver reservation (UpperTorsoSecondaryDriver, physics-connected
    # inputs, ...) is P1/P2; P0 leaves this empty rather than guessing.
    out["drivers"] = []
    out["evaluation"] = evaluation_block()
    return out
