import { act, render } from "@testing-library/react";
import { Profiler } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrbStage, type OrbStageProps } from "./OrbStage";
import { type OrbParams, targetParams } from "./orbParams";
import type { OrbScene } from "./scene";

class FakeScene implements OrbScene {
  updates: { params: OrbParams; dtMs: number }[] = [];
  resizes: [number, number, number][] = [];
  autoRotate: boolean[] = [];
  disposed = 0;
  start: (() => void) | null = null;
  end: (() => void) | null = null;
  update(params: OrbParams, dtMs: number): void {
    this.updates.push({ params: { ...params }, dtMs });
  }
  resize(width: number, height: number, dpr: number): void {
    this.resizes.push([width, height, dpr]);
  }
  setAutoRotate(enabled: boolean): void {
    this.autoRotate.push(enabled);
  }
  onInteraction(start: () => void, end: () => void): () => void {
    this.start = start;
    this.end = end;
    return () => {
      this.start = null;
      this.end = null;
    };
  }
  dispose(): void {
    this.disposed += 1;
  }
  get last(): OrbParams {
    return this.updates[this.updates.length - 1]!.params;
  }
}

let frames = new Map<number, FrameRequestCallback>();
let nextFrame = 1;
let clock = 0;
let reducedMotion = false;
let motionListeners: ((event: { matches: boolean }) => void)[] = [];

function step(count = 1, ms = 16): void {
  for (let i = 0; i < count; i += 1) {
    clock += ms;
    const pending = Array.from(frames.values());
    frames = new Map();
    act(() => pending.forEach((callback) => callback(clock)));
  }
}

function setHidden(hidden: boolean): void {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: hidden ? "hidden" : "visible" });
  Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function stage(overrides: Partial<OrbStageProps> = {}) {
  const scene = new FakeScene();
  const props: OrbStageProps = {
    state: "idle",
    level: 0,
    getAmplitude: () => 0,
    createScene: () => scene,
    webglAvailable: () => true,
    ...overrides,
  };
  const view = render(<OrbStage {...props} />);
  return { scene, view, props, container: view.container.querySelector(".stage") as HTMLElement };
}

