// A fixed-tick driver must produce the same state regardless of render FPS.
import { createUpperTorsoSecondaryDriver } from "./physics.mjs";

function run(fps) {
  const driver = createUpperTorsoSecondaryDriver({
    model: "inertial_relative_v2", breathDisplacementPx: 0.25, inertiaCouplingY: 0.2,
  });
  const tick = 1 / 60, frame = 1 / fps;
  let accumulator = 0, simTime = 0;
  for (let elapsed = 0; elapsed < 1 - 1e-9; elapsed += frame) {
    accumulator += frame;
    while (accumulator + 1e-12 >= tick) {
      simTime += tick;
      const t = simTime;
      const velocity = Math.cos(t * 1.7);
      const acceleration = -1.7 * Math.sin(t * 1.7);
      driver.stepPhysicsFixed(1, 0.5, 0, 0, velocity, 0, 0, acceleration, 0);
      accumulator -= tick;
    }
  }
  return driver.stepPhysicsFixed(0);
}

const reference = run(60);
for (const fps of [30, 120]) {
  const sample = run(fps);
  if (Math.abs(sample.value - reference.value) > 1e-9
      || Math.abs(sample.velocity - reference.velocity) > 1e-9)
    throw new Error(`fixed-tick parity failed at ${fps} FPS`);
}
console.log("motion framerate parity passed");
