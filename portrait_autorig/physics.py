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

__all__ = ["INPUT_MODES", "PhysicsMaterial", "PhysicsSnapshot", "DeterministicSpring",
           "StrandSpringDriver", "UpperTorsoSecondaryDriver",
           "DEFAULT_PHYSICS_CONFIG", "validate_physics_spec"]

DEFAULT_PHYSICS_CONFIG: dict[str, Any] = {
    "update_hz": 60,
    "reference_scale": 768,
    "reset_policy": "rest",
    "warmup_seconds": 0.25,
}
INPUT_MODES = frozenset({"translation", "angle", "velocity", "acceleration", "impulse"})


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
    for field in ("max_body_acceleration", "max_impulse"):
        if field in config:
            try:
                if not math.isfinite(float(config[field])) or float(config[field]) <= 0:
                    errors.append(f"config.{field} must be finite and positive")
            except (TypeError, ValueError):
                errors.append(f"config.{field} must be finite and positive")
    strands = (spec.get("strand_driver") or {}).get("strands", [])
    ids = [str(item.get("strand_id", item.get("id", ""))).strip() for item in strands]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        errors.append("strand_driver.strands require unique strand_id values")
    strand_driver = spec.get("strand_driver") or {}
    if strand_driver.get("input_mode", "translation") not in INPUT_MODES:
        errors.append(f"unsupported strand_driver.input_mode: {strand_driver.get('input_mode')!r}")
    torso = spec.get("upper_torso_driver")
    if torso:
        model = torso.get("model", "legacy_target_v1")
        if model not in {"legacy_target_v1", "inertial_relative_v1"}:
            errors.append(f"unsupported upper_torso_driver.model: {model!r}")
        if torso.get("profile", "soft") not in UpperTorsoSecondaryDriver.PROFILES:
            errors.append(f"unsupported upper_torso_driver.profile: {torso.get('profile')!r}")
        if torso.get("input_mode", "translation") not in INPUT_MODES:
            errors.append(f"unsupported upper_torso_driver.input_mode: {torso.get('input_mode')!r}")
        for field in ("translation_gain", "angle_gain", "velocity_gain", "acceleration_gain",
                      "breath_gain", "pose_bias_gain", "inertia_gain_x", "inertia_gain_y",
                      "velocity_drag_x", "velocity_drag_y", "settle_gain"):
            if field in torso:
                try:
                    if not math.isfinite(float(torso[field])):
                        errors.append(f"upper_torso_driver.{field} must be finite")
                except (TypeError, ValueError):
                    errors.append(f"upper_torso_driver.{field} must be finite")
        try:
            asymmetry = float(torso.get("turn_asymmetry", 0.08))
            if not math.isfinite(asymmetry) or not 0 <= asymmetry <= 1:
                errors.append("upper_torso_driver.turn_asymmetry must be finite and in [0, 1]")
        except (TypeError, ValueError):
            errors.append("upper_torso_driver.turn_asymmetry must be finite and in [0, 1]")
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
                 config: dict[str, Any] | None = None,
                 input_mode: str = "translation") -> None:
        if input_mode not in INPUT_MODES:
            raise ValueError(f"unknown strand input mode: {input_mode!r}")
        base = material or PhysicsMaterial()
        self.springs: dict[str, DeterministicSpring] = {}
        self.geometry_factor: dict[str, float] = {}
        self.offset: dict[str, float] = {}
        self.input_mode = input_mode
        self._previous_input = 0.0
        self._previous_velocity = 0.0
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
        self._previous_input = 0.0
        self._previous_velocity = 0.0
        return {strand_id: spring.resetPhysics() for strand_id, spring in self.springs.items()}

    def warmupPhysics(self, seconds: float | None = None,
                      *, target: float = 0.0) -> dict[str, PhysicsSnapshot]:
        return {strand_id: spring.warmupPhysics(seconds, target=target + self.offset[strand_id])
                for strand_id, spring in self.springs.items()}

    def stepPhysicsFixed(self, n: int = 1, *, target: float = 0.0,
                         input_mode: str | None = None,
                         input_value: float | None = None) -> dict[str, PhysicsSnapshot]:
        mode = self.input_mode if input_mode is None else input_mode
        if mode not in INPUT_MODES:
            raise ValueError(f"unknown strand input mode: {mode!r}")
        source = float(target if input_value is None else input_value)
        dt = 1.0 / next(iter(self.springs.values())).update_hz if self.springs else 1.0 / 60.0
        velocity = (source - self._previous_input) / dt
        acceleration = (velocity - self._previous_velocity) / dt
        interpreted = {"translation": source, "angle": source, "velocity": velocity,
                       "acceleration": acceleration, "impulse": source - self._previous_input}[mode]
        self._previous_input, self._previous_velocity = source, velocity
        return {strand_id: spring.stepPhysicsFixed(
            n, target=interpreted * self.geometry_factor[strand_id] + self.offset[strand_id])
                for strand_id, spring in self.springs.items()}