beforeEach(() => {
  frames = new Map();
  nextFrame = 1;
  clock = 0;
  reducedMotion = false;
  motionListeners = [];
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const id = nextFrame;
    nextFrame += 1;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("reduce") ? reducedMotion : false,
    media: query,
    addEventListener: (_type: string, listener: (event: { matches: boolean }) => void) => motionListeners.push(listener),
    removeEventListener: (_type: string, listener: (event: { matches: boolean }) => void) => {
      motionListeners = motionListeners.filter((l) => l !== listener);
    },
  }));
  setHidden(false);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("OrbStage", () => {
  it("is decorative and exposes its state", () => {
    const { container, view } = stage({ state: "thinking" });

    expect(container).toHaveAttribute("aria-hidden", "true");
    expect(container).toHaveAttribute("data-orb-state", "thinking");
    expect(view.container.querySelector("canvas")).not.toBeNull();
  });

  it("sizes the scene to the window on mount", () => {
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 3 });
    const { scene } = stage();

    expect(scene.resizes[0]).toEqual([window.innerWidth, window.innerHeight, 3]);
  });

  it("renders a frame per animation frame with the measured dt", () => {
    const { scene } = stage();

    step(3, 20);

    expect(scene.updates).toHaveLength(3);
    expect(scene.updates[1]!.dtMs).toBe(20);
  });

  it("stops scheduling frames while the tab is hidden and resumes on return", () => {
    const { scene } = stage();
    step(2);

    setHidden(true);
    step(5);
    expect(scene.updates).toHaveLength(2);
    expect(frames.size).toBe(0);

    setHidden(false);
    step(2);
    expect(scene.updates).toHaveLength(4);
    expect(scene.updates[2]!.dtMs).toBe(16);
  });

  it("cancels the loop and disposes the scene on unmount", () => {
    const { scene, view } = stage();
    step(1);

    view.unmount();

    expect(frames.size).toBe(0);
    expect(scene.disposed).toBe(1);
    expect(scene.start).toBeNull();
  });

  it("eases towards the new state instead of jumping", () => {
    const { scene, view, props } = stage({ state: "idle" });
    step(2);
    const idleRings = scene.last.ringSpeed;

    view.rerender(<OrbStage {...props} state="thinking" />);
    step(1);
    const firstStep = scene.last.ringSpeed;
    step(150);

    expect(firstStep).toBeGreaterThan(idleRings);
    expect(firstStep).toBeLessThan(scene.last.ringSpeed / 2);
    expect(scene.last.ringSpeed).toBeCloseTo(1.8, 2);
  });

  it("reads the playback amplitude every frame without re-rendering", () => {
    const getAmplitude = vi.fn(() => 1);
    const scene = new FakeScene();
    let commits = 0;
    render(
      <Profiler id="orb" onRender={() => (commits += 1)}>
        <OrbStage state="speaking" level={0} getAmplitude={getAmplitude} createScene={() => scene} webglAvailable={() => true} />
      </Profiler>,
    );
    const afterMount = commits;

    step(30);

    expect(getAmplitude).toHaveBeenCalledTimes(30);
    expect(commits).toBe(afterMount);
    const silent = targetParams("speaking", 0, 0, false).displacement;
    const loud = targetParams("speaking", 0, 1, false).displacement;
    expect(scene.last.displacement).toBeGreaterThan(silent + (loud - silent) * 0.7);
  });

  it("feeds the microphone level into listening", () => {
    const { scene, view, props } = stage({ state: "listening", level: 0 });
    step(30);
    const quiet = scene.last.coreScale;

    view.rerender(<OrbStage {...props} level={1} />);
    step(60);

    expect(quiet).toBeCloseTo(1, 3);
    expect(scene.last.coreScale).toBeGreaterThan(1.3);
  });

  it("reads the listening level from getLevel on every frame without re-rendering", () => {
    let level = 0;
    const { scene } = stage({ state: "listening", level: 0, getLevel: () => level });
    step(30);
    const quiet = scene.last.coreScale;

    level = 1;
    step(60);

    expect(quiet).toBeCloseTo(1, 3);
    expect(scene.last.coreScale).toBeGreaterThan(1.3);
  });

  it("with reduced motion the orb stops moving and does not auto-rotate", () => {
    reducedMotion = true;
    const { scene } = stage({ state: "speaking", getAmplitude: () => 1 });

    step(10);

    expect(scene.last.spin).toBe(0);
    expect(scene.last.displacement).toBe(0);
    expect(scene.last.agitation).toBe(0);
    expect(scene.last.glow).toBeGreaterThan(1);
    expect(scene.autoRotate[scene.autoRotate.length - 1]).toBe(false);
  });

  it("follows a live change of the reduced-motion preference", () => {
    const { scene } = stage({ state: "thinking" });
    step(2);
    expect(scene.last.spin).toBeGreaterThan(0);

    act(() => motionListeners.forEach((listener) => listener({ matches: true })));
    step(200);

    expect(scene.last.spin).toBeCloseTo(0, 3);
    expect(scene.autoRotate[scene.autoRotate.length - 1]).toBe(false);
  });

  it("stops auto-rotation while dragging and resumes it 4 s after the drag ends", () => {
    const { scene } = stage();
    act(() => scene.start!());
    expect(scene.autoRotate[scene.autoRotate.length - 1]).toBe(false);

    act(() => scene.end!());
    act(() => vi.advanceTimersByTime(3999));
    expect(scene.autoRotate[scene.autoRotate.length - 1]).toBe(false);
    act(() => vi.advanceTimersByTime(1));

    expect(scene.autoRotate[scene.autoRotate.length - 1]).toBe(true);
  });

  it("a new drag before the 4 s cancels the pending resume", () => {
    const { scene } = stage();
    act(() => scene.start!());
    act(() => scene.end!());
    act(() => vi.advanceTimersByTime(2000));
    act(() => scene.start!());
    act(() => vi.advanceTimersByTime(5000));

    expect(scene.autoRotate[scene.autoRotate.length - 1]).toBe(false);
  });

  it("shows the CSS orb without WebGL", () => {
    const createScene = vi.fn();
    const { view, container } = stage({ webglAvailable: () => false, createScene, state: "speaking" });

    expect(createScene).not.toHaveBeenCalled();
    expect(view.container.querySelector(".orb-fallback")).not.toBeNull();
    expect(view.container.querySelector("canvas")).toBeNull();
    expect(container).toHaveAttribute("data-orb-state", "speaking");
    expect(frames.size).toBe(0);
  });

  it("shows the CSS orb when creating the scene throws", () => {
    const { view } = stage({
      createScene: () => {
        throw new Error("no context");
      },
    });

    expect(view.container.querySelector(".orb-fallback")).not.toBeNull();
    expect(frames.size).toBe(0);
  });

  it("falls back to the CSS orb when the WebGL context is lost", () => {
    const { view, scene } = stage();
    step(1);

    act(() => {
      view.container.querySelector("canvas")!.dispatchEvent(new Event("webglcontextlost"));
    });

    expect(view.container.querySelector(".orb-fallback")).not.toBeNull();
    expect(scene.disposed).toBe(1);
    expect(frames.size).toBe(0);
  });
});
