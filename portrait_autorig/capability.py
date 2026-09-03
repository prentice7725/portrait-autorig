"""Capability Report.

`PORTRAIT_AUTORIG_IMPLEMENTATION_DIRECTIVE_v0.2.md` #34; Master doc
(`SEETHROUGH_COMPOSER_AUTORIG_RESPONSIBILITY_VERSIONUP_MASTER_v0.2.md`) #19;
`PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1` #18 (P0-G).

Capability != gate (directive #35): a rig with some capabilities degraded
or disabled still compiles -- only contract corruption (an INCOMPATIBLE
`rig_preflight`, already a hard abort upstream in `compiler.py`) refuses
the whole compile. This module answers "what can this particular *compiled*
rig actually do", derived from the parts a compile actually produced plus
the `rig_preflight` verdict that already ran ahead of them -- it never
re-runs derivation or second-guesses `rig_preflight`, only reads its
result.
"""

from __future__ import annotations

from typing import Any

__all__ = ["READY", "DEGRADED", "DISABLED", "UNSUPPORTED", "capability_report"]

READY = "ready"
DEGRADED = "degraded"
DISABLED = "disabled"
UNSUPPORTED = "unsupported"


def _eye_capability(tags: set[str], side: str) -> str:
    """`blink_l` / `blink_r`: READY when this side's own `eyelash{side}`
    part compiled (the part that actually closes for a wink), DEGRADED when
    only the undivided `eyelash` survived (both eyes forced to blink
    together, no independent wink), DISABLED when there is no lash part for
    this eye at all."""
    if f"eyelash{side}" in tags:
        return READY
    if "eyelash" in tags:
        return DEGRADED
    return DISABLED


def capability_report(parts: list[dict[str, Any]], preflight: dict[str, Any],
                      variant_status: str | None = None) -> dict[str, str]:
    """The manifest's `"capabilities"` block. Values are `READY`/`DEGRADED`/
    `DISABLED`/`UNSUPPORTED` (directive #34); `rig.build_rig` calls this
    once `parts[]` and `preflight` are both final."""
    tags = {str(part["tag"]) for part in parts}

    def has(*names: str) -> bool:
        return any(name in tags for name in names)

    report: dict[str, str] = {}

    # head_turn: compiler.py already hard-aborts on an INCOMPATIBLE
    # preflight (missing head/face) before build_rig runs at all, so by the
    # time there is a capability report to build, the geometry head_turn
    # needs was always present.
    report["head_turn"] = READY

    report["blink_l"] = _eye_capability(tags, "l")
    report["blink_r"] = _eye_capability(tags, "r")

    report["mouth_open"] = READY if has("mouth") else DISABLED

    # Strand physics (P2) does not exist in this compiler at all yet --
    # UNSUPPORTED ("the compiler doesn't do this"), not DISABLED ("this
    # character's art doesn't support it"), regardless of whether hair
    # parts compiled.
    report["hair_secondary"] = UNSUPPORTED

    # upper_torso_secondary: today's implementation is upper_torso_soft_
    # morph (soft_morph.py), the pre-v0.2 predecessor of the generalized
    # driver + local_soft_field deformer -- it answers the same capability
    # question ("can this rig's upper torso do secondary-style motion")
    # even though the underlying deformer is not the v0.2 one yet.
    soft_status = ((preflight.get("checks") or {}).get("upper_torso_soft_morph") or {}).get("status")
    report["upper_torso_secondary"] = {
        "READY": READY, "DEGRADED": DEGRADED, "DISABLED": DISABLED,
    }.get(soft_status, DISABLED)

    # Variant binding is compiler capability plus this character's authored
    # sets.  The caller supplies the binding result so this report never
    # re-derives or second-guesses the compile.
    report["expression_variants"] = variant_status if variant_status is not None else DISABLED

    return report
