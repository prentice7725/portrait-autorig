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

// Body moves for a short pulse, then stops. The driver must see the resulting
// acceleration pulse, follow through after the stop, and settle back to rest.
const follow = createUpperTorsoSecondaryDriver({
  model: "inertial_relative_v1", breathGain: 0, poseBiasGain: 0,
  inertiaGainY: 0.5, velocityDragY: 0, profile: "springy",
});
let previousVelocity = 0;
const values = [];
for (let tick = 0; tick < 240; tick++) {
  const velocity = tick < 12 ? 3 : 0;
  const acceleration = (velocity - previousVelocity) * 60;
  values.push(follow.stepPhysicsFixed(1, 0, 0, velocity, acceleration, 0, 0, 0, 0).value);
  previousVelocity = velocity;
}
if (!(values[12] < 0 && values.slice(13).some((value) => value > 0)))
  throw new Error("body stop did not produce inertial follow-through/overshoot");
if (Math.abs(values.at(-1)) > 1e-3)
  throw new Error("inertial follow-through did not settle near rest");

const physical = createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
  breathDisplacementPx: 0.8, inertiaCouplingY: 0.22, dragCouplingY: 0.02 });
physical.setRelativeDisplacement(4);
if (physical.stepPhysicsFixed(0).units !== "px"
    || Math.abs(physical.stepPhysicsFixed(0).left.value - 4) > 0.01)
  throw new Error("inertial_relative_v2 did not expose pixel-unit q");

const idleLag = createUpperTorsoSecondaryDriver({ model: "inertial_relative_v2",
  breathDisplacementPx: 0, poseBiasPx: 0, inertiaCouplingY: 0, dragCouplingY: 0,
  lagSecondsY: 0.25, idleLagMaxPx: 0.8 });
for (let tick = 0; tick < 120; tick++) idleLag.stepPhysicsFixed(1, 0, 0, 1, 0);
if (!(idleLag.stepPhysicsFixed(0).value < -0.2))
  throw new Error("slow body velocity did not produce a visible relative lag target");
console.log(`idle velocity lag reached ${idleLag.stepPhysicsFixed(0).value.toFixed(2)}px`);

console.log("inertial motion checks passed");
