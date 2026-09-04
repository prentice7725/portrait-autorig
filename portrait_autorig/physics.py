"""Deterministic fixed-step physics primitives for P2 drivers.

The core intentionally has no character-specific policy.  Strand and torso
drivers can provide a target/rest value and material, while this module owns
fixed-tick integration, reset/warm-up, and non-finite rollback guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any

__all__ = ["PhysicsMaterial", "PhysicsSnapshot", "DeterministicSpring",
           "StrandSpringDriver", "UpperTorsoSecondaryDriver",
           "DEFAULT_PHYSICS_CONFIG", "validate_physics_spec"]

DEFAULT_PHYSICS_CONFIG: dict[str, Any] = {
    "update_hz": 60,
    "reference_scale": 768,
    "reset_policy": "rest",
    "warmup_seconds": 0.25,
}


def validate_physics_spec(spec: dict[str, Any]) -> list[str]:
    """Return actionable errors for an opt-in manifest physics block."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["physics must be an object"]
    config = {**DEFAULT_PHYSICS_CONFIG, **(spec.get("config") or {})}
    try:
        hz = int(config["update_hz"])
        if hz <= 0 or float(config["update_hz"]) != hz: errors.append("config.update_hz must be a positive integer")
    except (TypeError, ValueError):
        errors.append("config.update_hz must be a positive integer")
    strands = (spec.get("strand_driver") or {}).get("strands", [])
    ids = [str(item.get("strand_id", item.get("id", ""))).strip() for item in strands]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        errors.append("strand_driver.strands require unique strand_id values")
    torso = spec.get("upper_torso_driver")
    if torso and torso.get("profile", "soft") not in UpperTorsoSecondaryDriver.PROFILES:
        errors.append(f"unsupported upper_torso_driver.profile: {torso.get('profile')!r}")
    return errors


@dataclass(frozen=True)
class PhysicsMaterial:
    stiffness: float = 18.0
    damping: float = 6.0
    mass: float = 1.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(float(value)) for value in
                   (self.stiffness, self.damping, self.mass)):
            raise ValueError("physics material values must be finite")
        if self.stiffness < 0 or self.damping < 0 or self.mass <= 0:
            raise ValueError("stiffness/damping must be non-negative and mass positive")


@dataclass(frozen=True)
class PhysicsSnapshot:
    value: float
    velocity: float
    degraded: bool
    diagnostic: str | None


class DeterministicSpring:
    """One scalar spring with deterministic fixed-tick integration."""

    def __init__(self, *, rest: float = 0.0,
                 material: PhysicsMaterial | None = None,
                 config: dict[str, Any] | None = None) -> None:
        self.config = dict(DEFAULT_PHYSICS_CONFIG)
        self.config.update(config or {})
        self.update_hz = int(self.config["update_hz"])
        if self.update_hz <= 0:
            raise ValueError("update_hz must be positive")
        self.rest = self._finite(rest, "rest")
        self.material = material or PhysicsMaterial()
        self.value = self.rest
        self.velocity = 0.0
        self.last_good = PhysicsSnapshot(self.value, self.velocity, False, None)
        self.degraded = False
        self.diagnostic: str | None = None

    @staticmethod
    def _finite(value: float, label: str) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{label} must be finite")
        return value

    def snapshot(self) -> PhysicsSnapshot:
        return PhysicsSnapshot(self.value, self.velocity, self.degraded, self.diagnostic)

    def resetPhysics(self, value: float | None = None) -> PhysicsSnapshot:
        self.value = self.rest if value is None else self._finite(value, "value")
        self.velocity = 0.0
        self.degraded = False
        self.diagnostic = None
        self.last_good = PhysicsSnapshot(self.value, self.velocity, False, None)
        return self.snapshot()

    def _step_once(self, target: float) -> None:
        dt = 1.0 / self.update_hz
        acceleration = ((target - self.value) * self.material.stiffness
                         - self.velocity * self.material.damping) / self.material.mass
        self.velocity += acceleration * dt
        self.value += self.velocity * dt

    def stepPhysicsFixed(self, n: int = 1, *, target: float | None = None) -> PhysicsSnapshot:
        if int(n) < 0:
            raise ValueError("fixed step count must be non-negative")
        target_value = self.rest if target is None else self._finite(target, "target")
        for _ in range(int(n)):
            self._step_once(target_value)
            if not (math.isfinite(self.value) and math.isfinite(self.velocity)):
                self.value = self.last_good.value
                self.velocity = self.last_good.velocity
                self.degraded = True
                self.diagnostic = "non_finite_rollback"
                return self.snapshot()
            self.last_good = PhysicsSnapshot(self.value, self.velocity, self.degraded, self.diagnostic)
        return self.snapshot()

    def warmupPhysics(self, seconds: float | None = None,
                      *, target: float | None = None) -> PhysicsSnapshot:
        duration = self.config["warmup_seconds"] if seconds is None else float(seconds)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("warmup seconds must be finite and non-negative")
        self.resetPhysics()
        return self.stepPhysicsFixed(math.ceil(duration * self.update_hz), target=target)


