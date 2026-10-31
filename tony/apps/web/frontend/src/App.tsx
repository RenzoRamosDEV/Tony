import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { createApi } from "./api/client";
import type { MicCaptureDeps } from "./audio/capture";
import { useMicCapture, usePcmPlayer } from "./audio/hooks";
import { applyToPlayback } from "./audio/playbackEvents";
import { ConfirmationCard } from "./components/ConfirmationCard";
import { deriveOrbState } from "./orb/orbState";
import { OrbStage } from "./orb/OrbStage";
import { initialState, reduce } from "./protocol/reducer";
import { ChatSocket, defaultSocketUrl } from "./protocol/socket";
import type { Envelope } from "./protocol/types";

export const CONVERSATION_KEY = "tony.conversation_id";

interface Props {
  socketFactory?: (url: string) => WebSocket;
  fetchImpl?: typeof fetch;
  storage?: Storage;
  micDeps?: MicCaptureDeps;
  audioContextFactory?: () => AudioContext;
}

/** The server refused the capture: the microphone must really stop, not only look off. */
function isCaptureRejection(envelope: Envelope): boolean {
  const code = envelope.type === "error" ? envelope.payload.code : null;
  return code === "voice_unavailable" || code === "unsupported_audio";
}

function readStorage(storage: Storage | undefined, key: string): string | null {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function writeStorage(storage: Storage | undefined, key: string, value: string): void {
  try {
    storage?.setItem(key, value);
  } catch {
    return;
  }
}

export function App({ socketFactory, fetchImpl, storage, micDeps, audioContextFactory }: Props) {
  const [state, dispatch] = useReducer(reduce, initialState);
  const [, setHistoryReady] = useState(false);
  const api = useMemo(() => createApi(fetchImpl), [fetchImpl]);
  const store = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
  const stateRef = useRef(state);
  stateRef.current = state;
  const socketRef = useRef<ChatSocket | null>(null);
  const reportStopped = useCallback((messageId: string) => {
    socketRef.current?.send({ type: "playback.stopped", payload: { message_id: messageId } });
  }, []);
  const player = usePcmPlayer(audioContextFactory, reportStopped);
  const playerRef = useRef(player);
  playerRef.current = player;
  const mic = useMicCapture(micDeps, {
    onFrame: (frame) => void socketRef.current?.sendBinary(frame.buffer as ArrayBuffer),
    onSilenceAfterSpeech: () => dispatch({ type: "silence_after_speech" }),
    replyPlaying: () => playerRef.current.isPlaying(),
  });
  const stopMic = mic.stop;

  useEffect(() => {
    const socket = new ChatSocket({
      url: defaultSocketUrl(window.location),
      onEnvelope: (envelope: Envelope) => {
        applyToPlayback(envelope, playerRef.current);
        if (envelope.type === "hello.ok" || isCaptureRejection(envelope)) {
          stopMic();
        }
        dispatch({ type: "envelope", envelope, now: Date.now() });
      },
      onAudio: (meta, buffer) => playerRef.current.enqueue(meta.seq, buffer, meta.messageId),
      onStatus: (connected) => {
        if (!connected) {
          stopMic();
        }
        dispatch({ type: "connection", connected });
      },
      conversationId: () => stateRef.current.conversationId ?? readStorage(store, CONVERSATION_KEY),
      lastSeq: () => stateRef.current.lastSeq,
      ...(socketFactory ? { factory: socketFactory } : {}),
    });
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
    // The socket lives for the whole page; its callbacks read the latest state through the ref.
  }, []);

  const conversationId = state.conversationId;
  const resyncRequested = state.resyncRequested;
  useEffect(() => {
    if (conversationId === null) {
      return;
    }
    writeStorage(store, CONVERSATION_KEY, conversationId);
    let cancelled = false;
    setHistoryReady(false);
    api
      .getMessages(conversationId)
      .then((messages) => {
        if (!cancelled) {
          dispatch({ type: "history", messages });
          setHistoryReady(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHistoryReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, conversationId, resyncRequested, store]);

  const turnInProgress = state.turnInProgress;
  useEffect(() => {
    if (turnInProgress || conversationId === null) {
      return;
    }
    api
      .getSettings()
      .then((settings) => dispatch({ type: "set_reply_mode", mode: settings.reply_mode }))
      .catch(() => undefined);
  }, [api, turnInProgress, conversationId]);

  useEffect(() => {
    const timer = setInterval(() => dispatch({ type: "tick", now: Date.now() }), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    api
      .getHealth()
      .then((health) => dispatch({ type: "voice_health", available: health.voice.available, reason: health.voice.reason }))
      .catch(() => undefined);
  }, [api]);

  const synthesizing = state.voice.phase === "speaking";
  const speaking = synthesizing || player.playing;
  const heardMessageId = state.voice.speakingMessageId;
  useEffect(() => {
    if (!speaking && heardMessageId !== null) {
      dispatch({ type: "playback_drained" });
    }
  }, [speaking, heardMessageId]);

  const answer = useCallback((confirmationId: string, approved: boolean) => {
    socketRef.current?.send({ type: "confirm", payload: { confirmation_id: confirmationId, approved } });
  }, []);

  const orbState = deriveOrbState({
    phase: state.voice.phase,
    mic: state.voice.mic,
    playing: player.playing,
    turnInProgress: state.turnInProgress,
    activeRootId: state.activeRootId,
  });

  return (
    <>
      <OrbStage state={orbState} level={mic.level} getAmplitude={player.amplitude} />
      {state.confirmation ? <ConfirmationCard confirmation={state.confirmation} onAnswer={answer} /> : null}
    </>
  );
}
