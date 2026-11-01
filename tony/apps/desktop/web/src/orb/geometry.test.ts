import { describe, expect, it } from "vitest";

import {
  arcs,
  fragmentShell,
  PARTICLE_COUNT,
  particles,
  radialStreaks,
  randomGenerator,
  segmentShades,
} from "./geometry";

function radii(positions: Float32Array): number[] {
  const result: number[] = [];
  for (let i = 0; i < positions.length; i += 3) {
    result.push(Math.hypot(positions[i]!, positions[i + 1]!, positions[i + 2]!));
  }
  return result;
}

function summary(positions: Float32Array) {
  const r = radii(positions);
  let checksum = 0;
  for (const value of positions) {
    checksum += value;
  }
  return {
    vertices: positions.length / 3,
    minRadius: Number(Math.min(...r).toFixed(4)),
    maxRadius: Number(Math.max(...r).toFixed(4)),
    checksum: Number(checksum.toFixed(4)),
  };
}

describe("randomGenerator", () => {
  it("is deterministic per seed and stays in [0, 1)", () => {
    const a = randomGenerator(7);
    const b = randomGenerator(7);
    const values = Array.from({ length: 1000 }, () => a());

    expect(values).toEqual(Array.from({ length: 1000 }, () => b()));
    expect(Math.min(...values)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...values)).toBeLessThan(1);
    expect(new Set(values).size).toBeGreaterThan(990);
  });

  it("differs between seeds", () => {
    expect(randomGenerator(1)()).not.toBe(randomGenerator(2)());
  });
});

describe("fragmentShell", () => {
  it("emits one segment of two vertices per fragment, on the shell radius", () => {
    const shell = fragmentShell(3, { radius: 1.2, count: 500, minLength: 0.03, maxLength: 0.12 });

    expect(shell.length).toBe(500 * 2 * 3);
    for (const r of radii(shell)) {
      expect(r).toBeGreaterThan(1.2 - 0.01);
      expect(r).toBeLessThan(1.2 + 0.01);
    }
  });

  it("keeps every fragment length within bounds", () => {
    const shell = fragmentShell(4, { radius: 1.5, count: 200, minLength: 0.05, maxLength: 0.1 });

    for (let i = 0; i < shell.length; i += 6) {
      const length = Math.hypot(shell[i]! - shell[i + 3]!, shell[i + 1]! - shell[i + 4]!, shell[i + 2]! - shell[i + 5]!);
      expect(length).toBeGreaterThan(0.05 * 0.95);
      expect(length).toBeLessThan(0.1 * 1.01);
    }
  });
});

describe("fragmentShell with bands", () => {
  it("lays every dash on a latitude band or along a quantised meridian", () => {
    const bands = 12;
    const latitudes = Array.from({ length: bands }, (_, k) => 1.3 * Math.cos((Math.PI * (k + 0.5)) / bands));
    const shell = fragmentShell(5, { radius: 1.3, count: 400, minLength: 0.03, maxLength: 0.12, bands });
    let onLatitude = 0;
    let onMeridian = 0;

    for (let i = 0; i < shell.length; i += 6) {
      const [x0, y0, z0, x1, y1, z1] = Array.from(shell.subarray(i, i + 6));
      const latitudeDash = Math.abs(y0! - y1!) < 1e-5 && latitudes.some((band) => Math.abs(band - y0!) < 1e-5);
      const longitude = Math.atan2(z0!, x0!);
      const sector = (2 * Math.PI) / (bands * 2);
      const quantised = Math.abs(longitude / sector - Math.round(longitude / sector)) < 1e-4;
      const meridianDash = quantised && Math.abs(Math.atan2(z1!, x1!) - longitude) < 1e-4;
      expect(latitudeDash || meridianDash, `dash ${i / 6}`).toBe(true);
      expect(Math.hypot(x0!, y0!, z0!)).toBeCloseTo(1.3, 5);
      expect(Math.hypot(x1!, y1!, z1!)).toBeCloseTo(1.3, 5);
      const length = Math.hypot(x0! - x1!, y0! - y1!, z0! - z1!);
      expect(length).toBeGreaterThan(0.03 * 0.9);
      expect(length).toBeLessThan(0.12 * 1.01);
      onLatitude += latitudeDash ? 1 : 0;
      onMeridian += meridianDash ? 1 : 0;
    }
    expect(onLatitude).toBeGreaterThan(100);
    expect(onMeridian).toBeGreaterThan(100);
  });
});

