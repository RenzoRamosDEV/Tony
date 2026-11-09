import { TAU, alpha, clamp, fillRadial } from "./canvasDraw";
import type { OrbDrawing } from "./canvasScene";

const TICKS = 120;
const MAJOR_TICK_EVERY = 10;
const BARS = 96;
const ARC_SEGMENTS = 3;

/** Radial dial: tick scale, a ring of level bars, a sweeping arc and a bright core. */
export const drawDialOrb: OrbDrawing = (ctx, width, height, params, clock, scale) => {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.28;
  const { t } = clock;
  const glow = params.glow * (1 + 0.15 * params.pulse * Math.sin(t * 3.2));

  ctx.lineCap = "round";
  ctx.strokeStyle = "rgba(220,235,245,.1)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 1.55, 0, TAU);
  ctx.stroke();

  for (let i = 0; i < TICKS; i += 1) {
    const angle = (i / TICKS) * TAU + clock.rot * 0.2 - Math.PI / 2;
    const major = i % MAJOR_TICK_EVERY === 0;
    const inner = radius * 1.3;
    const outer = inner + radius * (major ? 0.11 : 0.05);
    ctx.strokeStyle = major ? "rgba(232,240,248,.55)" : "rgba(232,240,248,.16)";
    ctx.lineWidth = major ? Math.max(1, 1.6 * scale) : 1;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner);
    ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer);
    ctx.stroke();
  }

  const barBase = radius * 0.8;
  const boost = Math.min(1, params.displacement * 4.2);
  ctx.lineWidth = Math.max(1, 2.3 * scale);
  for (let b = 0; b < BARS; b += 1) {
    const theta = (b / BARS) * TAU - Math.PI / 2;
    const wave = 0.5 + 0.5 * Math.sin(b * 0.33 + t * (1.4 + params.ringSpeed)) * Math.sin(b * 0.09 - t * 1.1 + 1);
    const amp = clamp(0.045 + boost * wave * 1.05 + 0.02 * Math.sin(t * 3 + b));
    const length = radius * (0.07 + 0.55 * amp);
    ctx.strokeStyle =
      amp > 0.5 ? `rgba(123,224,255,${alpha(0.5 + amp * 0.5)})` : `rgba(232,240,248,${alpha(0.28 + 0.6 * amp)})`;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(theta) * barBase, cy + Math.sin(theta) * barBase);
    ctx.lineTo(cx + Math.cos(theta) * (barBase + length), cy + Math.sin(theta) * (barBase + length));
    ctx.stroke();
  }

  if (ctx.createConicGradient) {
    const sweep = ctx.createConicGradient(clock.ring * 0.8 - Math.PI / 2, cx, cy);
    sweep.addColorStop(0, "rgba(123,224,255,0)");
    sweep.addColorStop(0.7, "rgba(123,224,255,0)");
    sweep.addColorStop(1, `rgba(123,224,255,${clamp(0.2 + params.ringSpeed * 0.25, 0, 0.8).toFixed(2)})`);
    ctx.strokeStyle = sweep;
    ctx.lineWidth = radius * 0.07;
    ctx.lineCap = "butt";
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.62, 0, TAU);
    ctx.stroke();
    ctx.lineCap = "round";
  }

  ctx.strokeStyle = "rgba(232,240,248,.5)";
  ctx.lineWidth = Math.max(1, 1.6 * scale);
  for (let k = 0; k < ARC_SEGMENTS; k += 1) {
    const start = -clock.ring * 0.6 + (k * TAU) / ARC_SEGMENTS;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.5, start, start + 0.8);
    ctx.stroke();
  }

  const pointerTop = cy - radius * 1.62;
  const pointerHalf = Math.max(3, 5 * scale);
  ctx.fillStyle = "#e8f0f8";
  ctx.beginPath();
  ctx.moveTo(cx, pointerTop + pointerHalf * 1.4);
  ctx.lineTo(cx - pointerHalf, pointerTop);
  ctx.lineTo(cx + pointerHalf, pointerTop);
  ctx.closePath();
  ctx.fill();

  ctx.globalCompositeOperation = "lighter";
  fillRadial(ctx, cx, cy, radius * 1.9, [
    [0, `rgba(123,224,255,${alpha(0.1 * glow)})`],
    [1, "rgba(123,224,255,0)"],
  ]);
  const core = radius * 0.36 * params.coreScale;
  fillRadial(ctx, cx, cy, core * 1.8, [
    [0, `rgba(190,240,255,${alpha(0.55 * glow)})`],
    [1, "rgba(123,224,255,0)"],
  ]);
  fillRadial(ctx, cx, cy, core * 0.55, [
    [0, `rgba(255,255,255,${alpha(0.95 * glow)})`],
    [1, "rgba(220,245,255,0)"],
  ]);
  ctx.globalCompositeOperation = "source-over";
};
