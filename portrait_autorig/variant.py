"""Composer VariantSet -> Rig Manifest bindings.

Composer owns the state graph (instance ids and mutually-exclusive members).
This module only validates that graph at the AutoRig seam and describes the
runtime visibility deformer.  It deliberately does not invent semantic ids
from labels: every member keeps its Composer instance id and an explicit
semantic/part mapping.
"""

from __future__ import annotations

import re
import math
from typing import Any, Mapping

from .manifest import DEFORMER_SPRITE_SWAP, PHASE_VISIBILITY
from .parameters import standard_parameter_registry

DISCRETE = "discrete"
CROSSFADE = "crossfade"
SUPPORTED_TRANSITIONS = frozenset({DISCRETE, CROSSFADE})


def visible_variant_members(spec: Mapping[str, Any], selected: str) -> set[str]:
    """Return the members visible for a selected Composer state.

    Composer may model one visual state as a group (for example open eyes are
    the eyewhite, iris, and lash members together).  Older manifests have no
    ``state_groups`` and retain the one-member behavior.
    """
    groups = spec.get("state_groups")
    labels = spec.get("state_labels")
    if isinstance(groups, Mapping) and isinstance(labels, Mapping):
        group_id = labels.get(selected)
        members = groups.get(group_id)
        if isinstance(members, list):
            return {str(member) for member in members}
    return {str(selected)}


def _part_name(instance_id: str) -> str:
    return "variant_" + (re.sub(r"[^A-Za-z0-9_.-]+", "_", str(instance_id)).strip("_") or "member")


