import { FrameAccumulator, Resampler, TARGET_RATE } from "./resample";

declare const sampleRate: number;
declare function registerProcessor(name: string, processor: unknown): void;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
}

export const PROCESSOR_NAME = "tony-capture";

/** Resamples the device audio to 16 kHz mono and posts 30 ms Float32 frames (transferred). */
class CaptureProcessor extends AudioWorkletProcessor {
  private readonly frames = new FrameAccumulator((frame) => this.port.postMessage(frame, [frame.buffer]));
  private readonly resampler = new Resampler(sampleRate, TARGET_RATE);

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];
    if (channel && channel.length > 0) {
      this.frames.push(this.resampler.process(channel));
    }
    return true;
  }
}

registerProcessor(PROCESSOR_NAME, CaptureProcessor);
