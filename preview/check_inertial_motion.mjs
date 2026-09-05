// P2.2 inertial driver smoke/regression checks.
import { createUpperTorsoSecondaryDriver } from "./physics.mjs";

const driver = createUpperTorsoSecondaryDriver({
  model: "inertial_relative_v1", breathGain: 0, poseBiasGain: 0,
  inertiaGainY: 1, velocityDragY: 0,
});
const kick = driver.stepPhysicsFixed(1, 0, 0, 0, 1, 0, 0, 0, 0);
if (!(kick.value < 0)) throw new Error("positive body acceleration must create a negative inertial force");
if (kick.left.value === kick.right.value)
  throw new Error("inertial lobes must remain independently materialized");

const equilibrium = createUpperTorsoSecondaryDriver({
  model: "inertial_relative_v1", breathGain: 1, poseBiasGain: 0,
  inertiaGainY: 0, velocityDragY: 0,
});
equilibrium.warmupPhysics(0, 0, 0);
const rest = equilibrium.stepPhysicsFixed(1, 0, 0).value;
const breath = equilibrium.stepPhysicsFixed(1, 1, 0).value;
if (!(breath > rest)) throw new Error("breath equilibrium was not separated from external force");

console.log("inertial motion checks passed");
