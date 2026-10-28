export const OUTPUT_RATE = 24000;

export function int16ToFloat32(buffer: ArrayBuffer): Float32Array {
  const samples = new Int16Array(buffer);
  const floats = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    floats[i] = samples[i]! / 32768;
  }
  return floats;
}

function defaultContext(): AudioContext {
  return new AudioContext({ sampleRate: OUTPUT_RATE });
}

/** Gapless playback of Int16 PCM chunks: each buffer starts exactly where the previous ends. */
export class PcmPlayer {
  onDrain: (() => void) | null = null;
  private context: AudioContext | null = null;
  private nextStartTime = 0;
  private lastSeq = -1;
  private readonly sources = new Set<AudioBufferSourceNode>();

  constructor(private readonly createContext: () => AudioContext = defaultContext) {}

  get playing(): boolean {
    return this.sources.size > 0;
  }

  /** A new reply starts its chunk sequence at 0 again. */
  begin(): void {
    this.lastSeq = -1;
  }

  enqueue(seq: number, pcm16: ArrayBuffer): boolean {
    if (seq <= this.lastSeq) {
      return false;
    }
    this.lastSeq = seq;
    const context = this.contextOrCreate();
    const floats = int16ToFloat32(pcm16);
    const buffer = context.createBuffer(1, floats.length, OUTPUT_RATE);
    buffer.getChannelData(0).set(floats);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const start = Math.max(this.nextStartTime, context.currentTime);
    source.onended = () => this.finished(source);
    source.start(start);
    this.nextStartTime = start + buffer.duration;
    this.sources.add(source);
    return true;
  }

  stop(): void {
    const pending = Array.from(this.sources);
    this.sources.clear();
    for (const source of pending) {
      source.onended = null;
      source.stop();
    }
    this.nextStartTime = 0;
  }

  private contextOrCreate(): AudioContext {
    if (this.context === null) {
      this.context = this.createContext();
    }
    if (this.context.state === "suspended") {
      void this.context.resume();
    }
    return this.context;
  }

  private finished(source: AudioBufferSourceNode): void {
    this.sources.delete(source);
    if (this.sources.size === 0) {
      this.nextStartTime = 0;
      this.onDrain?.();
    }
  }
}
