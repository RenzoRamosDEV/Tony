import type { OrbParams } from "./orbParams";

/** Coming back from a hidden tab must not jump: one frame never counts for more than this. */
export const MAX_DT_MS = 100;

/** Exponential approach: after `tauMs` the gap has closed by 1 - 1/e (about 63 %). */
export function approach(current: number, target: number, dtMs: number, tauMs: number): number {
  if (tauMs <= 0) {
    return target;
  }
  const dt = Math.min(Math.max(dtMs, 0), MAX_DT_MS);
  return current + (target - current) * (1 - Math.exp(-dt / tauMs));
}

export function approachParams(current: OrbParams, target: OrbParams, dtMs: number, tauMs: number): OrbParams {
  for (const key of Object.keys(current) as (keyof OrbParams)[]) {
    current[key] = approach(current[key], target[key], dtMs, tauMs);
  }
  return current;
}
