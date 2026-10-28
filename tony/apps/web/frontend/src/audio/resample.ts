/** Samples per frame sent to the server: 30 ms at 16 kHz. */
export const FRAME_SAMPLES = 480;
export const TARGET_RATE = 16000;

/**
 * Block-averaging resampler for a continuous stream (enough for speech, runs in the audio
 * thread): the fractional read position and the unconsumed input carry over between blocks,
 * so 128-sample worklet blocks neither drift in length nor jump at their edges.
 */
export class Resampler {
  private readonly ratio: number;
  private residual = new Float32Array(0);
  private position = 0;

  constructor(fromRate: number, toRate: number) {
    this.ratio = fromRate / toRate;
  }

  process(input: Float32Array): Float32Array {
    if (this.ratio === 1) {
      return Float32Array.from(input);
    }
    const data = new Float32Array(this.residual.length + input.length);
    data.set(this.residual);
    data.set(input, this.residual.length);
    const output: number[] = [];
    let start = this.position;
    while (start + this.ratio <= data.length) {
      const first = Math.floor(start);
      const end = Math.max(first + 1, Math.floor(start + this.ratio));
      let sum = 0;
      for (let j = first; j < end; j += 1) {
        sum += data[j]!;
      }
      output.push(sum / (end - first));
      start += this.ratio;
    }
    const kept = Math.floor(start);
    this.residual = data.slice(kept);
    this.position = start - kept;
    return Float32Array.from(output);
  }
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
