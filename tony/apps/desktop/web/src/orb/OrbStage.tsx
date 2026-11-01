import { type MutableRefObject, useEffect, useRef, useState } from "react";

import { AmplitudeSmoother } from "./amplitude";
import { OrbFallback } from "./OrbFallback";
import { emptyParams, targetParams } from "./orbParams";
import type { OrbState } from "./orbState";
import type { OrbScene } from "./scene";
import { approachParams } from "./tween";
import { isWebGLAvailable } from "./webgl";

type SceneFactory = (canvas: HTMLCanvasElement) => OrbScene;

export interface OrbStageProps {
  state: OrbState;
  level: number;
  getAmplitude: () => number;
  createScene?: SceneFactory;
  webglAvailable?: () => boolean;
}

interface OrbInputs {
  state: OrbState;
  level: number;
  getAmplitude: () => number;
}

const TRANSITION_MS = 300;
const AUTO_ROTATE_DELAY_MS = 4000;
const FIRST_FRAME_MS = 16;
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

const browserWebGL = () => isWebGLAvailable(document);

/** Wires a scene to the page: render loop, visibility, resize, reduced motion and drag. */
function runOrb(
  scene: OrbScene,
  canvas: HTMLCanvasElement,
  inputs: MutableRefObject<OrbInputs>,
  onContextLost: () => void,
): () => void {
  const motion = window.matchMedia?.(REDUCED_MOTION_QUERY);
  let reducedMotion = motion?.matches ?? false;
  const smoother = new AmplitudeSmoother();
  const target = emptyParams();
  const current = targetParams(inputs.current.state, inputs.current.level, 0, reducedMotion);
  let frame: number | null = null;
  let lastTime: number | null = null;
  let resumeTimer: ReturnType<typeof setTimeout> | undefined;

  const render = (now: number) => {
    const dtMs = lastTime === null ? FIRST_FRAME_MS : now - lastTime;
    lastTime = now;
    const { state, level, getAmplitude } = inputs.current;
    const amplitude = smoother.update(getAmplitude(), dtMs);
    targetParams(state, level, amplitude, reducedMotion, target);
    approachParams(current, target, dtMs, TRANSITION_MS);
    scene.update(current, dtMs);
    frame = requestAnimationFrame(render);
  };
  const start = () => {
    if (frame === null && document.visibilityState !== "hidden") {
      lastTime = null;
      frame = requestAnimationFrame(render);
    }
  };
  const stop = () => {
    if (frame !== null) {
      cancelAnimationFrame(frame);
      frame = null;
    }
  };
  const onVisibility = () => (document.visibilityState === "hidden" ? stop() : start());
  const onResize = () => scene.resize(window.innerWidth, window.innerHeight, window.devicePixelRatio || 1);
  const onMotion = (event: { matches: boolean }) => {
    reducedMotion = event.matches;
    scene.setAutoRotate(!reducedMotion);
  };
  const onContextLostEvent = (event: Event) => {
    event.preventDefault();
    onContextLost();
  };
  const unsubscribe = scene.onInteraction(
    () => {
      clearTimeout(resumeTimer);
      scene.setAutoRotate(false);
    },
    () => {
      clearTimeout(resumeTimer);
      resumeTimer = setTimeout(() => scene.setAutoRotate(!reducedMotion), AUTO_ROTATE_DELAY_MS);
    },
  );

  onResize();
  scene.setAutoRotate(!reducedMotion);
  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", onVisibility);
  motion?.addEventListener("change", onMotion);
  canvas.addEventListener("webglcontextlost", onContextLostEvent);
  start();

  return () => {
    stop();
    clearTimeout(resumeTimer);
    unsubscribe();
    window.removeEventListener("resize", onResize);
    document.removeEventListener("visibilitychange", onVisibility);
    motion?.removeEventListener("change", onMotion);
    canvas.removeEventListener("webglcontextlost", onContextLostEvent);
    scene.dispose();
  };
}

export function OrbStage({
  state,
  level,
  getAmplitude,
  createScene,
  webglAvailable = browserWebGL,
}: OrbStageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(() => !webglAvailable());
  const inputs = useRef<OrbInputs>({ state, level, getAmplitude });
  inputs.current = { state, level, getAmplitude };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (failed || canvas === null) {
      return;
    }
    let stopOrb: (() => void) | undefined;
    let unmounted = false;
    const start = (factory: SceneFactory) => {
      if (unmounted) {
        return;
      }
      try {
        stopOrb = runOrb(factory(canvas), canvas, inputs, () => setFailed(true));
      } catch {
        setFailed(true);
      }
    };
    if (createScene) {
      start(createScene);
    } else {
      // Three.js is only downloaded when WebGL is there to use it.
      import("./scene").then(
        (module) => start(module.createOrbScene),
        () => setFailed(true),
      );
    }
    return () => {
      unmounted = true;
      stopOrb?.();
    };
  }, [failed, createScene]);

  return (
    <div className="stage" aria-hidden="true" data-orb-state={state}>
      {failed ? <OrbFallback /> : <canvas ref={canvasRef} className="orb-canvas" />}
    </div>
  );
}