class StrandSpringDriver:
    """Deterministic collection of strand springs.

    ``length`` and ``mass`` deliberately affect lag through the material, while
    a stable hash supplies a tiny per-id phase offset without global randomness.
    """

    def __init__(self, strands: list[dict[str, Any]], *,
                 material: PhysicsMaterial | None = None,
                 config: dict[str, Any] | None = None) -> None:
        base = material or PhysicsMaterial()
        self.springs: dict[str, DeterministicSpring] = {}
        self.geometry_factor: dict[str, float] = {}
        self.offset: dict[str, float] = {}
        for strand in strands:
            strand_id = str(strand.get("strand_id", strand.get("id", ""))).strip()
            if not strand_id or strand_id in self.springs:
                raise ValueError("each strand needs a unique strand_id")
            length = float(strand.get("length", 1.0))
            mass_factor = float(strand.get("mass", 1.0))
            geometry = float(strand.get("geometry_factor", 1.0))
            if not all(math.isfinite(value) and value > 0 for value in
                       (length, mass_factor, geometry)):
                raise ValueError("strand length, mass, and geometry_factor must be positive")
            effective = PhysicsMaterial(
                stiffness=base.stiffness / max(1.0, length),
                damping=base.damping,
                mass=base.mass * mass_factor,
            )
            self.springs[strand_id] = DeterministicSpring(material=effective, config=config)
            self.geometry_factor[strand_id] = geometry
            digest = hashlib.sha256(strand_id.encode("utf-8")).digest()[0] / 255.0
            self.offset[strand_id] = (digest - 0.5) * 0.02

    def resetPhysics(self) -> dict[str, PhysicsSnapshot]:
        return {strand_id: spring.resetPhysics() for strand_id, spring in self.springs.items()}

    def warmupPhysics(self, seconds: float | None = None,
                      *, target: float = 0.0) -> dict[str, PhysicsSnapshot]:
        return {strand_id: spring.warmupPhysics(seconds, target=target + self.offset[strand_id])
                for strand_id, spring in self.springs.items()}

    def stepPhysicsFixed(self, n: int = 1, *, target: float = 0.0) -> dict[str, PhysicsSnapshot]:
        return {strand_id: spring.stepPhysicsFixed(
            n, target=target * self.geometry_factor[strand_id] + self.offset[strand_id])
                for strand_id, spring in self.springs.items()}


class UpperTorsoSecondaryDriver:
    """Profiled deterministic secondary response for the authored torso field."""

    PROFILES = {
        "soft": PhysicsMaterial(stiffness=12.0, damping=5.0),
        "firm_bounce": PhysicsMaterial(stiffness=24.0, damping=3.5),
        "springy": PhysicsMaterial(stiffness=16.0, damping=1.8),
    }

    def __init__(self, *, profile: str = "soft", translation_gain: float = 1.0,
                 angle_gain: float = 0.25, config: dict[str, Any] | None = None) -> None:
        if profile not in self.PROFILES:
            raise ValueError(f"unknown torso response profile: {profile!r}")
        self.translation_gain = float(translation_gain)
        self.angle_gain = float(angle_gain)
        self.spring = DeterministicSpring(material=self.PROFILES[profile], config=config)

    def resetPhysics(self) -> PhysicsSnapshot:
        return self.spring.resetPhysics()

    def warmupPhysics(self, seconds: float | None = None, *, breath: float = 0.0,
                      angle_y: float = 0.0) -> PhysicsSnapshot:
        target = breath * self.translation_gain + angle_y * self.angle_gain
        return self.spring.warmupPhysics(seconds, target=target)

    def stepPhysicsFixed(self, n: int = 1, *, breath: float = 0.0,
                         angle_y: float = 0.0) -> PhysicsSnapshot:
        target = breath * self.translation_gain + angle_y * self.angle_gain
        return self.spring.stepPhysicsFixed(n, target=target)
