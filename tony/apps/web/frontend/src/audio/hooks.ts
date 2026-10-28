import { useCallback, useEffect, useRef, useState } from "react";

import { browserDeps, MicCapture, type MicCaptureDeps } from "./capture";
import { SilenceDetector } from "./level";
import { PcmPlayer } from "./player";

export const PERMISSION_DENIED = "No se pudo acceder al micrófono: revisa el permiso del navegador.";
const LEVEL_STEPS = 50;

interface MicHandlers {
  onFrame: (frame: Float32Array) => void;
  onSilenceAfterSpeech: () => void;
}

/** One lazily created MicCapture per page; `level` is the RMS of the last frame. */
export function useMicCapture(deps: MicCaptureDeps | undefined, handlers: MicHandlers) {
  const capture = useRef<MicCapture | null>(null);
  const silence = useRef(new SilenceDetector());
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  const [level, setLevel] = useState(0);

  const instance = useCallback((): MicCapture => {
    if (capture.current === null) {
      const created = new MicCapture(deps ?? browserDeps());
      created.onFrame = (frame) => handlersRef.current.onFrame(frame);
      created.onLevel = (rms) => {
        // Frames arrive every 30 ms: only a visible change of the meter re-renders.
        const quantised = Math.round(rms * LEVEL_STEPS) / LEVEL_STEPS;
        setLevel((previous) => (previous === quantised ? previous : quantised));
        if (silence.current.update(rms, Date.now())) {
          handlersRef.current.onSilenceAfterSpeech();
        }
      };
      capture.current = created;
    }
    return capture.current;
  }, [deps]);

  useEffect(() => () => capture.current?.stop(), []);

  const start = useCallback(() => instance().start(), [instance]);
  const stop = useCallback(() => {
    capture.current?.stop();
    setLevel(0);
  }, []);
  const setMuted = useCallback((muted: boolean) => {
    if (capture.current) {
      capture.current.muted = muted;
    }
  }, []);
  return { start, stop, setMuted, level };
}

/** One PcmPlayer per page; `playing` flips on the first chunk and back when the queue drains. */
export function usePcmPlayer(createContext: (() => AudioContext) | undefined) {
  const player = useRef<PcmPlayer | null>(null);
  const [playing, setPlaying] = useState(false);

  const instance = useCallback((): PcmPlayer => {
    if (player.current === null) {
      const created = createContext ? new PcmPlayer(createContext) : new PcmPlayer();
      created.onDrain = () => setPlaying(false);
      player.current = created;
    }
    return player.current;
  }, [createContext]);

  const begin = useCallback(() => instance().begin(), [instance]);
  const enqueue = useCallback(
    (seq: number, pcm16: ArrayBuffer) => {
      if (instance().enqueue(seq, pcm16)) {
        setPlaying(true);
      }
    },
    [instance],
  );
  const stop = useCallback(() => {
    player.current?.stop();
    setPlaying(false);
  }, []);
  return { begin, enqueue, stop, playing };
}
