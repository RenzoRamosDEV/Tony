import { describe, expect, it } from "vitest";

import { int16ToFloat32, PcmPlayer } from "./player";

class FakeSource {
  started: number | null = null;
  stopped = false;
  connected = false;
  onended: (() => void) | null = null;
  constructor(public buffer: { duration: number }) {}
  connect(): void {
    this.connected = true;
  }
  start(when: number): void {
    this.started = when;
  }
  stop(): void {
    this.stopped = true;
    this.onended?.();
  }
  finish(): void {
    this.onended?.();
  }
}

class FakeContext {
  currentTime = 0;
  sampleRate = 24000;
  destination = {};
  state = "running";
  sources: FakeSource[] = [];
  closed = false;
  buffers: Float32Array[] = [];
  createBuffer(_channels: number, length: number, rate: number) {
    const data = new Float32Array(length);
    this.buffers.push(data);
    return { duration: length / rate, getChannelData: () => data };
  }
  createBufferSource() {
    const source = new FakeSource({ duration: 0 });
    this.sources.push(source);
    return source as unknown as AudioBufferSourceNode;
  }
  async resume(): Promise<void> {
    this.state = "running";
  }
  async close(): Promise<void> {
    this.closed = true;
  }
}

function pcm(ms: number, value = 1000): ArrayBuffer {
  const samples = new Int16Array((24000 * ms) / 1000).fill(value);
  return samples.buffer;
}

describe("PcmPlayer", () => {
  it("schedules consecutive chunks back to back from the current time", () => {
    const ctx = new FakeContext();
    ctx.currentTime = 2;
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);

    expect(player.enqueue(0, pcm(500))).toBe(true);
    expect(player.enqueue(1, pcm(500))).toBe(true);
    expect(player.enqueue(2, pcm(500))).toBe(true);

    expect(ctx.sources.map((s) => s.started)).toEqual([2, 2.5, 3]);
    expect(ctx.sources.every((s) => s.connected)).toBe(true);
    expect(player.playing).toBe(true);
  });

  it("discards chunks whose seq is not above the last one", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    player.enqueue(2, pcm(100));

    expect(player.enqueue(1, pcm(100))).toBe(false);
    expect(player.enqueue(2, pcm(100))).toBe(false);
    expect(player.enqueue(3, pcm(100))).toBe(true);
    expect(ctx.sources).toHaveLength(2);
  });

  it("restarts the sequence for a new message", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    player.enqueue(0, pcm(100));
    player.enqueue(1, pcm(100));

    player.begin();

    expect(player.enqueue(0, pcm(100))).toBe(true);
  });

  it("stop halts every source and empties the queue", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    player.enqueue(0, pcm(500));
    player.enqueue(1, pcm(500));

    player.stop();

    expect(ctx.sources.every((s) => s.stopped)).toBe(true);
    expect(player.playing).toBe(false);
    ctx.currentTime = 1;
    player.begin();
    player.enqueue(0, pcm(100));
    expect(ctx.sources[2]!.started).toBe(1);
  });

  it("calls onDrain once when the last source ends", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    let drained = 0;
    player.onDrain = () => {
      drained += 1;
    };
    player.enqueue(0, pcm(100));
    player.enqueue(1, pcm(100));

    ctx.sources[0]!.finish();
    expect(drained).toBe(0);
    ctx.sources[1]!.finish();

    expect(drained).toBe(1);
    expect(player.playing).toBe(false);
  });

  it("converts Int16 to Float32 in [-1, 1]", () => {
    const samples = new Int16Array([0, 16384, -32768, 32767]);

    const floats = int16ToFloat32(samples.buffer);

    expect(Array.from(floats)).toEqual([0, 0.5, -1, 32767 / 32768]);
  });

  it("writes the converted samples into the audio buffer", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);

    player.enqueue(0, pcm(1, 16384));

    expect(ctx.buffers[0]![0]).toBeCloseTo(0.5);
    expect(ctx.buffers[0]!.length).toBe(24);
  });
});
