/*
 * Small, dependency-free correctness oracle for the v0.2 geometry contract.
 *
 * This is intentionally not a second copy of runtime.mjs.  It evaluates the
 * declarative operation list with a pure CPU implementation and is used for
 * parity tests.  The optimized WebGL runtime may change its storage and draw
 * path without changing this reference result.
 */
"use strict";

export const TURN_BASE = 0.015;
export const TURN_SPAN = 0.045;
export const TURN_Y_SCALE = 0.7;

function physicalDistribution(spec) {
  const raw = spec?.physicsDistribution || {};
  if (Number(raw.version ?? 1) < 2 || raw.vertical_floor == null)
    return { horizontalGain: 0.45, verticalGain: 1.0, verticalFloor: 0.35 };
  return {
    horizontalGain: Number(raw.horizontal_gain ?? 0.45),
    verticalGain: Number(raw.vertical_gain ?? 1.0),
    verticalFloor: Math.max(0, Math.min(1, Number(raw.vertical_floor ?? 0.35))),
  };
}

function weightAt(part, index, y) {
  const weight = part.weight || { mode: "constant", value: 1 };
  if (weight.mode !== "gradient_y") return Number(weight.value ?? 1);
  const lo = Number(weight.y_top ?? part.xyxy?.[1] ?? y);
  const hi = Number(weight.y_bottom ?? part.xyxy?.[3] ?? y);
  const t = hi === lo ? 0 : Math.max(0, Math.min(1, (y - lo) / (hi - lo)));
  return Number(weight.top ?? 1) * (1 - t) + Number(weight.bottom ?? 0) * t;
}

function bodySwayInfluence(part) {
  return ["head", "neck", "body", "body_remainder", "hair"].includes(
    part.group || part.spec?.group) ? 1 : 0;
}

