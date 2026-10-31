import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { createApi } from "./api/client";
import type { MicCaptureDeps } from "./audio/capture";
import { PERMISSION_DENIED, useMicCapture, usePcmPlayer } from "./audio/hooks";
import { applyToPlayback } from "./audio/playbackEvents";
import { ConfirmationCard } from "./components/ConfirmationCard";
import { EngineReadout } from "./components/EngineReadout";
import { ModeReadout } from "./components/ModeReadout";
import { deriveOrbState } from "./orb/orbState";
import { OrbStage } from "./orb/OrbStage";
import type { Message } from "./protocol/reducer";
import { initialState, reduce } from "./protocol/reducer";
import { ChatSocket, defaultSocketUrl } from "./protocol/socket";
import { AUDIO_START_PAYLOAD, type Envelope, type ReplyMode } from "./protocol/types";

export const CONVERSATION_KEY = "tony.conversation_id";

let requestCounter = 0;

function newClientId(): string {
  requestCounter += 1;
  return `${Date.now().toString(36)}-${requestCounter.toString(36)}`;
}

function lastExchange(messages: Message[]): { question: Message | null; reply: Message | null } {
  let questionIndex = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]!.role === "user") {
      questionIndex = i;
      break;
    }
  }
  let reply: Message | null = null;
  for (let i = messages.length - 1; i > questionIndex; i -= 1) {
    if (messages[i]!.role === "assistant") {
      reply = messages[i]!;
      break;
    }
  }
  return { question: questionIndex >= 0 ? messages[questionIndex]! : null, reply };
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
  const [, setHistoryReady] = useState(false);
  const [engineChanging, setEngineChanging] = useState(false);
  const [clock, setClock] = useState(() => new Date());
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
    const timer = setInterval(() => {
      dispatch({ type: "tick", now: Date.now() });
      setClock(new Date());
    }, 1000);
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

  const onModeChanged = useCallback((mode: ReplyMode) => dispatch({ type: "set_reply_mode", mode }), []);
  const newConversation = useCallback(() => socketRef.current?.newConversation(), []);

  const inputDisabled = engineChanging || !state.connected || state.turnInProgress || state.pendingText !== null;

  const orbState = deriveOrbState({
    phase: state.voice.phase,
    mic: state.voice.mic,
    playing: player.playing,
    turnInProgress: state.turnInProgress,
    activeRootId: state.activeRootId,
  });

  const { question, reply } = lastExchange(state.messages);
  const [draft, setDraft] = useState("");
  const submit = () => {
    const trimmed = draft.trim();
    if (!trimmed || inputDisabled) return;
    if (send(trimmed) !== false) setDraft("");
  };

  return (
    <>
      <OrbStage state={orbState} level={mic.level} getAmplitude={player.amplitude} />

      <div className="hud-corner hud-corner-tl">
        <div className="corner-bracket" />
        <h1 className="hud-brand">TONY</h1>
        <div className="hud-readout">
          <span className="hud-label">Hora</span>
          <span className="hud-value hud-clock">{clock.toLocaleTimeString("es-ES", { hour12: false })}</span>
        </div>
        <EngineReadout disabled={inputDisabled} fetchImpl={fetchImpl} onBusy={setEngineChanging} />
      </div>

      <div className="hud-corner hud-corner-tr">
        <div className="corner-bracket" />
        <div className="hud-readout">
          <span className="hud-label">Enlace</span>
          <span className={state.connected ? "hud-value hud-ok" : "hud-value hud-warn"}>
            {state.connected ? "ACTIVO" : "CAÍDO"}
          </span>
        </div>
        <div className="hud-readout">
          <span className="hud-label">Micrófono</span>
          <span className="hud-value">{micOn ? "ESCUCHANDO" : "APAGADO"}</span>
        </div>
        <button type="button" className="hud-btn" onClick={newConversation}>
          + Nueva
        </button>
      </div>

      <div className="hud-corner hud-corner-bl">
        <div className="corner-bracket" />
        <span className="hud-label">Conversación</span>
        <div className="hud-transcript">
          {question === null && reply === null ? <p className="hud-muted">Sin mensajes todavía.</p> : null}
          {question ? <p className="hud-line hud-q">» {question.content}</p> : null}
          {reply ? <p className="hud-line hud-a">{reply.content}</p> : null}
        </div>
      </div>

      <div className="hud-corner hud-corner-br">
        <div className="corner-bracket" />
        <ModeReadout value={state.replyMode} onChanged={onModeChanged} fetchImpl={fetchImpl} />
        <div className="hud-input-row">
          <button
            type="button"
            className={micOn ? "hud-mic active" : "hud-mic"}
            aria-pressed={micOn}
            aria-label={micOn ? "Silenciar micrófono" : "Activar micrófono"}
            onClick={() => void toggleMic()}
          >
            {micOn ? "●" : "○"}
          </button>
          <input
            className="hud-text-input"
            aria-label="Mensaje para Jarvis"
            placeholder="Escribe a Jarvis…"
            value={draft}
            disabled={inputDisabled}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submit();
              }
            }}
          />
          <button type="button" className="hud-btn" aria-label="Enviar" disabled={inputDisabled} onClick={submit}>
            ➤
          </button>
        </div>
      </div>

      {state.confirmation ? <ConfirmationCard confirmation={state.confirmation} onAnswer={answer} /> : null}
    </>
  );
}
