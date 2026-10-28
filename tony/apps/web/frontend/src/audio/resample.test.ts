import { describe, expect, it } from "vitest";

import { FrameAccumulator, FRAME_SAMPLES, resample } from "./resample";

function ramp(length: number): Float32Array {
  return Float32Array.from({ length }, (_, i) => i / length);
}

describe("resample", () => {
  it("turns 30 ms at 48 kHz into 480 samples at 16 kHz", () => {
    const out = resample(ramp(1440), 48000, 16000);

    expect(out.length).toBe(480);
    expect(out[0]).toBeCloseTo((0 + 1 / 1440 + 2 / 1440) / 3, 6);
    expect(out[479]!).toBeGreaterThan(out[0]!);
  });

  it("rounds the length for 44.1 kHz input", () => {
    expect(resample(ramp(1323), 44100, 16000).length).toBe(480);
    expect(resample(ramp(100), 44100, 16000).length).toBe(Math.round((100 * 16000) / 44100));
  });

  it("passes 16 kHz audio through untouched", () => {
    const input = ramp(320);

    const out = resample(input, 16000, 16000);

    expect(out).not.toBe(input);
    expect(Array.from(out)).toEqual(Array.from(input));
  });

  it("averages each block so a constant signal stays constant", () => {
    const out = resample(new Float32Array(960).fill(0.25), 48000, 16000);

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
