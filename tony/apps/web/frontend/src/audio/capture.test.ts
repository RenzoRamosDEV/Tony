import { describe, expect, it } from "vitest";

import { MIC_CONSTRAINTS, MicCapture } from "./capture";
import { rms, SilenceDetector } from "./level";

class FakeTrack {
  stopped = false;
  stop(): void {
    this.stopped = true;
  }
}

class FakePort {
  onmessage: ((event: { data: Float32Array }) => void) | null = null;
  emit(frame: Float32Array): void {
    this.onmessage?.({ data: frame });
  }
}

class FakeNode {
  port = new FakePort();
  connect(): void {}
  disconnect(): void {}
}

class FakeContext {
  modules: (string | URL)[] = [];
  closed = false;
  sampleRate = 48000;
  audioWorklet = { addModule: async (url: string | URL) => void this.modules.push(url) };
  createMediaStreamSource() {
    return { connect: () => undefined, disconnect: () => undefined };
  }
  async close(): Promise<void> {
    this.closed = true;
  }
}

function harness(permission: "granted" | "denied" = "granted") {
  const tracks = [new FakeTrack()];
  const requests: MediaStreamConstraints[] = [];
  const context = new FakeContext();
  const node = new FakeNode();
  const capture = new MicCapture({
    getUserMedia: async (constraints) => {
      requests.push(constraints);
      if (permission === "denied") {
        throw new DOMException("denied", "NotAllowedError");
      }
      return { getTracks: () => tracks } as unknown as MediaStream;
    },
    createContext: () => context as unknown as AudioContext,
    createNode: () => node as unknown as AudioWorkletNode,
    workletUrl: "worklet.js",
  });
  return { capture, tracks, requests, context, node };
}

describe("MicCapture", () => {
  it("asks for a mono microphone with echo cancellation and loads the worklet", async () => {
    const { capture, requests, context } = harness();

    await capture.start();

    expect(requests).toEqual([MIC_CONSTRAINTS]);
    expect(MIC_CONSTRAINTS).toEqual({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    expect(context.modules).toEqual(["worklet.js"]);
    expect(capture.active).toBe(true);
  });

  it("forwards every worklet frame and reports its level", async () => {
    const { capture, node } = harness();
    const frames: Float32Array[] = [];
    const levels: number[] = [];
    capture.onFrame = (frame) => frames.push(frame);
    capture.onLevel = (level) => levels.push(level);
    await capture.start();

    node.port.emit(new Float32Array(480).fill(0.5));
    node.port.emit(new Float32Array(480).fill(0.25));

    expect(frames.map((f) => f[0])).toEqual([0.5, 0.25]);
    expect(levels.map((l) => Number(l.toFixed(3)))).toEqual([0.5, 0.25]);
    expect("muted" in capture).toBe(false);
  });

  it("stop releases the tracks and closes the context", async () => {
    const { capture, tracks, context, node } = harness();
    const frames: Float32Array[] = [];
    capture.onFrame = (frame) => frames.push(frame);
    await capture.start();

    capture.stop();
    node.port.emit(new Float32Array(480).fill(0.5));

    expect(tracks[0]!.stopped).toBe(true);
    expect(context.closed).toBe(true);
    expect(capture.active).toBe(false);
    expect(frames).toHaveLength(0);
  });

  it("rejects with NotAllowedError when the permission is denied", async () => {
    const { capture, context } = harness("denied");

    await expect(capture.start()).rejects.toMatchObject({ name: "NotAllowedError" });
    expect(context.modules).toEqual([]);
    expect(capture.active).toBe(false);
  });
});

describe("level", () => {
  it("rms of a constant frame is its magnitude and silence is zero", () => {
    expect(rms(new Float32Array(4).fill(-0.5))).toBeCloseTo(0.5);
    expect(rms(new Float32Array(4))).toBe(0);
    expect(rms(new Float32Array(0))).toBe(0);
  });

  it("detects 500 ms of silence after speech exactly once per utterance", () => {
    const detector = new SilenceDetector();

    expect(detector.update(0.3, 0)).toBe(false);
    expect(detector.update(0.001, 100)).toBe(false);
    expect(detector.update(0.001, 499)).toBe(false);
    expect(detector.update(0.001, 500)).toBe(true);
    expect(detector.update(0.001, 2000)).toBe(false);
    expect(detector.update(0.3, 2100)).toBe(false);
    expect(detector.update(0.001, 2599)).toBe(false);
    expect(detector.update(0.001, 2600)).toBe(true);
  });

  it("forgets the speech heard while the reply was playing", () => {
    const detector = new SilenceDetector();

    detector.update(0.3, 0);
    detector.reset();

    expect(detector.update(0.001, 600)).toBe(false);
  });

  it("never fires without speech first", () => {
    const detector = new SilenceDetector();

    expect(detector.update(0, 0)).toBe(false);
    expect(detector.update(0, 5000)).toBe(false);
  });
});

describe("MicCapture (review of change 05)", () => {
  it("finding 9: a second start while the first is pending acquires the microphone once", async () => {
    const { capture, requests } = harness();

    await Promise.all([capture.start(), capture.start()]);
    await capture.start();

    expect(requests).toHaveLength(1);
    expect(capture.active).toBe(true);
  });

  it("finding 9: a worklet that fails to load releases the tracks and the context", async () => {
    const { capture, tracks, context } = harness();
    context.audioWorklet.addModule = async () => {
      throw new Error("no worklet");
    };

    await expect(capture.start()).rejects.toThrow("no worklet");

    expect(tracks[0]!.stopped).toBe(true);
    expect(context.closed).toBe(true);
    expect(capture.active).toBe(false);
  });

  it("finding 9: stop during a pending start leaves nothing acquired", async () => {
    const { capture, tracks, context } = harness();

    const starting = capture.start();
    capture.stop();
    await starting.catch(() => undefined);

    expect(capture.active).toBe(false);
    expect(tracks[0]!.stopped).toBe(true);
    expect(context.closed).toBe(true);
  });
});