class UpperTorsoSecondaryDriver:
    """Profiled deterministic secondary response for the authored torso field."""

    PROFILES = {
        "soft": PhysicsMaterial(stiffness=12.0, damping=5.0),
        "firm_bounce": PhysicsMaterial(stiffness=24.0, damping=3.5),
        "springy": PhysicsMaterial(stiffness=16.0, damping=1.8),
    }

    def __init__(self, *, profile: str = "soft", model: str = "legacy_target_v1",
                 translation_gain: float = 1.0, angle_gain: float = 0.25,
                 breath_gain: float = 1.0, pose_bias_gain: float = 0.05,
                 inertia_gain_x: float = 0.015, inertia_gain_y: float = 0.045,
                 velocity_drag_x: float = 0.002, velocity_drag_y: float = 0.006,
                 settle_gain: float = 0.08, turn_asymmetry: float = 0.08,
                 velocity_gain: float = 0.03, acceleration_gain: float = 0.005,
                 left_material_scale: dict[str, Any] | None = None,
                 right_material_scale: dict[str, Any] | None = None,
                 config: dict[str, Any] | None = None,
                 input_mode: str = "translation") -> None:
        if model not in {"legacy_target_v1", "inertial_relative_v1"}:
            raise ValueError(f"unknown torso driver model: {model!r}")
        if profile not in self.PROFILES:
            raise ValueError(f"unknown torso response profile: {profile!r}")
        if input_mode not in INPUT_MODES:
            raise ValueError(f"unknown torso input mode: {input_mode!r}")
        self.translation_gain = float(translation_gain)
        self.angle_gain = float(angle_gain)
        self.model = model
        self.breath_gain = float(breath_gain)
        self.pose_bias_gain = float(pose_bias_gain)
        self.inertia_gain_x = float(inertia_gain_x)
        self.inertia_gain_y = float(inertia_gain_y)
        self.velocity_drag_x = float(velocity_drag_x)
        self.velocity_drag_y = float(velocity_drag_y)
        self.settle_gain = float(settle_gain)
        if not all(math.isfinite(value) for value in (
                self.breath_gain, self.pose_bias_gain, self.inertia_gain_x,
                self.inertia_gain_y, self.velocity_drag_x, self.velocity_drag_y,
                self.settle_gain)):
            raise ValueError("torso inertial coefficients must be finite")
        self.velocity_gain = float(velocity_gain)
        self.acceleration_gain = float(acceleration_gain)
        if not math.isfinite(self.velocity_gain) or not math.isfinite(self.acceleration_gain):
            raise ValueError("velocity/acceleration gains must be finite")
        self.turn_asymmetry = float(turn_asymmetry)
        if not math.isfinite(self.turn_asymmetry) or self.turn_asymmetry < 0 or self.turn_asymmetry > 1:
            raise ValueError("turn_asymmetry must be finite and in [0, 1]")
        self.input_mode = input_mode
        self._previous_input = 0.0
        self._previous_velocity = 0.0
        if (self.model == "inertial_relative_v1" and not left_material_scale
                and not right_material_scale):
            # Keep the two lobes physically independent by default while
            # retaining exact legacy behavior for old manifests.
            left_material_scale = {"stiffness": 0.98, "damping": 1.02, "mass": 1.03}
            right_material_scale = {"stiffness": 1.02, "damping": 0.98, "mass": 0.97}

        def material(scale: dict[str, Any] | None) -> PhysicsMaterial:
            scale = scale or {}
            values = {key: float(scale.get(key, 1.0)) for key in ("stiffness", "damping", "mass")}
            if not all(math.isfinite(value) and value > 0 for value in values.values()):
                raise ValueError("torso material scales must be positive and finite")
            base = self.PROFILES[profile]
            return PhysicsMaterial(base.stiffness * values["stiffness"],
                                   base.damping * values["damping"],
                                   base.mass * values["mass"])
        self.springs = {
            "left": DeterministicSpring(material=material(left_material_scale), config=config),
            "right": DeterministicSpring(material=material(right_material_scale), config=config),
        }
        # Compatibility alias for callers that inspected the old scalar spring.
        self.spring = self.springs["left"]

    def _snapshot(self) -> PhysicsSnapshot:
        left, right = self.springs["left"].snapshot(), self.springs["right"].snapshot()
        return PhysicsSnapshot(
            (left.value + right.value) * 0.5,
            (left.velocity + right.velocity) * 0.5,
            left.degraded or right.degraded,
            left.diagnostic or right.diagnostic,
        )

    def snapshot(self) -> dict[str, Any]:
        left, right = self.springs["left"].snapshot(), self.springs["right"].snapshot()
        aggregate = self._snapshot()
        return {"value": aggregate.value, "velocity": aggregate.velocity,
                "degraded": aggregate.degraded, "diagnostic": aggregate.diagnostic,
                "left": left, "right": right}

    def resetPhysics(self) -> PhysicsSnapshot:
        self._previous_input = 0.0
        self._previous_velocity = 0.0
        for spring in self.springs.values():
            spring.resetPhysics()
        self._previous_input = 0.0
        self._previous_velocity = 0.0
        return self._snapshot()

    def _interpret(self, source: float, mode: str) -> float:
        dt = 1.0 / self.spring.update_hz
        velocity = (source - self._previous_input) / dt
        acceleration = (velocity - self._previous_velocity) / dt
        interpreted = {"translation": source, "angle": source, "velocity": velocity,
                       "acceleration": acceleration, "impulse": source - self._previous_input}[mode]
        self._previous_input, self._previous_velocity = source, velocity
        return interpreted

    def warmupPhysics(self, seconds: float | None = None, *, breath: float = 0.0,
                      angle_y: float = 0.0) -> PhysicsSnapshot:
        target = (breath * self.breath_gain + angle_y * self.pose_bias_gain
                  if self.model == "inertial_relative_v1"
                  else breath * self.translation_gain + angle_y * self.angle_gain)
        self.resetPhysics()
        asym = max(-1.0, min(1.0, angle_y * self.turn_asymmetry))
        left_target, right_target = target * (1.0 - asym), target * (1.0 + asym)
        duration = self.springs["left"].config["warmup_seconds"] if seconds is None else float(seconds)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("warmup seconds must be finite and non-negative")
        count = math.ceil(duration * self.springs["left"].update_hz)
        self.springs["left"].stepPhysicsFixed(count, target=left_target)
        self.springs["right"].stepPhysicsFixed(count, target=right_target)
        return self._snapshot()

    def stepPhysicsFixed(self, n: int = 1, *, breath: float = 0.0,
                         angle_y: float = 0.0, turn_y: float | None = None,
                         equilibrium: float | None = None,
                         body_velocity: tuple[float, float] = (0.0, 0.0),
                         body_acceleration: tuple[float, float] = (0.0, 0.0),
                         impulse: tuple[float, float] = (0.0, 0.0),
                         input_mode: str | None = None,
                         input_value: float | None = None,
                         legacy_body_velocity: float = 0.0,
                         legacy_body_acceleration: float = 0.0) -> PhysicsSnapshot:
        mode = self.input_mode if input_mode is None else input_mode
        if mode not in INPUT_MODES:
            raise ValueError(f"unknown torso input mode: {mode!r}")
        turn = angle_y if turn_y is None else float(turn_y)
        if self.model == "inertial_relative_v1":
            equilibrium_value = (breath * self.breath_gain + turn * self.pose_bias_gain
                                  if equilibrium is None else float(equilibrium))
            def pair(value: tuple[float, float] | float) -> tuple[float, float]:
                if isinstance(value, (int, float)):
                    return 0.0, float(value)
                return float(value[0]), float(value[1])
            vx, vy = pair(body_velocity)
            ax, ay = pair(body_acceleration)
            ix, iy = pair(impulse)
            max_acc = float((self.springs["left"].config or {}).get("max_body_acceleration", 2400.0))
            max_impulse = float((self.springs["left"].config or {}).get("max_impulse", 8.0))
            ax, ay = max(-max_acc, min(max_acc, ax)), max(-max_acc, min(max_acc, ay))
            ix, iy = max(-max_impulse, min(max_impulse, ix)), max(-max_impulse, min(max_impulse, iy))
            force = max(-4.0, min(4.0,
                -ax * self.inertia_gain_x - ay * self.inertia_gain_y
                -vx * self.velocity_drag_x - vy * self.velocity_drag_y + ix + iy))
            asym = max(-1.0, min(1.0, turn * self.turn_asymmetry))
            left_target = (equilibrium_value + force / self.springs["left"].material.stiffness) * (1.0 - asym)
            right_target = (equilibrium_value + force / self.springs["right"].material.stiffness) * (1.0 + asym)
        else:
            legacy_velocity = (float(body_velocity) if isinstance(body_velocity, (int, float))
                               else legacy_body_velocity)
            legacy_acceleration = (float(body_acceleration) if isinstance(body_acceleration, (int, float))
                                   else legacy_body_acceleration)
            source = (breath * self.translation_gain + angle_y * self.angle_gain
                      + legacy_velocity * self.velocity_gain
                      + legacy_acceleration * self.acceleration_gain
                      if input_value is None else float(input_value))
            target = self._interpret(source, mode)
            asym = max(-1.0, min(1.0, angle_y * self.turn_asymmetry))
            left_target, right_target = target * (1.0 - asym), target * (1.0 + asym)
        self.springs["left"].stepPhysicsFixed(n, target=left_target)
        self.springs["right"].stepPhysicsFixed(n, target=right_target)
        return self._snapshot()
