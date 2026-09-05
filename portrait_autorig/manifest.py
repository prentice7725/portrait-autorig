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
    PARAM_BREATH, PARAM_EYE_L_OPEN, PARAM_EYE_R_OPEN, PARAM_EYEBALL_X, PARAM_EYEBALL_Y,
    PARAM_UPPER_TORSO_SECONDARY,
    parameter_descriptor, standard_parameter_registry,
)

__all__ = [
    "RIG_MANIFEST_VERSION_01", "RIG_MANIFEST_VERSION_02", "RIG_MANIFEST_VERSION",
    "DEFORMER_PARALLAX_TURN", "DEFORMER_SHELL_TURN", "DEFORMER_WEIGHTED_ROTATION",
    "DEFORMER_CONTINUOUS_FIELD", "DEFORMER_EYE_FOLD", "DEFORMER_GAZE",
    "DEFORMER_SPRITE_SWAP", "DEFORMER_VISIBILITY_CURVE", "DEFORMER_LOCAL_SOFT_FIELD", "DEFORMER_KINDS",
    "DEFORMER_STRAND_SPRING", "DEFORMER_UPPER_TORSO_PHYSICS", "physics_deformer_entries",
    "DRIVER_UPPER_TORSO_SECONDARY",
    "PHASE_BASE", "PHASE_PRIMARY", "PHASE_CORRECTIVE", "PHASE_SECONDARY",
    "PHASE_CONSTRAINTS", "PHASE_VISIBILITY", "PHASE_RENDER", "EVALUATION_PHASES",
    "evaluation_block", "validate_deformer_phases",
    "deformers_from_motion", "upper_torso_secondary_entries", "upgrade_manifest_v01_to_v02",
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
DEFORMER_BODY_SWAY = "body_sway"
DEFORMER_EYE_FOLD = "eye_fold"
DEFORMER_GAZE = "gaze"
DEFORMER_SPRITE_SWAP = "sprite_swap"
DEFORMER_VISIBILITY_CURVE = "visibility_curve"
# local_soft_field (directive v0.2 #15, #18): the deformer kind
# upper_torso_secondary (and any future authored secondary region) writes
# its displacement through -- see upper_torso_secondary_entries.
DEFORMER_LOCAL_SOFT_FIELD = "local_soft_field"
DEFORMER_STRAND_SPRING = "strand_spring"
DEFORMER_UPPER_TORSO_PHYSICS = "upper_torso_physics"
DEFORMER_KINDS = frozenset({
    DEFORMER_PARALLAX_TURN, DEFORMER_SHELL_TURN, DEFORMER_WEIGHTED_ROTATION,
    DEFORMER_CONTINUOUS_FIELD, DEFORMER_BODY_SWAY, DEFORMER_EYE_FOLD, DEFORMER_GAZE, DEFORMER_SPRITE_SWAP,
    DEFORMER_VISIBILITY_CURVE,
    DEFORMER_LOCAL_SOFT_FIELD,
    DEFORMER_STRAND_SPRING, DEFORMER_UPPER_TORSO_PHYSICS,
})

# UpperTorsoSecondaryDriver (directive v0.2 #18-19): a driver *kind* name,
# not a deformer -- drivers[] entries produce a parameter value (here
# ParamUpperTorsoSecondary), deformers[] entries consume one.
DRIVER_UPPER_TORSO_SECONDARY = "UpperTorsoSecondaryDriver"

# Explicit evaluation phases (directive v0.2 #13; Master doc #15). Every
# deformer/driver/constraint declares which phase it runs in, in this fixed
# order -- a rig runtime's own call order must never be the implicit
# contract. P0-G locks the vocabulary and tags every synthesized deformer
# with one; P0-H's runtime evaluates the declared list in this order while
# retaining the motion{} adapter for v0.1 compatibility.
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

    body_sway = motion.get("body_sway")
    if body_sway:
        deformers.append({
            "id": "body_sway", "kind": DEFORMER_BODY_SWAY,
            "parameters": [PARAM_ANGLE_X, PARAM_ANGLE_Y],
            "targets": {"scope": "upper_body"}, "config": dict(body_sway),
            "phase": PHASE_PRIMARY,
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

    gaze = motion.get("gaze")
    if gaze:
        config = dict(gaze)
        config.setdefault("max_x", 0.22)
        config.setdefault("max_y", 0.14)
        config.setdefault("safe_margin", 0.08)
        deformers.append({
            "id": "gaze", "kind": DEFORMER_GAZE,
            "parameters": [PARAM_EYEBALL_X, PARAM_EYEBALL_Y],
            "targets": {"tags": ["iridesl", "iridesr", "irides", "eyel", "eyer", "eyes"]},
            "config": config, "phase": PHASE_PRIMARY,
        })

    curves = motion.get("visibility_curves") or motion.get("visibility_curve")
    if isinstance(curves, dict):
        curves = [curves]
    if isinstance(curves, list):
        for index, curve in enumerate(curves):
            if not isinstance(curve, dict):
                continue
            item = dict(curve)
            item.setdefault("targets", item.get("target", []))
            item.setdefault("phase", PHASE_VISIBILITY)
            item.setdefault("id", f"visibility_curve_{index}")
            item["kind"] = DEFORMER_VISIBILITY_CURVE
            deformers.append(item)

    return deformers


def upper_torso_secondary_entries(
    spec: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The declarative `local_soft_field` deformer + `UpperTorsoSecondaryDriver`
    reservation for an authored, enabled `motion.upper_torso_soft_morph`
    spec (`soft_morph.authored_upper_torso_soft_morph_spec`'s output) --
    `(None, None)` for anything else: not authored, author-disabled,
    preflight-disabled, or the legacy Portrait Bundle auto-derived spec
    (`source == "topwear_geometry"`), which has no `response_profile` to
    reserve a driver for.

    Directive v0.2 #15, #18-19: Composer supplies the region and qualitative
    response_profile; AutoRig compiles the deformer + driver *schema* here.
    The driver's `inputs` mirror the directive's own example exactly
    (`ParamBreath` translation, `ParamAngleY` angle) -- the actual spring
    solver connecting them is P2, so this is a reservation, not a
    computation.
    """
    if not spec or not spec.get("enabled") or spec.get("source") != "assembly_rig_intent":
        return None, None
    deformer = {
        "id": "upper_torso_secondary_field", "kind": DEFORMER_LOCAL_SOFT_FIELD,
        "parameters": [PARAM_UPPER_TORSO_SECONDARY],
        "targets": {"tag": "topwear"},
        "config": {
            "left": spec.get("left"), "right": spec.get("right"),
            "center_lock": spec.get("center_lock"), "neckline_lock": spec.get("neckline_lock"),
            "horizontal_px": spec.get("horizontal_px"), "vertical_px": spec.get("vertical_px"),
        },
        "phase": PHASE_SECONDARY,
    }
    driver = {
        "id": "upper_torso_secondary", "kind": DRIVER_UPPER_TORSO_SECONDARY,
        "inputs": [
            {"parameter": PARAM_BREATH, "mode": "translation", "weight": 1.0},
            {"parameter": PARAM_ANGLE_Y, "mode": "angle", "weight": -0.25},
        ],
        "output": PARAM_UPPER_TORSO_SECONDARY,
        "response_profile": spec.get("response_profile"),
        "response_config": spec.get("response_config"),
        # P2 keeps the authored field as the geometry backend while exposing
        # a small, explicit left/right turn coupling for the runtime spring.
        "turn_asymmetry": spec.get("turn_asymmetry", 0.08),
        "phase": PHASE_SECONDARY,
    }
    return deformer, driver


def physics_deformer_entries(spec: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Compile opt-in physics manifest declarations into secondary deformers."""
    if not spec:
        return []
    entries: list[dict[str, Any]] = []
    strand = spec.get("strand_driver")
    if strand and strand.get("enabled", True) and strand.get("strands"):
        entries.append({
            "id": "strand_spring", "kind": DEFORMER_STRAND_SPRING,
            "targets": {"tags": ["front hair", "back hair", "hair_secondary", "hair"]},
            "config": {"driver": "strand", "output": "motion.physics.strand"},
            "phase": PHASE_SECONDARY,
        })
    # Upper-torso physics deliberately does not get a second geometry
    # deformer. Its output is consumed by the existing authored
    # `local_soft_field`, preserving two-lobe weights and locks.
    return entries


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
    motion = manifest.get("motion") or {}
    out["parameters"] = standard_parameter_registry()
    out["deformers"] = deformers_from_motion(motion)
    soft_field, soft_driver = upper_torso_secondary_entries(motion.get("upper_torso_soft_morph"))
    out["drivers"] = [soft_driver] if soft_driver else []
    if soft_field:
        out["deformers"].append(soft_field)
        out["parameters"].append(parameter_descriptor(PARAM_UPPER_TORSO_SECONDARY, -1.0, 1.0, 0.0))
    out["evaluation"] = evaluation_block()
    return out
