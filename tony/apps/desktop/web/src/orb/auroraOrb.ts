import { TAU, alpha, fillRadial } from "./canvasDraw";
import type { OrbDrawing } from "./canvasScene";

const OUTLINE_POINTS = 96;
const WOBBLE_REST_AMPLITUDE = 0.05;
/** Radial deformation per unit of displacement; keeps full voice under 2x the resting deformation. */
const WOBBLE_DISPLACEMENT_GAIN = 0.3;
const CONIC_SPIN_RATIO = 0.6;
const BLOB_ORBIT_BASE_RATIO = 0.5;
const BLOB_ORBIT_STEP_RATIO = 0.2;
const BLOB_COLORS = ["rgba(167,255,120,.75)", "rgba(76,201,240,.7)", "rgba(244,114,182,.6)", "rgba(94,242,196,.75)"];
const CONIC_STOPS: [number, string][] = [
  [0, "#5ef2c4"],
  [0.25, "#4cc9f0"],
  [0.5, "#8b5cf6"],
  [0.75, "#f472b6"],
  [1, "#5ef2c4"],
];

/** Liquid drop: a wobbling outline filled with a conic gradient and drifting colour blobs. */
export const drawAuroraOrb: OrbDrawing = (ctx, width, height, params, clock, scale) => {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.28 * params.shellScale;
  const { t, wobble: phase } = clock;
  const glow = params.glow;
  const wobble = WOBBLE_REST_AMPLITUDE + params.displacement * WOBBLE_DISPLACEMENT_GAIN;

  const traceDrop = () => {
    ctx.beginPath();
    for (let i = 0; i <= OUTLINE_POINTS; i += 1) {
      const theta = (i / OUTLINE_POINTS) * TAU;
      const r =
        radius *
        (1 +
          wobble *
            (0.5 * Math.sin(3 * theta + phase * 1.1) +
              0.35 * Math.sin(5 * theta - phase * 1.7) +
              0.25 * Math.sin(2 * theta + t * 0.6)));
      const x = cx + Math.cos(theta) * r;
      const y = cy + Math.sin(theta) * r;
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.closePath();
  };

  fillRadial(ctx, cx, cy, radius * 2.4, [
    [0, `rgba(94,242,196,${alpha(0.2 * glow)})`],
    [0.5, `rgba(139,92,246,${alpha(0.06 * glow)})`],
    [1, "rgba(0,0,0,0)"],
  ]);

  ctx.save();
  traceDrop();
  ctx.clip();
  const span = radius * 3.2;
  const body = ctx.createLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius);
  body.addColorStop(0, "#103f4d");
  body.addColorStop(1, "#1d1650");
  ctx.fillStyle = body;
  ctx.fillRect(cx - radius * 1.6, cy - radius * 1.6, span, span);
  if (ctx.createConicGradient) {
    const conic = ctx.createConicGradient(clock.rot * CONIC_SPIN_RATIO, cx, cy);
    for (const [offset, color] of CONIC_STOPS) {
      conic.addColorStop(offset, color);
    }
    ctx.globalAlpha = 0.8;
    ctx.fillStyle = conic;
    ctx.fillRect(cx - radius * 1.6, cy - radius * 1.6, span, span);
    ctx.globalAlpha = 1;
  }
  ctx.globalCompositeOperation = "screen";
  BLOB_COLORS.forEach((color, k) => {
    const angle = clock.rot * (BLOB_ORBIT_BASE_RATIO + k * BLOB_ORBIT_STEP_RATIO) + k * 1.7;
    const distance = radius * (0.35 + 0.15 * Math.sin(t * 0.8 + k));
    fillRadial(ctx, cx + Math.cos(angle) * distance, cy + Math.sin(angle) * distance, radius * 0.8, [
      [0, color],
      [1, "rgba(0,0,0,0)"],
    ]);
  });
  fillRadial(ctx, cx, cy, radius * 0.75 * params.coreScale, [
    [0, `rgba(255,255,255,${alpha(0.7 * glow)})`],
    [1, "rgba(255,255,255,0)"],
  ]);
  ctx.globalCompositeOperation = "source-over";
  fillRadial(ctx, cx, cy, radius * 1.25, [
    [0.55, "rgba(2,8,14,0)"],
    [1, "rgba(2,8,14,.6)"],
  ]);
  fillRadial(ctx, cx - radius * 0.34, cy - radius * 0.5, radius * 0.55, [
    [0, "rgba(255,255,255,.42)"],
    [1, "rgba(255,255,255,0)"],
  ]);
  ctx.restore();

  const rim = ctx.createLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius);
  rim.addColorStop(0, "rgba(255,255,255,.65)");
  rim.addColorStop(1, "rgba(94,242,196,.15)");
  ctx.lineWidth = Math.max(1, 1.6 * scale);
  ctx.strokeStyle = rim;
  traceDrop();
  ctx.stroke();
};

