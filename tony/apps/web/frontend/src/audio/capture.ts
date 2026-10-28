import workletUrl from "./capture.worklet.ts?worker&url";
import { rms } from "./level";

export const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};
export const PROCESSOR_NAME = "tony-capture";

export interface MicCaptureDeps {
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  createContext: () => AudioContext;
  createNode: (context: AudioContext) => AudioWorkletNode;
  workletUrl: string | URL;
}

export function browserDeps(): MicCaptureDeps {
  return {
    getUserMedia: (constraints) => navigator.mediaDevices.getUserMedia(constraints),
    createContext: () => new AudioContext(),
    createNode: (context) => new AudioWorkletNode(context, PROCESSOR_NAME),
    workletUrl,
  };
}

/** Microphone -> AudioWorklet -> 16 kHz frames; `muted` drops frames without closing the mic. */
export class MicCapture {
  muted = false;
  onFrame: ((frame: Float32Array) => void) | null = null;
  onLevel: ((level: number) => void) | null = null;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private starting: Promise<void> | null = null;
  private generation = 0;

  constructor(private readonly deps: MicCaptureDeps) {}

  get active(): boolean {
    return this.stream !== null;
  }

  /** Idempotent: a call while active or starting shares the same acquisition. */
  start(): Promise<void> {
    if (this.active) {
      return Promise.resolve();
    }
    if (this.starting === null) {
      const starting = this.acquire(this.generation).finally(() => {
        if (this.starting === starting) {
          this.starting = null;
        }
      });
      this.starting = starting;
    }
    return this.starting;
  }

  /** Releases the microphone and abandons any start still waiting for permission or the worklet. */
  stop(): void {
    this.generation += 1;
    this.starting = null;
    const { stream, context, node } = this;
    this.stream = null;
    this.context = null;
    this.node = null;
    release(stream, context, node);
  }

  private async acquire(generation: number): Promise<void> {
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    let node: AudioWorkletNode | null = null;
    try {
      stream = await this.deps.getUserMedia(MIC_CONSTRAINTS);
      context = this.deps.createContext();
      if (generation === this.generation) {
        await context.audioWorklet.addModule(this.deps.workletUrl);
      }
      if (generation !== this.generation) {
        release(stream, context, node);
        return;
      }
      node = this.deps.createNode(context);
      node.port.onmessage = (event: MessageEvent<Float32Array>) => this.handle(event.data);
      context.createMediaStreamSource(stream).connect(node);
    } catch (error) {
      release(stream, context, node);
      throw error;
    }
    this.stream = stream;
    this.context = context;
    this.node = node;
  }

  private handle(frame: Float32Array): void {
    if (!this.active) {
      return;
    }
    this.onLevel?.(rms(frame));
    if (!this.muted) {
      this.onFrame?.(frame);
    }
  }
}

function release(stream: MediaStream | null, context: AudioContext | null, node: AudioWorkletNode | null): void {
  if (node) {
    node.port.onmessage = null;
    node.disconnect();
  }
  stream?.getTracks().forEach((track) => track.stop());
  void context?.close();
}
