import { rms } from "../audio/level";
import { approach } from "./tween";

export { rms };

/** RMS of 0.2 already fills the meter: speech levels are small numbers. */
export const FULL_SCALE_RMS = 0.2;
const ATTACK_MS = 40;
const RELEASE_MS = 180;

export function normalizeLevel(level: number): number {
  return Math.min(1, Math.max(0, level / FULL_SCALE_RMS));
}

/** Fast attack and slow release so the orb follows syllables without flickering. */
export class AmplitudeSmoother {
  value = 0;

  update(target: number, dtMs: number): number {
    const clamped = Math.min(1, Math.max(0, target));
    const tau = clamped > this.value ? ATTACK_MS : RELEASE_MS;
    this.value = approach(this.value, clamped, dtMs, tau);
    return this.value;
  }

  reset(): void {
    this.value = 0;
  }
}
