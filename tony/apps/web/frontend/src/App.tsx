import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { createApi } from "./api/client";
import type { MicCaptureDeps } from "./audio/capture";
import { PERMISSION_DENIED, useMicCapture, usePcmPlayer } from "./audio/hooks";
import { ChatList } from "./components/ChatList";
import { Composer } from "./components/Composer";
import { ConfirmationCard } from "./components/ConfirmationCard";
import { DebugPanel } from "./components/DebugPanel";
import { PlusIcon, StopIcon } from "./components/icons";
import { MicButton } from "./components/MicButton";
import { ModeSelector } from "./components/ModeSelector";
import { StatusBanner } from "./components/StatusBanner";
import { StopAudioButton } from "./components/StopAudioButton";
import { VoiceStatus } from "./components/VoiceStatus";
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
  const player = usePcmPlayer(audioContextFactory);
  const playerRef = useRef(player);
  playerRef.current = player;
  const mic = useMicCapture(micDeps, {
    onFrame: (frame) => void socketRef.current?.sendBinary(frame.buffer as ArrayBuffer),
    onSilenceAfterSpeech: () => dispatch({ type: "silence_after_speech" }),
  });

  useEffect(() => {
    const socket = new ChatSocket({
      url: defaultSocketUrl(window.location),
      onEnvelope: (envelope: Envelope) => {
        if (envelope.type === "tts.start") {
          playerRef.current.begin();
        } else if (envelope.type === "tts.cancelled") {
          playerRef.current.stop();
        }
        dispatch({ type: "envelope", envelope, now: Date.now() });
      },
      onBinary: (buffer) => {
        const meta = stateRef.current.voice.pendingMeta;
        if (meta === null) {
          return;
        }
        playerRef.current.enqueue(meta.seq, buffer);
        dispatch({ type: "binary_consumed" });
      },
      onStatus: (connected) => dispatch({ type: "connection", connected }),
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

  const speaking = state.voice.phase === "speaking" || player.playing;
  const setMuted = mic.setMuted;
  useEffect(() => {
    setMuted(speaking);
  }, [setMuted, speaking]);

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

  const speakingMessageId = state.voice.speakingMessageId;
  const stopAudio = useCallback(() => {
    player.stop();
    if (speakingMessageId !== null) {
      socketRef.current?.send({ type: "cancel", payload: { message_id: speakingMessageId } });
    }
    dispatch({ type: "stop_audio" });
  }, [player, speakingMessageId]);

  const onModeChanged = useCallback((mode: ReplyMode) => dispatch({ type: "set_reply_mode", mode }), []);
  const dismiss = useCallback(() => dispatch({ type: "dismiss_notice" }), []);
  const newConversation = useCallback(() => socketRef.current?.newConversation(), []);

  const inputDisabled = !state.connected || !historyReady || state.turnInProgress || state.pendingText !== null;

  return (
    <div className="layout">
      <main className="app">
        <header className="toolbar">
          <h1>Tony</h1>
          <ModeSelector value={state.replyMode} onChanged={onModeChanged} fetchImpl={fetchImpl} />
          <button type="button" className="icon" aria-label="Nueva conversación" onClick={newConversation}>
            <PlusIcon />
          </button>
        </header>
        <StatusBanner connected={state.connected} notice={state.notice} onDismiss={dismiss} />
        <ChatList messages={state.messages} waitText={state.waitText} />
        {state.confirmation ? <ConfirmationCard confirmation={state.confirmation} onAnswer={answer} /> : null}
        {activeRoot !== null ? (
          <button type="button" className="secondary cancel" onClick={cancel}>
            <StopIcon /> Cancelar tarea
          </button>
        ) : null}
        <div className="voice-bar">
          <MicButton voice={state.voice} onToggle={() => void toggleMic()} />
          <VoiceStatus voice={speaking ? { ...state.voice, phase: "speaking" } : state.voice} level={mic.level} />
          <StopAudioButton visible={speaking} onStop={stopAudio} />
        </div>
        <Composer disabled={inputDisabled} onSend={send} />
      </main>
      <DebugPanel state={state} storage={store} />
    </div>
  );
}
