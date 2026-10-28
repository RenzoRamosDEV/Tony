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

  constructor(private readonly deps: MicCaptureDeps) {}

  get active(): boolean {
    return this.stream !== null;
  }

  async start(): Promise<void> {
    const stream = await this.deps.getUserMedia(MIC_CONSTRAINTS);
    const context = this.deps.createContext();
    await context.audioWorklet.addModule(this.deps.workletUrl);
    const node = this.deps.createNode(context);
    node.port.onmessage = (event: MessageEvent<Float32Array>) => this.handle(event.data);
    context.createMediaStreamSource(stream).connect(node);
    this.stream = stream;
    this.context = context;
    this.node = node;
  }

  stop(): void {
    const { stream, context, node } = this;
    this.stream = null;
    this.context = null;
    this.node = null;
    if (node) {
      node.port.onmessage = null;
      node.disconnect();
    }
    stream?.getTracks().forEach((track) => track.stop());
    void context?.close();
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
