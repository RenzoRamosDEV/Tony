import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { createApi } from "./api/client";
import type { MicCaptureDeps } from "./audio/capture";
import { PERMISSION_DENIED, useMicCapture, usePcmPlayer } from "./audio/hooks";
import { applyToPlayback } from "./audio/playbackEvents";
import { ConfirmationCard } from "./components/ConfirmationCard";
import { DebugPanel } from "./components/DebugPanel";
import { HudBar } from "./components/HudBar";
import { PlusIcon } from "./components/icons";
import { StatusBanner } from "./components/StatusBanner";
import { Subtitles } from "./components/Subtitles";
import { TranscriptDrawer } from "./components/TranscriptDrawer";
import { deriveOrbState } from "./orb/orbState";
import { OrbStage } from "./orb/OrbStage";
import { initialState, reduce } from "./protocol/reducer";
import { ChatSocket, defaultSocketUrl } from "./protocol/socket";
import { AUDIO_START_PAYLOAD, type Envelope, type ReplyMode } from "./protocol/types";

export const CONVERSATION_KEY = "tony.conversation_id";

let requestCounter = 0;

function newClientId(): string {
  requestCounter += 1;
  return `${Date.now().toString(36)}-${requestCounter.toString(36)}`;
}

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
  const [historyReady, setHistoryReady] = useState(false);
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

  const send = useCallback((text: string): boolean => {
    const clientId = newClientId();
    const sent = socketRef.current?.send({ type: "user.text", payload: { text, client_id: clientId } }) ?? false;
    if (sent) {
      dispatch({ type: "sent", text, clientId });
    }
    return sent;
  }, []);

  const answer = useCallback((confirmationId: string, approved: boolean) => {
    socketRef.current?.send({ type: "confirm", payload: { confirmation_id: confirmationId, approved } });
  }, []);

  const activeRoot = state.activeRootId;
  const cancel = useCallback(() => {
    if (activeRoot !== null) {
      socketRef.current?.send({ type: "cancel", payload: { task_id: activeRoot } });
    }
  }, [activeRoot]);

  const micOn = state.voice.mic === "on";
  const toggleMic = useCallback(async () => {
    if (micOn) {
      socketRef.current?.send({ type: "audio.end", payload: {} });
      mic.stop();
      dispatch({ type: "mic", on: false });
      return;
    }
    try {
      await mic.start();
    } catch {
      dispatch({ type: "notice", text: PERMISSION_DENIED });
      return;
    }
    socketRef.current?.send({ type: "audio.start", payload: { ...AUDIO_START_PAYLOAD } });
    dispatch({ type: "mic", on: true });
  }, [mic, micOn]);

  const stopAudio = useCallback(() => {
    player.stop();
    if (synthesizing && heardMessageId !== null) {
      socketRef.current?.send({ type: "cancel", payload: { message_id: heardMessageId } });
    }
    dispatch({ type: "stop_audio" });
  }, [player, synthesizing, heardMessageId]);

  const onModeChanged = useCallback((mode: ReplyMode) => dispatch({ type: "set_reply_mode", mode }), []);
  const dismiss = useCallback(() => dispatch({ type: "dismiss_notice" }), []);
  const newConversation = useCallback(() => socketRef.current?.newConversation(), []);

  const inputDisabled = !state.connected || !historyReady || state.turnInProgress || state.pendingText !== null;

  const orbState = deriveOrbState({
    phase: state.voice.phase,
    mic: state.voice.mic,
    playing: player.playing,
    turnInProgress: state.turnInProgress,
    activeRootId: activeRoot,
  });

  return (
    <>
      <OrbStage state={orbState} level={mic.level} getAmplitude={player.amplitude} />
      <main className="hud">
        <header className="hud-top">
          <h1 className="brand">Tony</h1>
          <div className="hud-actions">
            <TranscriptDrawer messages={state.messages} waitText={state.waitText} />
            <button type="button" className="icon" aria-label="Nueva conversación" onClick={newConversation}>
              <PlusIcon />
            </button>
          </div>
        </header>
        <StatusBanner connected={state.connected} notice={state.notice} onDismiss={dismiss} />
        <Subtitles messages={state.messages} waitText={state.waitText} />
        <HudBar
          voice={state.voice}
          level={mic.level}
          speaking={speaking}
          replyMode={state.replyMode}
          onModeChanged={onModeChanged}
          fetchImpl={fetchImpl}
          inputDisabled={inputDisabled}
          onSend={send}
          onToggleMic={() => void toggleMic()}
          onStopAudio={stopAudio}
          canCancel={activeRoot !== null}
          onCancel={cancel}
        />
      </main>
      {state.confirmation ? <ConfirmationCard confirmation={state.confirmation} onAnswer={answer} /> : null}
      <DebugPanel state={state} storage={store} />
    </>
  );
}
