/** Samples per frame sent to the server: 30 ms at 16 kHz. */
export const FRAME_SAMPLES = 480;
export const TARGET_RATE = 16000;

/** Block-averaging resampler: enough for speech, no dependencies, runs in the audio thread. */
export function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) {
    return Float32Array.from(input);
  }
  const ratio = fromRate / toRate;
  const length = Math.round((input.length * toRate) / fromRate);
  const output = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for (let j = start; j < end; j += 1) {
      sum += input[j] ?? 0;
    }
    output[i] = sum / (end - start);
  }
  return output;
}

/** Groups a stream of samples into fixed frames, keeping the remainder for the next push. */
export class FrameAccumulator {
  private buffer = new Float32Array(FRAME_SAMPLES);
  private filled = 0;

  constructor(private readonly onFrame: (frame: Float32Array) => void) {}

  get pending(): number {
    return this.filled;
  }

  push(samples: Float32Array): void {
    let offset = 0;
    while (offset < samples.length) {
      const take = Math.min(FRAME_SAMPLES - this.filled, samples.length - offset);
      this.buffer.set(samples.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;
      if (this.filled === FRAME_SAMPLES) {
        const frame = this.buffer;
        this.buffer = new Float32Array(FRAME_SAMPLES);
        this.filled = 0;
        this.onFrame(frame);
      }
    }
  }
}
