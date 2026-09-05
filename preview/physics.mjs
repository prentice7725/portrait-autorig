/* Deterministic P2 spring core.  Character drivers own targets/materials;
 * this module owns fixed ticks, reset/warm-up, and finite-state rollback. */

export const DEFAULT_PHYSICS_CONFIG = Object.freeze({
  update_hz: 60, reference_scale: 768, reset_policy: "rest", warmup_seconds: 0.25,
});

export function createPhysicsState({ rest = 0, stiffness = 18, damping = 6, mass = 1,
                                      config = {} } = {}) {
  const options = { ...DEFAULT_PHYSICS_CONFIG, ...config };
  options.update_hz = Number(options.update_hz);
  if (!Number.isFinite(rest) || !Number.isFinite(stiffness) || !Number.isFinite(damping)
      || !Number.isFinite(mass) || stiffness < 0 || damping < 0 || mass <= 0
      || !Number.isInteger(options.update_hz) || options.update_hz <= 0) {
    throw new Error("invalid physics configuration");
  }
  const state = { value: rest, velocity: 0, rest, stiffness, damping, mass,
    config: options, degraded: false, diagnostic: null,
    lastGood: { value: rest, velocity: 0 } };
  const snapshot = () => ({ value: state.value, velocity: state.velocity,
    degraded: state.degraded, diagnostic: state.diagnostic });
  const resetPhysics = (value = state.rest) => {
    if (!Number.isFinite(value)) throw new Error("reset value must be finite");
    state.value = value; state.velocity = 0; state.degraded = false; state.diagnostic = null;
    state.lastGood = { value, velocity: 0 }; return snapshot();
  };
  const stepPhysicsFixed = (count = 1, target = state.rest) => {
    if (!Number.isInteger(count) || count < 0 || !Number.isFinite(target))
      throw new Error("invalid fixed step");
    const dt = 1 / state.config.update_hz;
    for (let i = 0; i < count; i++) {
      const acceleration = ((target - state.value) * state.stiffness
        - state.velocity * state.damping) / state.mass;
      state.velocity += acceleration * dt;
      state.value += state.velocity * dt;
      if (!Number.isFinite(state.value) || !Number.isFinite(state.velocity)) {
        state.value = state.lastGood.value; state.velocity = state.lastGood.velocity;
        state.degraded = true; state.diagnostic = "non_finite_rollback"; return snapshot();
      }
      state.lastGood = { value: state.value, velocity: state.velocity };
    }
    return snapshot();
  };
  const warmupPhysics = (seconds = state.config.warmup_seconds, target = state.rest) => {
    if (!Number.isFinite(seconds) || seconds < 0) throw new Error("invalid warmup seconds");
    resetPhysics();
    return stepPhysicsFixed(Math.ceil(seconds * state.config.update_hz), target);
  };
  return { state, snapshot, resetPhysics, warmupPhysics, stepPhysicsFixed };
}

export function createStrandSpringDriver(strands, options = {}) {
  const base = { stiffness: options.stiffness ?? 18, damping: options.damping ?? 6,
    mass: options.mass ?? 1, config: options.config || {} };
  const inputMode = options.input_mode || "translation";
  if (!["translation", "angle", "velocity", "acceleration", "impulse"].includes(inputMode))
    throw new Error(`unknown strand input mode: ${inputMode}`);
  const springs = new Map();
  for (const strand of strands || []) {
    const id = String(strand.strand_id ?? strand.id ?? "");
    if (!id || springs.has(id)) throw new Error("each strand needs a unique strand_id");
    const length = Number(strand.length ?? 1), mass = Number(strand.mass ?? 1);
    const geometry = Number(strand.geometry_factor ?? 1);
    if (!(length > 0 && mass > 0 && geometry > 0)) throw new Error("invalid strand material");
    let hash = 0; for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
    const offset = ((hash % 1000) / 999 - 0.5) * 0.02;
    springs.set(id, { geometry, offset, physics: createPhysicsState({
      stiffness: base.stiffness / Math.max(1, length), damping: base.damping,
      mass: base.mass * mass, config: base.config,
    }) });
  }
  let previousInput = 0, previousVelocity = 0;
  const resetPhysics = () => {
    previousInput = 0; previousVelocity = 0;
    return Object.fromEntries([...springs].map(([id, item]) => [id, item.physics.resetPhysics()]));
  };
  const stepPhysicsFixed = (count = 1, target = 0) => {
    const dt = 1 / (Number(base.config.update_hz || 60));
    const velocity = (target - previousInput) / dt;
    const acceleration = (velocity - previousVelocity) / dt;
    const interpreted = { translation: target, angle: target, velocity,
      acceleration, impulse: target - previousInput }[inputMode];
    previousInput = target; previousVelocity = velocity;
    return Object.fromEntries([...springs].map(([id, item]) =>
      [id, item.physics.stepPhysicsFixed(count, interpreted * item.geometry + item.offset)]));
  };
  const warmupPhysics = (seconds, target = 0) => {
    resetPhysics();
    return Object.fromEntries([...springs].map(([id, item]) =>
      [id, item.physics.warmupPhysics(seconds, target + item.offset)]));
  };
  return { resetPhysics, warmupPhysics, stepPhysicsFixed };
}

