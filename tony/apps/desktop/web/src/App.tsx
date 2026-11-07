import { memo, useCallback, useEffect, useReducer, useRef, useState } from "react";

import { connectBridge } from "./bridge/channel";
import type { Command, CoreEvent, TonyBridge } from "./bridge/types";
import { ActivityPanel } from "./components/ActivityPanel";
import { AudioSettingsOverlay } from "./components/AudioSettingsOverlay";
import { ChatPanel } from "./components/ChatPanel";
import { ConfirmationCard } from "./components/ConfirmationCard";
import { MicButton } from "./components/MicButton";
import { PinOverlay } from "./components/PinOverlay";
import { ReplyModeSelector } from "./components/ReplyModeSelector";
import type { OrbScene } from "./orb/scene";
import { deriveOrbState, type OrbState } from "./orb/orbState";
import { OrbStage } from "./orb/OrbStage";
import { initialState, reduce } from "./state/reducer";

/** The core publishes levels every 50 ms: an older one means the sound has stopped. */
const LEVEL_STALE_MS = 150;
const ORB_REFRESH_MS = 100;

const Chat = memo(ChatPanel);
const Activity = memo(ActivityPanel);

interface Props {
  connect?: () => Promise<TonyBridge>;
  createScene?: (canvas: HTMLCanvasElement) => OrbScene;
  webglAvailable?: () => boolean;
}

interface Level {
  value: number;
  at: number;
}

export function App({ connect = connectBridge, createScene, webglAvailable }: Props) {
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const [focusRequest, setFocusRequest] = useState(0);
  const [orbState, setOrbState] = useState<OrbState>("idle");
  const bridge = useRef<TonyBridge | null>(null);
  const level = useRef<Level>({ value: 0, at: 0 });
  const lastOutputAt = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const refreshOrb = useCallback(() => {
    const { confirmation, voice, thinking } = stateRef.current;
    setOrbState(
      deriveOrbState(
        { confirming: confirmation !== null, voice: voice.state, thinking, lastOutputAt: lastOutputAt.current },
        Date.now(),
      ),
    );
  }, []);

  const onEvent = useCallback(
    (event: CoreEvent) => {
      const now = Date.now();
      if (event.type !== "voice_level") {
        dispatch({ kind: "event", event, now });
        return;
      }
      level.current = { value: event.level, at: now };
      if (event.source === "output") {
        lastOutputAt.current = now;
        if (stateRef.current.thinking) {
          dispatch({ kind: "output_started" });
        }
        refreshOrb();
      }
    },
    [refreshOrb],
  );

  useEffect(() => {
    let closed = false;
    connect().then(
      (connected) => {
        if (closed) {
          return;
        }
        bridge.current = connected;
        connected.onEvent(onEvent);
        connected.onFocusConfirmation(() => setFocusRequest((n) => n + 1));
      },
      (error: unknown) => {
        const message = error instanceof Error ? error.message : String(error);
        dispatch({ kind: "event", event: { type: "error", ts: "", source: "page", message }, now: Date.now() });
      },
    );
    return () => {
      closed = true;
    };
  }, [connect, onEvent]);

  useEffect(refreshOrb, [refreshOrb, state.confirmation, state.voice.state, state.thinking]);

  useEffect(() => {
    const timer = setInterval(refreshOrb, ORB_REFRESH_MS);
    return () => clearInterval(timer);
  }, [refreshOrb]);

  const freshLevel = useCallback(() => {
    const { value, at } = level.current;
    return Date.now() - at < LEVEL_STALE_MS ? value : 0;
  }, []);

  const send = useCallback((command: Command) => bridge.current?.send(command), []);
  const sendText = useCallback(
    (text: string) => {
      send({ type: "send_message", text });
      dispatch({ kind: "sent", text });
    },
    [send],
  );
  const answer = useCallback(
    (command: Command) => {
      send(command);
      dispatch({ kind: "confirmation_answered" });
    },
    [send],
  );
  return (
    <>
      <OrbStage
        state={orbState}
        level={0}
        getLevel={freshLevel}
        getAmplitude={freshLevel}
        {...(createScene ? { createScene } : {})}
        {...(webglAvailable ? { webglAvailable } : {})}
      />
      <ReplyModeSelector mode={state.replyMode} onCommand={send} />
      <MicButton voice={state.voice} onCommand={send} />
      <Chat messages={state.messages} onSend={sendText} />
      <div className="side-panels">
        <Activity tasks={state.tasks} servers={state.servers} />
      </div>
      {state.confirmation ? (
        <ConfirmationCard confirmation={state.confirmation} onAnswer={answer} focusRequest={focusRequest} />
      ) : null}
      <PinOverlay
        pin={state.pin}
        onCommand={send}
        onHide={() => dispatch({ kind: "pin_cancelled" })}
        onUnlockRequest={() => dispatch({ kind: "unlock_requested" })}
      />
      <AudioSettingsOverlay devices={state.audioDevices} onCommand={send} />
    </>
  );
}
