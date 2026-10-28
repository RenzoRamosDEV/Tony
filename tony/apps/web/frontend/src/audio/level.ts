export const SPEECH_RMS = 0.01;
export const SILENCE_AFTER_SPEECH_MS = 500;

export function rms(frame: Float32Array): number {
  if (frame.length === 0) {
    return 0;
  }
  let sum = 0;
  for (const value of frame) {
    sum += value * value;
  }
  return Math.sqrt(sum / frame.length);
}

/** UI heuristic: speech followed by SILENCE_AFTER_SPEECH_MS of quiet means "transcribing…". */
export class SilenceDetector {
  private lastSpeechAt: number | null = null;

  update(level: number, now: number): boolean {
    if (level > SPEECH_RMS) {
      this.lastSpeechAt = now;
      return false;
    }
    if (this.lastSpeechAt !== null && now - this.lastSpeechAt >= SILENCE_AFTER_SPEECH_MS) {
      this.lastSpeechAt = null;
      return true;
    }
    return false;
  }

  /** Forget the speech heard so far, e.g. while the reply plays through the speakers. */
  reset(): void {
    this.lastSpeechAt = null;
  }
}
