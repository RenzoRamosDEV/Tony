import { normalizeLevel, rms } from "../orb/amplitude";

export const OUTPUT_RATE = 24000;
const ANALYSER_FFT_SIZE = 512;

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

/**
 * Gapless playback of Int16 PCM chunks: each buffer starts exactly where the previous ends.
 * `onStopped` fires once per message, when its queue drains after `end` or when it is stopped.
 */
export class PcmPlayer {
  onDrain: (() => void) | null = null;
  onStopped: ((messageId: string) => void) | null = null;
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private readonly samples = new Float32Array(ANALYSER_FFT_SIZE);
  private nextStartTime = 0;
  private lastSeq = -1;
  private readonly sources = new Set<AudioBufferSourceNode>();
  private current: string | null = null;
  private ended = false;
  private readonly finishedMessages = new Set<string>();

  constructor(private readonly createContext: () => AudioContext = defaultContext) {}

  get playing(): boolean {
    return this.sources.size > 0;
  }

  /** A new reply starts its chunk sequence at 0 again. */
  begin(messageId: string | null = null): void {
    this.lastSeq = -1;
    this.current = messageId;
    this.ended = false;
  }

  enqueue(seq: number, pcm16: ArrayBuffer, messageId: string | null = null): boolean {
    if (seq <= this.lastSeq || (messageId !== null && this.finishedMessages.has(messageId))) {
      return false;
    }
    this.lastSeq = seq;
    const context = this.contextOrCreate();
    const floats = int16ToFloat32(pcm16);
    const buffer = context.createBuffer(1, floats.length, OUTPUT_RATE);
    buffer.getChannelData(0).set(floats);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyserOf(context));
    const start = Math.max(this.nextStartTime, context.currentTime);
    source.onended = () => this.finished(source);
    source.start(start);
    this.nextStartTime = start + buffer.duration;
    this.sources.add(source);
    return true;
  }

  /** Output level in [0, 1], read by the orb once per frame; 0 when nothing is sounding. */
  amplitude(): number {
    if (this.analyser === null || this.sources.size === 0) {
      return 0;
    }
    this.analyser.getFloatTimeDomainData(this.samples);
    return normalizeLevel(rms(this.samples));
  }

  /** The server sent every chunk of the message: it is reported once its queue drains. */
  end(messageId: string): void {
    if (messageId !== this.current) {
      return;
    }
    this.ended = true;
    if (this.sources.size === 0) {
      this.report();
    }
  }

  /** Stops every scheduled source at once; later chunks of the stopped message are dropped. */
  stop(messageId: string | null = this.current): void {
    const pending = Array.from(this.sources);
    this.sources.clear();
    for (const source of pending) {
      source.onended = null;
      source.stop();
    }
    this.nextStartTime = 0;
    if (messageId !== null && messageId === this.current) {
      this.report();
    } else if (messageId !== null) {
      this.finishedMessages.add(messageId);
    }
  }

  private report(): void {
    const messageId = this.current;
    if (messageId === null || this.finishedMessages.has(messageId)) {
      return;
    }
    this.finishedMessages.add(messageId);
    this.onStopped?.(messageId);
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

  /** A passive tap between the sources and the speakers: it reads the signal without changing it. */
  private analyserOf(context: AudioContext): AnalyserNode {
    if (this.analyser === null) {
      this.analyser = context.createAnalyser();
      this.analyser.fftSize = ANALYSER_FFT_SIZE;
      this.analyser.smoothingTimeConstant = 0;
      this.analyser.connect(context.destination);
    }
    return this.analyser;
  }

  private finished(source: AudioBufferSourceNode): void {
    this.sources.delete(source);
    if (this.sources.size === 0) {
      this.nextStartTime = 0;
      if (this.ended) {
        this.report();
      }
      this.onDrain?.();
    }
  }
}
