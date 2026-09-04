// Deterministic profile tuning report.  This is a bounded golden check, not a
// claim that one character's art has a universal best material.
import { createUpperTorsoSecondaryDriver } from "./physics.mjs";

const profiles = ["soft", "firm_bounce", "springy"];
const report = {};
for (const profile of profiles) {
  const driver = createUpperTorsoSecondaryDriver({ profile });
  driver.resetPhysics();
  const values = [];
  for (let i = 0; i < 120; i++) values.push(driver.stepPhysicsFixed(1, 1, 0).value);
  const peak = Math.max(...values), final = values.at(-1);
  const settle = values.findIndex((value, index) => index > 30
    && values.slice(index).every((later) => Math.abs(later - 1) < 0.05));
  report[profile] = { peak: Number(peak.toFixed(6)), final: Number(final.toFixed(6)),
    overshoot: Number(Math.max(0, peak - 1).toFixed(6)), settle_frames: settle < 0 ? null : settle };
}
if (!Object.values(report).every((item) => Number.isFinite(item.final)
    && item.settle_frames !== null && item.overshoot < 1))
  throw new Error("profile tuning escaped the bounded production envelope");
console.log(JSON.stringify(report, null, 2));
