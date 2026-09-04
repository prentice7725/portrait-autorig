import { createPhysicsState, createStrandSpringDriver,
  createUpperTorsoSecondaryDriver } from "./physics.mjs";

const a = createPhysicsState({ stiffness: 20, damping: 5 });
const b = createPhysicsState({ stiffness: 20, damping: 5 });
a.stepPhysicsFixed(30, 1); b.stepPhysicsFixed(30, 1);
if (a.state.value !== b.state.value || a.state.velocity !== b.state.velocity)
  throw new Error("fixed-step physics is not deterministic");

const warm = createPhysicsState({ rest: 2 });
warm.warmupPhysics(0.25, 5);
if (warm.state.value === 2 || warm.state.degraded) throw new Error("warmup failed");

const invalid = createPhysicsState({ stiffness: 1e308, damping: 0 });
const before = invalid.snapshot();
const rolled = invalid.stepPhysicsFixed(1, 1e308);
if (!rolled.degraded || rolled.diagnostic !== "non_finite_rollback"
    || rolled.value !== before.value || rolled.velocity !== before.velocity)
  throw new Error("non-finite rollback failed");

const strands = createStrandSpringDriver([
  { strand_id: "left", length: 2 }, { strand_id: "right", length: 4 },
]);
const outputs = strands.stepPhysicsFixed(10, 1);
if (!outputs.left || !outputs.right || outputs.left.value === outputs.right.value)
  throw new Error("strand driver outputs are not deterministic/per-strand");
const torso = createUpperTorsoSecondaryDriver({ profile: "firm_bounce" });
if (!Number.isFinite(torso.stepPhysicsFixed(5, 1, 0.2).value)) throw new Error("torso driver failed");

console.log("deterministic physics checks passed");
