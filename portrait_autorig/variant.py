"""Composer VariantSet -> Rig Manifest bindings.

Composer owns the state graph (instance ids and mutually-exclusive members).
This module only validates that graph at the AutoRig seam and describes the
runtime visibility deformer.  It deliberately does not invent semantic ids
from labels: every member keeps its Composer instance id and an explicit
semantic/part mapping.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .manifest import DEFORMER_SPRITE_SWAP, PHASE_VISIBILITY

DISCRETE = "discrete"
CROSSFADE = "crossfade"
SUPPORTED_TRANSITIONS = frozenset({DISCRETE, CROSSFADE})


def _part_name(instance_id: str) -> str:
    return "variant_" + (re.sub(r"[^A-Za-z0-9_.-]+", "_", str(instance_id)).strip("_") or "member")


def compile_variant_bindings(
    variant_sets: Mapping[str, Any] | None,
    expressions: Mapping[str, Any] | None,
    instance_to_tag: Mapping[str, str],
    part_names: Mapping[str, str],
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
    presets: dict[str, Any] = {}
    for preset_id, raw in (expressions or {}).items():
        if not isinstance(raw, Mapping) or not isinstance(raw.get("variants"), Mapping):
            raise ValueError(f"ExpressionPreset {preset_id!r} must contain variants")
        selections: dict[str, str] = {}
        for set_id, member in raw["variants"].items():
            set_id = str(set_id); member = str(member)
            spec = compiled.get(set_id)
            if spec is None or member not in spec["members"]:
                raise ValueError(f"ExpressionPreset {preset_id!r} selects invalid member {member!r} for {set_id!r}")
            selections[set_id] = member
        presets[str(preset_id)] = {"variants": selections}
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


__all__ = ["DISCRETE", "CROSSFADE", "compile_variant_bindings"]
