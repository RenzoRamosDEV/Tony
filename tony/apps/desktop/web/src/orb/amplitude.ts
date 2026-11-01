import { approach } from "./tween";

const ATTACK_MS = 40;
const RELEASE_MS = 180;

/** The core already normalises `voice_level` to [0, 1]; only out-of-range values are clamped. */
export function normalizeLevel(level: number): number {
  return Math.min(1, Math.max(0, level));
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
