import { clamp } from "./canvasDraw";
import type { OrbParams } from "./orbParams";
import type { OrbScene } from "./scene";

/** Accumulated animation phases, in seconds and radians. */
export interface OrbClock {
  t: number;
  rot: number;
  ring: number;
}

export type OrbDrawing = (
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  params: OrbParams,
  clock: OrbClock,
  scale: number,
) => void;

const MAX_PIXEL_RATIO = 2;
const REFERENCE_SIZE = 420;
const MIN_SCALE = 0.5;
const MAX_SCALE = 1.3;

/** An orb scene that paints a 2D drawing from the shared parameters. */
export function createCanvasScene(canvas: HTMLCanvasElement, draw: OrbDrawing): OrbScene {
  const ctx = canvas.getContext("2d");
  if (ctx === null) {
    throw new Error("2D canvas context unavailable");
  }
  const clock: OrbClock = { t: 0, rot: 0, ring: 0 };
  let width = 1;
  let height = 1;
  let ratio = 1;
  let moving = true;
  let disposed = false;

  return {
    update(params, dtMs) {
      if (disposed) {
        return;
      }
      if (moving) {
        const dt = dtMs / 1000;
        clock.t += dt;
        clock.rot += params.spin * dt;
        clock.ring += params.ringSpeed * dt;
      }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      const scale = clamp(Math.min(width, height) / REFERENCE_SIZE, MIN_SCALE, MAX_SCALE);
      draw(ctx, width, height, params, clock, scale);
    },
    resize(newWidth, newHeight, devicePixelRatio) {
      width = Math.max(1, newWidth);
      height = Math.max(1, newHeight);
      ratio = Math.min(devicePixelRatio, MAX_PIXEL_RATIO);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    },
    setAutoRotate(enabled) {
      moving = enabled;
    },
    onInteraction() {
      return () => undefined;
    },
    dispose() {
      disposed = true;
    },
  };
}
