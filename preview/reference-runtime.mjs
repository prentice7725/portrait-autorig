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
  const version = Number(raw.version ?? 1);
  if (version >= 3) {
    return {
      version: 3,
      carrierGain: Number(raw.carrier_gain ?? 1.0),
      volumeGain: Number(raw.volume_gain ?? 0.55),
      sagGain: Number(raw.sag_gain ?? 0.85),
      followGainS: Number(raw.follow_gain_s ?? 0.035),
      shearGainXS: Number(raw.shear_gain_x_s ?? 0.018),
      shearGainYS: Number(raw.shear_gain_y_s ?? 0.012),
      compressionGain: Number(raw.compression_gain ?? 0.20),
      upperAnchorStart: Number(raw.upper_anchor_start ?? -0.75),
      upperAnchorEnd: Number(raw.upper_anchor_end ?? -0.15),
      lowerStart: Number(raw.lower_start ?? 0.0),
      lowerPower: Number(raw.lower_power ?? 1.7),
      tangentRatio: Number(raw.tangent_ratio ?? 0.15),
      maxFollowPx: Number(raw.max_follow_px ?? 3.0),
      maxShearPx: Number(raw.max_shear_px ?? 2.0),
    };
  }
  if (version < 2 || raw.vertical_floor == null)
    return { version: 1, horizontalGain: 0.45, verticalGain: 1.0, verticalFloor: 0.35 };
  return {
    version: 2,
    horizontalGain: Number(raw.horizontal_gain ?? 0.45),
    verticalGain: Number(raw.vertical_gain ?? 1.0),
    verticalFloor: Math.max(0, Math.min(1, Number(raw.vertical_floor ?? 0.35))),
  };
}

