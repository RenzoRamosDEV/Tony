import { describe, expect, it } from "vitest";

import { FrameAccumulator, FRAME_SAMPLES, Resampler } from "./resample";

function ramp(length: number): Float32Array {
  return Float32Array.from({ length }, (_, i) => i / length);
}

describe("Resampler", () => {
  it("turns 30 ms at 48 kHz into 480 samples at 16 kHz", () => {
    const out = new Resampler(48000, 16000).process(ramp(1440));

    expect(out.length).toBe(480);
    expect(out[0]).toBeCloseTo((0 + 1 / 1440 + 2 / 1440) / 3, 6);
    expect(out[479]!).toBeGreaterThan(out[0]!);
  });

  it("passes 16 kHz audio through untouched", () => {
    const input = ramp(320);

    const out = new Resampler(16000, 16000).process(input);

    expect(out).not.toBe(input);
    expect(Array.from(out)).toEqual(Array.from(input));
  });

  it("averages each block so a constant signal stays constant", () => {
    const out = new Resampler(48000, 16000).process(new Float32Array(960).fill(0.25));

    expect(out.every((v) => Math.abs(v - 0.25) < 1e-6)).toBe(true);
  });
});

describe("FrameAccumulator", () => {
  it("emits one 480-sample frame per 30 ms and keeps the remainder", () => {
    const frames: Float32Array[] = [];
    const accumulator = new FrameAccumulator((frame) => frames.push(frame));

    accumulator.push(new Float32Array(300));
    expect(frames).toHaveLength(0);
    accumulator.push(new Float32Array(300));
    expect(frames).toHaveLength(1);
    accumulator.push(new Float32Array(FRAME_SAMPLES * 2));

    expect(frames).toHaveLength(3);
    expect(frames.every((f) => f.length === FRAME_SAMPLES)).toBe(true);
    expect(accumulator.pending).toBe(120);
  });

  it("preserves sample order across frame boundaries", () => {
    const frames: Float32Array[] = [];
    const accumulator = new FrameAccumulator((frame) => frames.push(frame));

    accumulator.push(Float32Array.from({ length: 500 }, (_, i) => i));
    accumulator.push(Float32Array.from({ length: 460 }, (_, i) => 500 + i));

    expect(frames[0]![479]).toBe(479);
    expect(frames[1]![0]).toBe(480);
    expect(frames[1]![479]).toBe(959);
  });
});

describe("Resampler (review of change 05)", () => {
  it("finding 12: 375 worklet blocks of 128 samples at 48 kHz give 16 000 ± 1 samples", () => {
    const resampler = new Resampler(48000, 16000);
    let total = 0;

    for (let block = 0; block < 375; block += 1) {
      total += resampler.process(new Float32Array(128).fill(0.1)).length;
    }

    expect(Math.abs(total - 16000)).toBeLessThanOrEqual(1);
  });

  it("finding 12: a ramp split in blocks comes out as one continuous ramp", () => {
    const resampler = new Resampler(44100, 16000);
    const output: number[] = [];

    for (let block = 0; block < 50; block += 1) {
      const input = Float32Array.from({ length: 128 }, (_, i) => (block * 128 + i) / 44100);
      output.push(...resampler.process(input));
    }

    const steps = output.slice(1).map((value, i) => value - output[i]!);
    const expected = 1 / 16000;
    expect(steps.every((step) => Math.abs(step - expected) < expected * 0.15)).toBe(true);
  });
});
