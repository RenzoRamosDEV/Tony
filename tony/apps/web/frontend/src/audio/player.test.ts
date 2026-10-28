import { describe, expect, it } from "vitest";

import { int16ToFloat32, PcmPlayer } from "./player";

class FakeSource {
  started: number | null = null;
  stopped = false;
  connected = false;
  target: unknown = null;
  onended: (() => void) | null = null;
  constructor(public buffer: { duration: number }) {}
  connect(target: unknown): void {
    this.connected = true;
    this.target = target;
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

class FakeAnalyser {
  fftSize = 2048;
  smoothingTimeConstant = 0.8;
  target: unknown = null;
  signal = 0;
  connect(target: unknown): void {
    this.target = target;
  }
  getFloatTimeDomainData(out: Float32Array): void {
    out.fill(this.signal);
  }
}

class FakeContext {
  analysers: FakeAnalyser[] = [];
  createAnalyser() {
    const analyser = new FakeAnalyser();
    this.analysers.push(analyser);
    return analyser as unknown as AnalyserNode;
  }
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

  it("tts.cancelled-style stop halts every scheduled source, zeroes the amplitude and drops later chunks", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    const stopped: string[] = [];
    player.onStopped = (messageId) => stopped.push(messageId);
    player.begin("m-2");
    player.enqueue(0, pcm(500), "m-2");
    player.enqueue(1, pcm(500), "m-2");
    player.enqueue(2, pcm(500), "m-2");
    player.amplitude();
    ctx.analysers[0]!.signal = 0.5;

    player.stop("m-2");

    expect(ctx.sources.map((s) => s.stopped)).toEqual([true, true, true]);
    expect(player.amplitude()).toBe(0);
    expect(player.enqueue(3, pcm(500), "m-2")).toBe(false);
    expect(ctx.sources).toHaveLength(3);
    expect(stopped).toEqual(["m-2"]);
    player.stop("m-2");
    expect(stopped).toEqual(["m-2"]);
    player.begin("m-3");
    expect(player.enqueue(0, pcm(100), "m-3")).toBe(true);
  });

  it("reports the playback stopped once when the queue drains after the end", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    const stopped: string[] = [];
    player.onStopped = (messageId) => stopped.push(messageId);
    player.begin("m-2");
    player.enqueue(0, pcm(100), "m-2");
    player.enqueue(1, pcm(100), "m-2");

    ctx.sources[0]!.finish();
    ctx.sources[1]!.finish();
    expect(stopped).toEqual([]);
    player.enqueue(2, pcm(100), "m-2");
    player.end("m-2");
    expect(stopped).toEqual([]);
    ctx.sources[2]!.finish();

    expect(stopped).toEqual(["m-2"]);
    player.end("m-2");
    player.stop();
    expect(stopped).toEqual(["m-2"]);
  });

  it("an end with the queue already empty reports at once", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    const stopped: string[] = [];
    player.onStopped = (messageId) => stopped.push(messageId);
    player.begin("m-4");
    player.enqueue(0, pcm(100), "m-4");
    ctx.sources[0]!.finish();

    player.end("m-4");

    expect(stopped).toEqual(["m-4"]);
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

  it("routes every source through one passive analyser into the destination", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    ctx.currentTime = 1;

    player.enqueue(0, pcm(500));
    player.enqueue(1, pcm(500));

    expect(ctx.analysers).toHaveLength(1);
    const analyser = ctx.analysers[0]!;
    expect(analyser.target).toBe(ctx.destination);
    expect(analyser.fftSize).toBe(512);
    expect(analyser.smoothingTimeConstant).toBe(0);
    expect(ctx.sources.map((s) => s.target)).toEqual([analyser, analyser]);
    expect(ctx.sources.map((s) => s.started)).toEqual([1, 1.5]);
  });

  it("reports the playback amplitude normalised to the meter's full scale", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    player.enqueue(0, pcm(500));

    ctx.analysers[0]!.signal = 0.1;
    expect(player.amplitude()).toBeCloseTo(0.5, 6);
    ctx.analysers[0]!.signal = 0.9;
    expect(player.amplitude()).toBe(1);
    ctx.analysers[0]!.signal = 0;
    expect(player.amplitude()).toBe(0);
  });

  it("reports 0 before any audio context exists", () => {
    expect(new PcmPlayer(() => new FakeContext() as unknown as AudioContext).amplitude()).toBe(0);
  });

  it("reports 0 once stopped and after the queue drains", () => {
    const ctx = new FakeContext();
    const player = new PcmPlayer(() => ctx as unknown as AudioContext);
    player.enqueue(0, pcm(500));
    ctx.analysers[0]!.signal = 0.1;

    player.stop();
    expect(player.amplitude()).toBe(0);

    player.begin();
    player.enqueue(0, pcm(100));
    expect(player.amplitude()).toBeGreaterThan(0);
    ctx.sources[1]!.finish();
    expect(player.amplitude()).toBe(0);
  });

  it("creates its audio context once and resumes it only while suspended", () => {
    const ctx = new FakeContext();
    let created = 0;
    let resumed = 0;
    ctx.resume = async () => {
      resumed += 1;
      ctx.state = "running";
    };
    const player = new PcmPlayer(() => {
      created += 1;
      return ctx as unknown as AudioContext;
    });

    player.enqueue(0, pcm(100));
    expect(resumed).toBe(0);
    ctx.state = "suspended";
    player.enqueue(1, pcm(100));

    expect(created).toBe(1);
    expect(resumed).toBe(1);
  });
});
