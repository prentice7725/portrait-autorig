"""Tests for capability.py -- the Capability Report.

See PORTRAIT_AUTORIG_IMPLEMENTATION_DIRECTIVE_v0.2.md #34-35, Master doc
#19, PORTRAIT_AUTORIG_PRIOR_ART_ABSORPTION_PLAN v0.1 #18 (P0-G).
"""

from __future__ import annotations

import unittest

from portrait_autorig.capability import (
    DEGRADED, DISABLED, READY, UNSUPPORTED, capability_report,
)


def _part(tag):
    return {"tag": tag, "name": tag}


def _preflight(soft_morph_status=None):
    checks = {}
    if soft_morph_status is not None:
        checks["upper_torso_soft_morph"] = {"status": soft_morph_status}
    return {"status": "READY", "checks": checks}


class CapabilityReportTests(unittest.TestCase):
    def test_head_turn_is_always_ready(self):
        # compiler.py already hard-aborts before build_rig runs at all when
        # head/face are missing, so by the time there is a report to build,
        # head_turn's own geometry was always present.
        report = capability_report([_part("head"), _part("face")], _preflight())
        self.assertEqual(report["head_turn"], READY)

    def test_blink_is_ready_when_the_sides_own_lash_part_compiled(self):
        report = capability_report([_part("eyelashl"), _part("eyelashr")], _preflight())
        self.assertEqual(report["blink_l"], READY)
        self.assertEqual(report["blink_r"], READY)

    def test_blink_is_degraded_when_only_the_undivided_lash_survived(self):
        report = capability_report([_part("eyelash")], _preflight())
        self.assertEqual(report["blink_l"], DEGRADED)
        self.assertEqual(report["blink_r"], DEGRADED)

    def test_blink_is_disabled_with_no_lash_part_at_all(self):
        report = capability_report([_part("head")], _preflight())
        self.assertEqual(report["blink_l"], DISABLED)
        self.assertEqual(report["blink_r"], DISABLED)

    def test_blink_sides_are_independent(self):
        # Only the left side's own part compiled -- the right stays
        # DISABLED rather than inheriting the left's READY.
        report = capability_report([_part("eyelashl")], _preflight())
        self.assertEqual(report["blink_l"], READY)
        self.assertEqual(report["blink_r"], DISABLED)

    def test_mouth_open_follows_mouth_part_presence(self):
        self.assertEqual(capability_report([_part("mouth")], _preflight())["mouth_open"], READY)
        self.assertEqual(capability_report([_part("head")], _preflight())["mouth_open"], DISABLED)

    def test_hair_secondary_is_always_unsupported(self):
        # Strand physics (P2) does not exist in this compiler at all yet --
        # UNSUPPORTED regardless of whether hair parts compiled.
        with_hair = capability_report([_part("front hair"), _part("back hair")], _preflight())
        without_hair = capability_report([_part("head")], _preflight())
        self.assertEqual(with_hair["hair_secondary"], UNSUPPORTED)
        self.assertEqual(without_hair["hair_secondary"], UNSUPPORTED)

    def test_upper_torso_secondary_follows_soft_morph_preflight_status(self):
        for status, expected in (("READY", READY), ("DEGRADED", DEGRADED), ("DISABLED", DISABLED)):
            report = capability_report([_part("topwear")], _preflight(soft_morph_status=status))
            self.assertEqual(report["upper_torso_secondary"], expected)

    def test_upper_torso_secondary_defaults_to_disabled_when_absent(self):
        report = capability_report([_part("topwear")], _preflight())
        self.assertEqual(report["upper_torso_secondary"], DISABLED)

    def test_report_has_every_directive_example_key(self):
        report = capability_report([_part("head"), _part("mouth")], _preflight())
        for key in ("head_turn", "blink_l", "blink_r", "mouth_open",
                   "hair_secondary", "upper_torso_secondary", "expression_variants"):
            self.assertIn(key, report)


if __name__ == "__main__":
    unittest.main()