describe("arcs", () => {
  const options = { count: 5, minRadius: 1.3, maxRadius: 1.6, minSweep: 0.6, maxSweep: 2.4, segments: 48 };

  it("emits count arcs of segments, within the radii", () => {
    const result = arcs(5, options);

    expect(result.length).toBe(5 * 48 * 2 * 3);
    for (const r of radii(result)) {
      expect(r).toBeGreaterThan(1.3 - 1e-4);
      expect(r).toBeLessThan(1.6 + 1e-4);
    }
  });

  it("sweeps only part of the circle", () => {
    const result = arcs(5, options);
    const perArc = 48 * 6;
    for (let arc = 0; arc < 5; arc += 1) {
      const start = result.subarray(arc * perArc, arc * perArc + 3);
      const end = result.subarray((arc + 1) * perArc - 3, (arc + 1) * perArc);
      const radius = Math.hypot(start[0]!, start[1]!, start[2]!);
      const chord = Math.hypot(start[0]! - end[0]!, start[1]! - end[1]!, start[2]! - end[2]!);
      const sweep = 2 * Math.asin(Math.min(1, chord / (2 * radius)));
      expect(sweep).toBeGreaterThan(0.6 - 1e-3);
      expect(sweep).toBeLessThan(Math.min(Math.PI, 2.4) + 1e-3);
    }
  });
});

describe("arcs with strands", () => {
  it("draws each arc as parallel strands a hair apart, so it reads as a bold band", () => {
    const options = { count: 2, minRadius: 1.4, maxRadius: 1.4, minSweep: 1, maxSweep: 1, segments: 10, strands: 3 };
    const result = arcs(9, options);
    const perStrand = 10 * 6;

    expect(result.length).toBe(2 * 3 * perStrand);
    const strandRadii = [0, 1, 2].map((strand) =>
      Math.hypot(result[strand * perStrand]!, result[strand * perStrand + 1]!, result[strand * perStrand + 2]!),
    );
    expect(strandRadii[0]).toBeLessThan(strandRadii[1]!);
    expect(strandRadii[1]).toBeCloseTo(1.4, 6);
    expect(strandRadii[2]! - strandRadii[1]!).toBeCloseTo(strandRadii[1]! - strandRadii[0]!, 6);
    expect(strandRadii[2]! - strandRadii[0]!).toBeLessThan(0.05);
  });
});

describe("radialStreaks", () => {
  it("points every streak away from the centre between the radii", () => {
    const result = radialStreaks(6, { count: 300, innerRadius: 0.5, outerRadius: 1.9, minLength: 0.05, maxLength: 0.4 });

    expect(result.length).toBe(300 * 6);
    for (let i = 0; i < result.length; i += 6) {
      const inner = Math.hypot(result[i]!, result[i + 1]!, result[i + 2]!);
      const outer = Math.hypot(result[i + 3]!, result[i + 4]!, result[i + 5]!);
      expect(inner).toBeGreaterThanOrEqual(0.5 - 1e-4);
      expect(outer).toBeLessThanOrEqual(1.9 + 1e-4);
      expect(outer - inner).toBeGreaterThan(0.05 - 1e-4);
      expect(outer - inner).toBeLessThan(0.4 + 1e-4);
    }
  });
});

describe("particles", () => {
  it("defaults to a count inside 3 000-6 000", () => {
    expect(PARTICLE_COUNT).toBeGreaterThanOrEqual(3000);
    expect(PARTICLE_COUNT).toBeLessThanOrEqual(6000);
    expect(particles(8).length).toBe(PARTICLE_COUNT * 3);
  });

  it("stays within the cloud radii", () => {
    const radiiOf = radii(particles(8, { count: 3000, innerRadius: 0.4, outerRadius: 2 }));

    expect(Math.min(...radiiOf)).toBeGreaterThanOrEqual(0.4 - 1e-4);
    expect(Math.max(...radiiOf)).toBeLessThanOrEqual(2 + 1e-4);
  });
});

describe("segmentShades", () => {
  it("gives both vertices of a segment the same shade within [min, 1]", () => {
    const shades = segmentShades(9, 100, 0.3);

    expect(shades.length).toBe(200);
    for (let i = 0; i < shades.length; i += 2) {
      expect(shades[i]).toBe(shades[i + 1]);
      expect(shades[i]).toBeGreaterThanOrEqual(0.3);
      expect(shades[i]).toBeLessThanOrEqual(1);
    }
  });
});

describe("golden geometry summary", () => {
  it("matches the recorded summary for the default seeds", async () => {
    const golden = {
      shell: summary(fragmentShell(1, { radius: 1, count: 400, minLength: 0.03, maxLength: 0.12 })),
      arcs: summary(arcs(2, { count: 5, minRadius: 1.3, maxRadius: 1.6, minSweep: 0.6, maxSweep: 2.4, segments: 32 })),
      streaks: summary(radialStreaks(3, { count: 200, innerRadius: 0.5, outerRadius: 1.9, minLength: 0.05, maxLength: 0.4 })),
      particles: summary(particles(4)),
      bandedShell: summary(fragmentShell(5, { radius: 1.3, count: 300, minLength: 0.03, maxLength: 0.12, bands: 12 })),
      strandedArcs: summary(
        arcs(6, { count: 4, minRadius: 1.2, maxRadius: 1.6, minSweep: 0.8, maxSweep: 3.6, segments: 24, strands: 3 }),
      ),
      shades: Number(segmentShades(7, 50, 0.2).reduce((total, shade) => total + shade, 0).toFixed(4)),
    };

    await expect(JSON.stringify(golden, null, 2)).toMatchFileSnapshot("./__golden__/geometry-summary.json");
  });
});
