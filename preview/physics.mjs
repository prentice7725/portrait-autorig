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
  const resetPhysics = () => Object.fromEntries([...springs].map(([id, item]) => [id, item.physics.resetPhysics()]));
  const warmupPhysics = (seconds, target = 0) => Object.fromEntries([...springs].map(([id, item]) =>
    [id, item.physics.warmupPhysics(seconds, target + item.offset)]));
  const stepPhysicsFixed = (count = 1, target = 0) => Object.fromEntries([...springs].map(([id, item]) =>
    [id, item.physics.stepPhysicsFixed(count, target * item.geometry + item.offset)]));
  return { resetPhysics, warmupPhysics, stepPhysicsFixed };
}

export function createUpperTorsoSecondaryDriver({ profile = "soft", translationGain = 1,
                                                  angleGain = 0.25, config = {} } = {}) {
  const materials = { soft: [12, 5], firm_bounce: [24, 3.5], springy: [16, 1.8] };
  if (!materials[profile]) throw new Error(`unknown torso response profile: ${profile}`);
  const spring = createPhysicsState({ stiffness: materials[profile][0], damping: materials[profile][1], config });
  const target = (breath, angleY) => Number(breath) * translationGain + Number(angleY) * angleGain;
  return {
    resetPhysics: () => spring.resetPhysics(),
    warmupPhysics: (seconds, breath = 0, angleY = 0) => spring.warmupPhysics(seconds, target(breath, angleY)),
    stepPhysicsFixed: (count = 1, breath = 0, angleY = 0) => spring.stepPhysicsFixed(count, target(breath, angleY)),
  };
}
