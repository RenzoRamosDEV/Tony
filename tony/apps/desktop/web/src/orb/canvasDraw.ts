export const TAU = Math.PI * 2;

export type ColorStop = [offset: number, color: string];

export function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

export function alpha(value: number): string {
  return clamp(value).toFixed(3);
}

export function fillRadial(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, stops: ColorStop[]): void {
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
  for (const [offset, color] of stops) {
    gradient.addColorStop(offset, color);
  }
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, TAU);
  ctx.fill();
}