def compile_variant_bindings(
    variant_sets: Mapping[str, Any] | None,
    expressions: Mapping[str, Any] | None,
    instance_to_tag: Mapping[str, str],
    part_names: Mapping[str, str],
    parameter_registry: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Return ``(sets, presets, deformers, report)`` for a Composer bundle.

    ``part_names`` contains the generated rig part name for each member.  A
    missing member is a contract error, not a degraded capability: silently
    dropping one state makes an exclusive set lie at runtime.
    """
    compiled: dict[str, Any] = {}
    deformers: list[dict[str, Any]] = []
    report: dict[str, Any] = {"status": "disabled", "warnings": [], "errors": []}
    owner: dict[str, str] = {}
    for set_id, raw in (variant_sets or {}).items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"VariantSet {set_id!r} must be an object")
        if raw.get("mode", "exclusive") != "exclusive":
            raise ValueError(f"VariantSet {set_id!r} has unsupported mode {raw.get('mode')!r}")
        members = list(raw.get("members") or [])
        if not members or len(set(members)) != len(members):
            raise ValueError(f"VariantSet {set_id!r} must contain unique members")
        default = raw.get("default", members[0])
        active = raw.get("active", default)
        if default not in members or active not in members:
            raise ValueError(f"VariantSet {set_id!r} has default/active outside members")
        bindings: dict[str, Any] = {}
        for member in members:
            member = str(member)
            if member in owner:
                raise ValueError(f"VariantSet member {member!r} belongs to both {owner[member]!r} and {set_id!r}")
            owner[member] = str(set_id)
            tag = instance_to_tag.get(member)
            part = part_names.get(member)
            if tag is None or part is None:
                raise ValueError(f"VariantSet {set_id!r} member {member!r} has no compiled instance mapping")
            bindings[member] = {"instance_id": member, "tag": tag, "part": part}
        transition = raw.get("transition", raw.get("transition_mode", DISCRETE))
        if transition not in SUPPORTED_TRANSITIONS:
            report["warnings"].append({
                "code": "unsupported_variant_transition",
                "variant_set": set_id,
                "transition": transition,
                "fallback": DISCRETE,
            })
            transition = DISCRETE
        compiled[str(set_id)] = {
            "mode": "exclusive", "default": str(default), "active": str(active),
            "members": [str(m) for m in members], "transition": transition,
            "member_bindings": bindings,
        }
        if isinstance(raw.get("state_groups"), Mapping):
            compiled[str(set_id)]["state_groups"] = {
                str(group): [str(member) for member in group_members]
                for group, group_members in raw["state_groups"].items()
                if isinstance(group_members, list)
            }
        if isinstance(raw.get("state_labels"), Mapping):
            compiled[str(set_id)]["state_labels"] = {
                str(member): str(label)
                for member, label in raw["state_labels"].items()
            }
        deformers.append({
            "id": "variant_" + _part_name(str(set_id))[8:],
            "kind": DEFORMER_SPRITE_SWAP,
            "parameters": [],
            "targets": {"variant_set": str(set_id)},
            "config": {"mode": transition, "default": str(default),
                       "members": [str(m) for m in members]},
            "phase": PHASE_VISIBILITY,
        })
        if active != default:
            report["warnings"].append({
                "code": "variant_active_differs_from_default",
                "variant_set": str(set_id), "active": str(active), "default": str(default),
            })
    descriptors = {
        str(item["id"]): (float(item["min"]), float(item["max"]))
        for item in (parameter_registry or standard_parameter_registry())
        if isinstance(item, Mapping) and item.get("id") is not None
    }
    presets: dict[str, Any] = {}
    for preset_id, raw in (expressions or {}).items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"ExpressionPreset {preset_id!r} must be an object")
        raw_parameters = raw.get("parameters")
        raw_variants = raw.get("variants")
        if not isinstance(raw_parameters, Mapping) and not isinstance(raw_variants, Mapping):
            raise ValueError(
                f"ExpressionPreset {preset_id!r} must contain parameters or variants"
            )
        if isinstance(raw_parameters, Mapping) and not raw_parameters:
            raw_parameters = None
        if isinstance(raw_variants, Mapping) and not raw_variants:
            raw_variants = None
        if raw_parameters is None and raw_variants is None:
            raise ValueError(
                f"ExpressionPreset {preset_id!r} must contain non-empty parameters or variants"
            )
        parameters: dict[str, float] = {}
        if raw_parameters is not None:
            for parameter_id, value in raw_parameters.items():
                parameter_id = str(parameter_id)
                if parameter_id not in descriptors:
                    raise ValueError(
                        f"ExpressionPreset {preset_id!r} selects unknown parameter {parameter_id!r}"
                    )
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(
                        f"ExpressionPreset {preset_id!r} has non-finite value for {parameter_id!r}"
                    )
                minimum, maximum = descriptors[parameter_id]
                if not minimum <= float(value) <= maximum:
                    raise ValueError(
                        f"ExpressionPreset {preset_id!r} value for {parameter_id!r} "
                        f"is outside [{minimum}, {maximum}]"
                    )
                parameters[parameter_id] = float(value)
        selections: dict[str, str] = {}
        if raw_variants is not None:
            for set_id, member in raw_variants.items():
                set_id = str(set_id); member = str(member)
                spec = compiled.get(set_id)
                if spec is None or member not in spec["members"]:
                    raise ValueError(f"ExpressionPreset {preset_id!r} selects invalid member {member!r} for {set_id!r}")
                selections[set_id] = member
        preset: dict[str, Any] = {}
        if parameters:
            preset["parameters"] = parameters
        if selections:
            preset["variants"] = selections
        presets[str(preset_id)] = preset
        if raw.get("metadata"):
            presets[str(preset_id)]["metadata"] = dict(raw["metadata"])
    if compiled:
        # An active/default mismatch is an intentional authoring-vs-runtime
        # distinction and only a warning.  Capability degrades only when the
        # runtime transition had to be substituted.
        report["status"] = (
            "degraded" if any(w.get("code") == "unsupported_variant_transition"
                               for w in report["warnings"])
            else "ready"
        )
    return compiled, presets, deformers, report


__all__ = ["DISCRETE", "CROSSFADE", "compile_variant_bindings", "visible_variant_members"]