/** Evaluate the phase-produced operation list on one part, without DOM/WebGL. */
export function deformReference(part, motion, operations) {
  const rest = part.mesh.rest;
  const live = new Float32Array(rest);
  const pivot = motion.neckPivot || [0, 0];
  const span = Math.max(Number(motion.canvasWidth || 0), Number(motion.canvasHeight || 0));
  const parallax = span * (TURN_BASE + TURN_SPAN * (1 - Number(part.depth ?? part.spec?.depth ?? 0.5)));
  const list = operations || [];
  const squash = motion.squash || motion.blink || { l: 0, r: 0 };
  const side = part.eyeSide;
  const blink = side === "l" ? squash.l : side === "r" ? squash.r : Math.max(squash.l || 0, squash.r || 0);
  for (let i = 0, v = 0; v < rest.length; i++, v += 2) {
    let x = rest[v], y = rest[v + 1];
    const w = weightAt(part, i, y);
    let pendingDx = 0, pendingDy = 0;
    const flush = () => { x += pendingDx * w; y += pendingDy * w; pendingDx = 0; pendingDy = 0; };
    for (const operation of list) {
      switch (operation.kind) {
        case "body_sway": {
          const sway = motion.bodySwayPosition || [0, 0];
          const influence = bodySwayInfluence(part);
          x += Number(sway[0] || 0) * influence;
          y += Number(sway[1] || 0) * influence;
          break;
        }
        case "eye_fold":
          if (part.isEye && blink > 0) {
            const lid = Number(part.openTop) + Number(motion.lidRatio ?? 0.85) *
              (Number(part.openBottom) - Number(part.openTop));
            const floor = part.isLid ? Number(motion.lidThickness ?? 0.18) : 0;
            y = lid + (y - lid) * (1 - blink * (1 - floor));
          }
          break;
        case "parallax_turn":
          pendingDx = Number(motion.turnX || 0) * parallax;
          pendingDy = Number(motion.turnY || 0) * parallax * TURN_Y_SCALE;
          break;
        case "weighted_rotation": {
          flush();
          const angle = Number(motion.tiltRad || 0) * w;
          const cos = Math.cos(angle), sin = Math.sin(angle);
          const dx = x - pivot[0], dy = y - pivot[1];
          x = pivot[0] + dx * cos - dy * sin;
          y = pivot[1] + dx * sin + dy * cos;
          break;
        }
        case "continuous_field":
          flush();
          if (motion.breath) {
            const lo = Number(motion.breathTop ?? 0), hi = Number(motion.breathBottom ?? motion.canvasHeight ?? y);
            const ramp = hi === lo ? 0 : Math.max(0, Math.min(1, (hi - y) / (hi - lo)));
            y -= Number(motion.breath) * Number(motion.breathAmp || 0) * ramp;
            if (part.group === "body" && motion.chestX) {
              const cx = Number(motion.chestCx ?? motion.canvasWidth / 2);
              x = cx + (x - cx) * (1 + Number(motion.breath) * Number(motion.chestX) * ramp);
            }
          }
          break;
        case "local_soft_field": {
          const sm = motion.softMorph;
          if (part.softMorph && sm?.enabled) {
            const torso = motion.physics?.torso || {};
            const mean = (Number(torso.left?.value ?? torso.value ?? 0)
              + Number(torso.right?.value ?? torso.value ?? 0)) * 0.5;
            const asym = Number(motion.qaAsymmetry ?? 1);
            const leftPhysics = mean + (Number(torso.left?.value ?? torso.value ?? 0) - mean) * asym;
            const rightPhysics = mean + (Number(torso.right?.value ?? torso.value ?? 0) - mean) * asym;
            const leftVelocity = Number(torso.left?.velocity ?? torso.velocity ?? 0);
            const rightVelocity = Number(torso.right?.velocity ?? torso.velocity ?? 0);
            const settleGain = Number(torso.settleGain ?? 0.08) * Number(motion.settleMultiplier ?? 1);
            const physicalPx = torso.model === "inertial_relative_v2";
            const baseAmount = Number(sm.strength ?? 0) * Number(sm.morph ?? 0);
            const leftAmount = physicalPx ? baseAmount : baseAmount + leftPhysics;
            const rightAmount = physicalPx ? baseAmount : baseAmount + rightPhysics;
            const wl = Number(part.softMorph.left?.[i] ?? 0), wr = Number(part.softMorph.right?.[i] ?? 0);
            if (wl > 0 || wr > 0) {
              const horizontal = Number(sm.horizontalPx ?? 0);
              const vertical = Number(sm.verticalPx ?? 0);
              const maxWeight = Math.max(wl, wr), total = wl + wr;
              const volume = total > 0 ? (leftAmount * wl + rightAmount * wr) / total : 0;
              const velocity = total > 0 ? (leftVelocity * wl + rightVelocity * wr) / total : 0;
              x += horizontal * (rightAmount * wr - leftAmount * wl);
              if (physicalPx) {
                const distribution = physicalDistribution(sm);
                const horizontalGain = distribution.horizontalGain;
                const verticalGain = distribution.verticalGain;
                const verticalFloor = distribution.verticalFloor;
                const qVolume = total > 0 ? (leftPhysics * wl + rightPhysics * wr) / total : 0;
                const qVelocity = total > 0 ? (leftVelocity * wl + rightVelocity * wr) / total : 0;
                x += horizontalGain * (rightPhysics * wr - leftPhysics * wl);
                const verticalShape = verticalFloor
                  + (1 - verticalFloor) * Number(part.softMorph.lowerBias?.[i] ?? 0);
                y += (qVolume * verticalGain + qVelocity * Number(torso.settleTimeScaleS ?? 0.03))
                  * maxWeight * verticalShape;
              } else {
                y += vertical * (volume + velocity * settleGain) * maxWeight
                  * Number(part.softMorph.lowerBias?.[i] ?? 0);
              }
            }
          }
          break;
        }
        default:
          // Unsupported optional operations are intentionally inert in the
          // oracle; parity tests list the operations they cover explicitly.
          break;
      }
    }
    flush();
    live[v] = x; live[v + 1] = y;
  }
  return live;
}

export function applyBoundaryStitchesReference(parts, constraints = []) {
  const byName = new Map(parts.map((part) => [part.name || part.spec?.name, part]));
  for (const constraint of constraints) {
    if (constraint.kind !== "boundary_stitch") continue;
    const tolerance = Number(constraint.tolerance_px ?? 0);
    for (const group of constraint.groups || []) {
      const members = (group.members || []).map((member) => ({
        member,
        part: byName.get(member.part),
      })).filter((item) => item.part?.mesh?.live && item.member.vertex >= 0);
      if (members.length < 2) continue;
      const points = members.map(({ part, member }) => [part.mesh.live[member.vertex * 2], part.mesh.live[member.vertex * 2 + 1]]);
      const maxDistance = Math.max(...points.map((point) => Math.max(...points.map((other) =>
        Math.hypot(point[0] - other[0], point[1] - other[1])))));
      if (maxDistance <= tolerance) continue;
      const weights = members.map(({ member }) => Number(member.weight ?? 1));
      const total = weights.reduce((sum, value) => sum + value, 0) || 1;
      const target = points.reduce((sum, point, index) => [sum[0] + point[0] * weights[index] / total,
        sum[1] + point[1] * weights[index] / total], [0, 0]);
      members.forEach(({ part, member }) => {
        part.mesh.live[member.vertex * 2] = target[0];
        part.mesh.live[member.vertex * 2 + 1] = target[1];
      });
    }
  }
}