export function createUpperTorsoSecondaryDriver({ profile = "soft", model = "legacy_target_v1",
                                                  translationGain = 1, angleGain = 0.25,
                                                  breathGain = 1, poseBiasGain = 0.05,
                                                  inertiaGainX = 0.015, inertiaGainY = 0.045,
                                                  velocityDragX = 0.002, velocityDragY = 0.006,
                                                  settleGain = 0.08, turnAsymmetry = 0.08,
                                                  velocityGain = 0.03, accelerationGain = 0.005,
                                                  leftMaterialScale = {}, rightMaterialScale = {},
                                                  inputMode = "translation", config = {} } = {}) {
  const materials = { soft: [12, 5], firm_bounce: [24, 3.5], springy: [16, 1.8] };
  if (!materials[profile]) throw new Error(`unknown torso response profile: ${profile}`);
  if (!["legacy_target_v1", "inertial_relative_v1"].includes(model))
    throw new Error(`unknown torso driver model: ${model}`);
  if (!["translation", "angle", "velocity", "acceleration", "impulse"].includes(inputMode))
    throw new Error(`unknown torso input mode: ${inputMode}`);
  if (!Number.isFinite(turnAsymmetry) || turnAsymmetry < 0 || turnAsymmetry > 1)
    throw new Error("turnAsymmetry must be finite and in [0, 1]");
  if (!Number.isFinite(velocityGain) || !Number.isFinite(accelerationGain))
    throw new Error("torso velocity/acceleration gains must be finite");
  // New inertial drivers get a tiny deterministic material asymmetry even
  // when the manifest omits optional scales. Legacy manifests remain exact.
  if (model === "inertial_relative_v1" && Object.keys(leftMaterialScale).length === 0 &&
      Object.keys(rightMaterialScale).length === 0) {
    leftMaterialScale = { stiffness: 0.98, damping: 1.02, mass: 1.03 };
    rightMaterialScale = { stiffness: 1.02, damping: 0.98, mass: 0.97 };
  }
  const scale = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const scales = {
    left: { stiffness: scale(leftMaterialScale.stiffness, 1), damping: scale(leftMaterialScale.damping, 1), mass: scale(leftMaterialScale.mass, 1) },
    right: { stiffness: scale(rightMaterialScale.stiffness, 1), damping: scale(rightMaterialScale.damping, 1), mass: scale(rightMaterialScale.mass, 1) },
  };
  for (const side of ["left", "right"])
    if (!(scales[side].stiffness > 0 && scales[side].damping > 0 && scales[side].mass > 0))
      throw new Error("torso material scales must be positive");
  const springs = {
    left: createPhysicsState({ stiffness: materials[profile][0] * scales.left.stiffness,
      damping: materials[profile][1] * scales.left.damping,
      mass: scales.left.mass, config }),
    right: createPhysicsState({ stiffness: materials[profile][0] * scales.right.stiffness,
      damping: materials[profile][1] * scales.right.damping,
      mass: scales.right.mass, config }),
  };
  let previousInput = 0, previousVelocity = 0;
  const target = (breath, angleY, bodyVelocity = 0, bodyAcceleration = 0) =>
    Number(breath) * translationGain + Number(angleY) * angleGain
    + Number(bodyVelocity) * velocityGain + Number(bodyAcceleration) * accelerationGain;
  const clamp = (value, limit) => Math.max(-limit, Math.min(limit, value));
  const inertialTarget = (breath, angleY, velocityX, velocityY, accelerationX, accelerationY,
                          impulseX, impulseY, spring) => {
    const maxAcceleration = Number(config.max_body_acceleration ?? 2400);
    const maxImpulse = Number(config.max_impulse ?? 8);
    accelerationX = clamp(Number(accelerationX), maxAcceleration);
    accelerationY = clamp(Number(accelerationY), maxAcceleration);
    impulseX = clamp(Number(impulseX), maxImpulse);
    impulseY = clamp(Number(impulseY), maxImpulse);
    const equilibrium = Number(breath) * breathGain + Number(angleY) * poseBiasGain;
    const force = clamp(-Number(accelerationX) * inertiaGainX
      - Number(accelerationY) * inertiaGainY
      - Number(velocityX) * velocityDragX
      - Number(velocityY) * velocityDragY
      + Number(impulseX) + Number(impulseY), 4);
    return equilibrium + force / Math.max(1e-6, spring.state.stiffness);
  };
  const enforceLimits = (spring) => {
    const maxDisplacement = Number(config.max_relative_displacement ?? 4);
    const maxVelocity = Number(config.max_lobe_velocity ?? 12);
    if (Math.abs(spring.state.value) > maxDisplacement) {
      spring.state.value = clamp(spring.state.value, maxDisplacement);
      spring.state.velocity = clamp(spring.state.velocity, maxVelocity);
      spring.state.degraded = true; spring.state.diagnostic = "relative_displacement_clamp";
    }
    if (Math.abs(spring.state.velocity) > maxVelocity) {
      spring.state.velocity = clamp(spring.state.velocity, maxVelocity);
      spring.state.degraded = true; spring.state.diagnostic = "lobe_velocity_clamp";
    }
  };
  const snapshot = () => {
    const left = springs.left.snapshot(), right = springs.right.snapshot();
    return { value: (left.value + right.value) * 0.5,
      velocity: (left.velocity + right.velocity) * 0.5,
      degraded: left.degraded || right.degraded,
      diagnostic: left.diagnostic || right.diagnostic, settleGain, left, right };
  };
  return {
    resetPhysics: () => {
      previousInput = 0; previousVelocity = 0;
      springs.left.resetPhysics(); springs.right.resetPhysics();
      return snapshot();
    },
    warmupPhysics: (seconds, breath = 0, angleY = 0) => {
      const source = model === "inertial_relative_v1"
        ? Number(breath) * breathGain + Number(angleY) * poseBiasGain : target(breath, angleY);
      const asym = Math.max(-1, Math.min(1, angleY * turnAsymmetry));
      const count = Math.ceil((seconds ?? config.warmup_seconds ?? DEFAULT_PHYSICS_CONFIG.warmup_seconds)
                              * Number(config.update_hz || 60));
      // Warm-up is a standalone state transition: do not carry velocity or
      // acceleration history into the first post-warmup fixed tick.
      previousInput = 0; previousVelocity = 0;
      springs.left.resetPhysics(); springs.right.resetPhysics();
      springs.left.stepPhysicsFixed(count, source * (1 - asym));
      springs.right.stepPhysicsFixed(count, source * (1 + asym));
      enforceLimits(springs.left); enforceLimits(springs.right);
      return snapshot();
    },
    stepPhysicsFixed: (count = 1, breath = 0, angleY = 0,
                       bodyVelocity = 0, bodyAcceleration = 0,
                       bodyVelocityX = 0, bodyAccelerationX = 0,
                       impulseY = 0, impulseX = 0) => {
      const asym = Math.max(-1, Math.min(1, angleY * turnAsymmetry));
      let leftTarget, rightTarget;
      if (model === "inertial_relative_v1") {
        // Inertial input is already expressed in px/s and px/s². It must not
        // pass through the legacy source reinterpretation/history channel.
        leftTarget = inertialTarget(breath, angleY, bodyVelocityX, bodyVelocity,
          bodyAccelerationX, bodyAcceleration, impulseX, impulseY, springs.left) * (1 - asym);
        rightTarget = inertialTarget(breath, angleY, bodyVelocityX, bodyVelocity,
          bodyAccelerationX, bodyAcceleration, impulseX, impulseY, springs.right) * (1 + asym);
      } else {
        const source = target(breath, angleY, bodyVelocity, bodyAcceleration);
        const dt = 1 / Number(config.update_hz || 60);
        const velocity = (source - previousInput) / dt;
        const acceleration = (velocity - previousVelocity) / dt;
        const interpreted = { translation: source, angle: source, velocity,
          acceleration, impulse: source - previousInput }[inputMode];
        previousInput = source; previousVelocity = velocity;
        leftTarget = interpreted * (1 - asym);
        rightTarget = interpreted * (1 + asym);
      }
      // Targets already include the side asymmetry.  Applying the factor a
      // second time here would square it and make the authored turn bias
      // stronger than the manifest contract (and diverge from Python).
      springs.left.stepPhysicsFixed(count, leftTarget);
      springs.right.stepPhysicsFixed(count, rightTarget);
      enforceLimits(springs.left); enforceLimits(springs.right);
      return snapshot();
    },
  };
}
