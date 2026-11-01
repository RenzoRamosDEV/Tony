export const PARTICLE_COUNT = 4500;

export interface ShellOptions {
  radius: number;
  count: number;
  minLength: number;
  maxLength: number;
  /** Snap dashes to this many latitude bands (and twice as many meridians), like hologram panels. */
  bands?: number;
}

export interface ArcOptions {
  count: number;
  minRadius: number;
  maxRadius: number;
  minSweep: number;
  maxSweep: number;
  segments: number;
  /** Parallel copies of each arc, a hair apart; 1 by default. */
  strands?: number;
}

const STRAND_GAP = 0.008;
/** A latitude dash near a pole must not wrap into a tiny closed ring. */
const MAX_DASH_TURN = 0.5;

export interface StreakOptions {
  count: number;
  innerRadius: number;
  outerRadius: number;
  minLength: number;
  maxLength: number;
}

export interface CloudOptions {
  count: number;
  innerRadius: number;
  outerRadius: number;
}

type Random = () => number;
type Vec3 = [number, number, number];

/** mulberry32: tiny seeded PRNG so the orb looks the same on every load and in the golden file. */
export function randomGenerator(seed: number): Random {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function between(random: Random, min: number, max: number): number {
  return min + (max - min) * random();
}

function unitVector(random: Random): Vec3 {
  const z = between(random, -1, 1);
  const angle = between(random, 0, 2 * Math.PI);
  const ring = Math.sqrt(1 - z * z);
  return [ring * Math.cos(angle), ring * Math.sin(angle), z];
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function normalize(v: Vec3): Vec3 {
  const length = Math.hypot(v[0], v[1], v[2]);
  return [v[0] / length, v[1] / length, v[2] / length];
}

/** Orthonormal basis (u, v) of the plane perpendicular to `normal`. */
function planeBasis(normal: Vec3): [Vec3, Vec3] {
  const helper: Vec3 = Math.abs(normal[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  const u = normalize(cross(normal, helper));
  return [u, cross(normal, u)];
}

function writePointOnCircle(out: Float32Array, offset: number, radius: number, u: Vec3, v: Vec3, angle: number): void {
  const c = Math.cos(angle) * radius;
  const s = Math.sin(angle) * radius;
  out[offset] = u[0] * c + v[0] * s;
  out[offset + 1] = u[1] * c + v[1] * s;
  out[offset + 2] = u[2] * c + v[2] * s;
}

/**
 * Short glowing dashes lying on a sphere, each one a small great-circle arc between two
 * vertices, aligned with latitudes or meridians like the panels of a hologram.
 */
function writeSpherePoint(out: Float32Array, offset: number, radius: number, polar: number, longitude: number): void {
  const ring = Math.sin(polar) * radius;
  out[offset] = ring * Math.cos(longitude);
  out[offset + 1] = Math.cos(polar) * radius;
  out[offset + 2] = ring * Math.sin(longitude);
}

function bandedShell(random: Random, options: ShellOptions, bands: number): Float32Array {
  const out = new Float32Array(options.count * 6);
  const sector = Math.PI / bands;
  const margin = sector / 2;
  for (let i = 0; i < options.count; i += 1) {
    const length = between(random, options.minLength, options.maxLength) / options.radius;
    if (random() < 0.5) {
      const polar = sector * (1 + Math.floor(random() * (bands - 2)) + 0.5);
      const longitude = between(random, -Math.PI, Math.PI);
      writeSpherePoint(out, i * 6, options.radius, polar, longitude);
      writeSpherePoint(out, i * 6 + 3, options.radius, polar, longitude + Math.min(length / Math.sin(polar), MAX_DASH_TURN));
    } else {
      const longitude = (Math.round(random() * bands * 2) - bands) * sector;
      const polar = between(random, margin, Math.PI - margin - length);
      writeSpherePoint(out, i * 6, options.radius, polar, longitude);
      writeSpherePoint(out, i * 6 + 3, options.radius, polar + length, longitude);
    }
  }
  return out;
}

export function fragmentShell(seed: number, options: ShellOptions): Float32Array {
  const random = randomGenerator(seed);
  if (options.bands) {
    return bandedShell(random, options, options.bands);
  }
  const out = new Float32Array(options.count * 6);
  for (let i = 0; i < options.count; i += 1) {
    const start = unitVector(random);
    const meridian = random() < 0.5;
    const tangent = meridian ? normalize(cross(cross([0, 1, 0], start), start)) : normalize(cross([0, 1, 0], start));
    const length = between(random, options.minLength, options.maxLength);
    const angle = 2 * Math.asin(Math.min(1, length / (2 * options.radius)));
    writePointOnCircle(out, i * 6, options.radius, start, tangent, 0);
    writePointOnCircle(out, i * 6 + 3, options.radius, start, tangent, angle);
  }
  return out;
}

/** Partial circles of random tilt, each drawn as `segments` line segments per strand. */
export function arcs(seed: number, options: ArcOptions): Float32Array {
  const random = randomGenerator(seed);
  const strands = options.strands ?? 1;
  const out = new Float32Array(options.count * strands * options.segments * 6);
  let offset = 0;
  for (let arc = 0; arc < options.count; arc += 1) {
    const [u, v] = planeBasis(unitVector(random));
    const radius = between(random, options.minRadius, options.maxRadius);
    const sweep = between(random, options.minSweep, options.maxSweep);
    const start = between(random, 0, 2 * Math.PI);
    for (let strand = 0; strand < strands; strand += 1) {
      const strandRadius = radius + (strand - (strands - 1) / 2) * STRAND_GAP;
      for (let step = 0; step < options.segments; step += 1) {
        writePointOnCircle(out, offset, strandRadius, u, v, start + (sweep * step) / options.segments);
        writePointOnCircle(out, offset + 3, strandRadius, u, v, start + (sweep * (step + 1)) / options.segments);
        offset += 6;
      }
    }
  }
  return out;
}

export function radialStreaks(seed: number, options: StreakOptions): Float32Array {
  const random = randomGenerator(seed);
  const out = new Float32Array(options.count * 6);
  for (let i = 0; i < options.count; i += 1) {
    const direction = unitVector(random);
    const length = between(random, options.minLength, options.maxLength);
    const inner = between(random, options.innerRadius, options.outerRadius - length);
    for (let axis = 0; axis < 3; axis += 1) {
      out[i * 6 + axis] = direction[axis]! * inner;
      out[i * 6 + 3 + axis] = direction[axis]! * (inner + length);
    }
  }
  return out;
}

const DEFAULT_CLOUD: CloudOptions = { count: PARTICLE_COUNT, innerRadius: 0.35, outerRadius: 2.1 };

/** Particle cloud denser near the shells: radius biased towards the middle of the range. */
export function particles(seed: number, options: CloudOptions = DEFAULT_CLOUD): Float32Array {
  const random = randomGenerator(seed);
  const out = new Float32Array(options.count * 3);
  for (let i = 0; i < options.count; i += 1) {
    const direction = unitVector(random);
    const bias = (random() + random()) / 2;
    const radius = options.innerRadius + (options.outerRadius - options.innerRadius) * bias;
    out[i * 3] = direction[0] * radius;
    out[i * 3 + 1] = direction[1] * radius;
    out[i * 3 + 2] = direction[2] * radius;
  }
  return out;
}

/** One brightness per segment (repeated on its two vertices) so the dashes flicker unevenly. */
export function segmentShades(seed: number, segments: number, minShade: number): Float32Array {
  const random = randomGenerator(seed);
  const out = new Float32Array(segments * 2);
  for (let i = 0; i < segments; i += 1) {
    const shade = between(random, minShade, 1);
    out[i * 2] = shade;
    out[i * 2 + 1] = shade;
  }
  return out;
}
