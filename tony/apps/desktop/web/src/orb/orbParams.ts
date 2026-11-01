import { normalizeLevel } from "./amplitude";
import type { OrbState } from "./orbState";

export interface OrbParams {
  spin: number;
  ringSpeed: number;
  coreScale: number;
  shellScale: number;
  displacement: number;
  agitation: number;
  bloom: number;
  glow: number;
  pulse: number;
}

export const MAX_CORE_SCALE = 1.45;
export const MAX_SHELL_SCALE = 1.15;

const CORE_GAIN = MAX_CORE_SCALE - 1;
const SHELL_GAIN = MAX_SHELL_SCALE - 1;

export function emptyParams(): OrbParams {
  return { spin: 0, ringSpeed: 0, coreScale: 1, shellScale: 1, displacement: 0, agitation: 0, bloom: 0, glow: 0, pulse: 0 };
}

function fill(out: OrbParams, values: OrbParams): OrbParams {
  return Object.assign(out, values);
}

function stateParams(state: OrbState, level: number, amplitude: number, out: OrbParams): OrbParams {
  switch (state) {
    case "idle":
      return fill(out, {
        spin: 0.12, ringSpeed: 0.3, coreScale: 1, shellScale: 1,
        displacement: 0.015, agitation: 0.04, bloom: 0.8, glow: 0.85, pulse: 0.12,
      });
    case "listening": {
      const input = normalizeLevel(level);
      return fill(out, {
        spin: 0.18, ringSpeed: 0.5, coreScale: 1 + CORE_GAIN * input, shellScale: 1 + SHELL_GAIN * input,
        displacement: 0.03 + 0.12 * input, agitation: 0.6 * input, bloom: 0.9 + 0.4 * input, glow: 1 + 0.3 * input,
        pulse: 0.05,
      });
    }
    case "thinking":
      return fill(out, {
        spin: 0.32, ringSpeed: 1.8, coreScale: 1, shellScale: 1,
        displacement: 0.05, agitation: 0.15, bloom: 1.0, glow: 1.05, pulse: 0.4,
      });
    case "speaking": {
      const voice = Math.min(1, Math.max(0, amplitude));
      return fill(out, {
        spin: 0.22, ringSpeed: 0.8 + 1.6 * voice, coreScale: 1 + CORE_GAIN * voice, shellScale: 1 + SHELL_GAIN * voice,
        displacement: 0.04 + 0.14 * voice, agitation: 0.1 + 0.5 * voice, bloom: 0.85 + 0.45 * voice, glow: 0.95 + 0.35 * voice,
        pulse: 0.05,
      });
    }
  }
}

/** Visual targets of a state; with reduced motion only the brightness tells the states apart. */
export function targetParams(
  state: OrbState,
  level: number,
  amplitude: number,
  reducedMotion: boolean,
  out: OrbParams = emptyParams(),
): OrbParams {
  stateParams(state, level, amplitude, out);
  if (reducedMotion) {
    out.spin = 0;
    out.ringSpeed = 0;
    out.displacement = 0;
    out.agitation = 0;
    out.pulse = 0;
    out.coreScale = 1;
    out.shellScale = 1;
  }
  return out;
}