function smoothstep(edge0, edge1, x) {
  if (edge1 === edge0) return x < edge0 ? 0 : 1;
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/**
 * P2.5 (directive #61): an independently-written re-derivation of the
 * runtime.mjs basis fields (#53-59), computed on the fly from raw lobe
 * geometry (`part.softMorph.geometry`) rather than sharing runtime.mjs's
 * precomputed Float32Arrays -- the whole point of a second implementation is
 * that it can disagree with the optimized one if either has a bug.
 */
function chestBasisFieldsAt(lobe, x, y, distribution) {
  const u = (x - lobe.cx) / lobe.rx;
  const v = (y - lobe.cy) / lobe.ry;
  const r2 = u * u + v * v;
  const r = Math.sqrt(r2);
  const coreBase = Math.max(0, Math.min(1, 1 - r2));
  const core = coreBase * coreBase;
  const upperRelease = smoothstep(distribution.upperAnchorStart, distribution.upperAnchorEnd, v);
  const lowerBase = smoothstep(distribution.lowerStart, 1.0, v);
  const lower = Math.pow(lowerBase, distribution.lowerPower);
  const middle = smoothstep(-0.55, -0.10, v) * (1 - smoothstep(0.35, 0.85, v));
  const eps = 1e-6;
  const tx = -v / Math.max(r, eps);
  const ty = u / Math.max(r, eps);
  return {
    carrierX: 0,
    carrierY: core * upperRelease,
    volumeX: u * core * upperRelease,
    volumeY: v * core * upperRelease * 0.30,
    sagX: u * lower * core * 0.10,
    sagY: lower * core,
    followX: tx * lower * core * distribution.tangentRatio,
    followY: lower * core,
    shearXX: -lower * core,
    shearXY: ty * lower * core * 0.15,
    shearYX: 0,
    shearYY: -lower * core,
    compressionX: -u * middle * core,
    compressionY: -Math.sign(v) * middle * core * 0.15,
  };
}

/** Composite one lobe's basis fields into a pixel delta (directive #15, #26),
 *  with the same Follow/Shear magnitude clamp as runtime.mjs's
 *  `applyChestBasis` (independently written, see `chestBasisFieldsAt`). */
function applyChestBasisFields(fields, q, springV, bodyVx, bodyVy, distribution) {
  const carrierX = q * fields.carrierX * distribution.carrierGain;
  const carrierY = q * fields.carrierY * distribution.carrierGain;
  const volumeX = q * fields.volumeX * distribution.volumeGain;
  const volumeY = q * fields.volumeY * distribution.volumeGain;
  const sagX = q * fields.sagX * distribution.sagGain;
  const sagY = q * fields.sagY * distribution.sagGain;

  let followX = springV * fields.followX * distribution.followGainS;
  let followY = springV * fields.followY * distribution.followGainS;
  const followMag = Math.hypot(followX, followY);
  if (followMag > distribution.maxFollowPx && followMag > 0) {
    const scale = distribution.maxFollowPx / followMag;
    followX *= scale; followY *= scale;
  }

  let shearX = bodyVx * fields.shearXX * distribution.shearGainXS
    + bodyVy * fields.shearYX * distribution.shearGainYS;
  let shearY = bodyVx * fields.shearXY * distribution.shearGainXS
    + bodyVy * fields.shearYY * distribution.shearGainYS;
  const shearMag = Math.hypot(shearX, shearY);
  if (shearMag > distribution.maxShearPx && shearMag > 0) {
    const scale = distribution.maxShearPx / shearMag;
    shearX *= scale; shearY *= scale;
  }

  const compressionX = q * fields.compressionX * distribution.compressionGain;
  const compressionY = q * fields.compressionY * distribution.compressionGain;

  return [
    carrierX + volumeX + sagX + followX + shearX + compressionX,
    carrierY + volumeY + sagY + followY + shearY + compressionY,
  ];
}

function chestParametricDelta(part, index, motion, spec) {
  const binding = spec?.binding || {};
  const cells = binding.vertex_cells?.[index], uv = binding.vertex_uv?.[index];
  const influence = Number(binding.vertex_influence?.[index] ?? 0);
  if (!cells || !uv || influence <= 0) return [0, 0];
  const cols = Number(spec.cage?.cols || 6), rows = Number(spec.cage?.rows || 4);
  const cx = Math.max(0, Math.min(cols - 2, Number(cells[0]) || 0));
  const cy = Math.max(0, Math.min(rows - 2, Number(cells[1]) || 0));
  const u = Math.max(0, Math.min(1, Number(uv[0]) || 0));
  const v = Math.max(0, Math.min(1, Number(uv[1]) || 0));
  const params = motion.parameters || {};
  const x = Math.max(-1, Math.min(1, Number(params[spec.parameters?.x || "ParamBustX"] || 0)));
  const y = Math.max(-1, Math.min(1, Number(params[spec.parameters?.y || "ParamBustY"] || 0)));
  const out = [0, 0], zero = [0, 0], keyforms = spec.keyforms || {};
  const add = (name, amount) => {
    const pose = keyforms[name] || [];
    const at = (row, col) => pose[row * cols + col] || zero;
    const p00 = at(cy, cx), p10 = at(cy, cx + 1), p01 = at(cy + 1, cx), p11 = at(cy + 1, cx + 1);
    const a = (1 - u) * (1 - v), b = u * (1 - v), c = (1 - u) * v, d = u * v;
    out[0] += amount * (a * Number(p00[0] || 0) + b * Number(p10[0] || 0) + c * Number(p01[0] || 0) + d * Number(p11[0] || 0));
    out[1] += amount * (a * Number(p00[1] || 0) + b * Number(p10[1] || 0) + c * Number(p01[1] || 0) + d * Number(p11[1] || 0));
  };
  if (x < 0) add("bust_x_neg", -x); else add("bust_x_pos", x);
  if (y < 0) add("bust_y_neg", -y); else add("bust_y_pos", y);
  return [out[0] * influence, out[1] * influence];
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
  const hasP3 = (candidate) => list.some((operation) => {
    if (operation.kind !== "chest_parametric_deformer") return false;
    const config = operation.config || {};
    return (config.target_instance == null
      || config.target_instance === candidate.name
      || config.target_instance === candidate.source_instance_id
      || config.target_part === candidate.name)
      && (config.target_tag == null || config.target_tag === (candidate.tag || candidate.spec?.tag));
  });
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
        case "chest_parametric_deformer": {
          flush();
          const config = operation.config || {};
          const targetMatches = (config.target_instance == null
            || config.target_instance === part.name
            || config.target_instance === part.source_instance_id
            || config.target_part === part.name)
            && (config.target_tag == null || config.target_tag === (part.tag || part.spec?.tag));
          if (targetMatches && (part.tag === "topwear" || part.spec?.tag === "topwear"
              || part.tag === "topwear_with_arms" || part.tag === "topwear_with_handwear")) {
            const delta = chestParametricDelta(part, i, motion, config);
            x += delta[0]; y += delta[1];
          }
          break;
        }
        case "local_soft_field": {
          const sm = motion.softMorph;
          if (!hasP3(part) && part.softMorph && sm?.enabled) {
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
                if (distribution.version >= 3 && part.softMorph.geometry) {
                  // P2.5 (directive #5, #15-16): unnormalized weighted blend
                  // of each lobe's independently-recomputed basis composite.
                  const bodyVx = Number(motion.bodyVelocityX ?? 0);
                  const bodyVy = Number(motion.bodyVelocityY ?? 0);
                  const dl = wl > 0
                    ? applyChestBasisFields(
                        chestBasisFieldsAt(part.softMorph.geometry.left, rest[v], rest[v + 1], distribution),
                        leftPhysics, leftVelocity, bodyVx, bodyVy, distribution)
                    : [0, 0];
                  const dr = wr > 0
                    ? applyChestBasisFields(
                        chestBasisFieldsAt(part.softMorph.geometry.right, rest[v], rest[v + 1], distribution),
                        rightPhysics, rightVelocity, bodyVx, bodyVy, distribution)
                    : [0, 0];
                  x += dl[0] * wl + dr[0] * wr;
                  y += dl[1] * wl + dr[1] * wr;
                } else {
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
                }
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
