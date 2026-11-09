import { describe, expect, it, vi } from "vitest";

import { type OrbDrawing, createCanvasScene } from "./canvasScene";
import { fakeContext } from "./fakeContext";
import { emptyParams } from "./orbParams";

function setup(draw: OrbDrawing = vi.fn()) {
  const fake = fakeContext();
  const canvas = { width: 0, height: 0, getContext: () => fake.ctx } as unknown as HTMLCanvasElement;
  return { scene: createCanvasScene(canvas, draw), canvas, fake, draw };
}

describe("createCanvasScene", () => {
  it("throws when the canvas has no 2d context", () => {
    const canvas = { getContext: () => null } as unknown as HTMLCanvasElement;
    expect(() => createCanvasScene(canvas, vi.fn())).toThrow();
  });

  it("sizes the backing store by the device pixel ratio, capped at 2", () => {
    const { scene, canvas } = setup();

    scene.resize(400, 300, 1.5);
    expect([canvas.width, canvas.height]).toEqual([600, 450]);

    scene.resize(400, 300, 3);
    expect([canvas.width, canvas.height]).toEqual([800, 600]);
  });

  it("clears and draws the parameters each update", () => {
    const { scene, fake, draw } = setup();
    scene.resize(400, 300, 1);
    const params = { ...emptyParams(), glow: 0.7 };

    scene.update(params, 16);

    expect(fake.called("clearRect")).toBe(1);
    expect(draw).toHaveBeenCalledTimes(1);
    const [, width, height, drawn] = (draw as ReturnType<typeof vi.fn>).mock.calls[0]!;
    expect([width, height]).toEqual([400, 300]);
    expect(drawn.glow).toBe(0.7);
  });

  it("scales the drawing with the stage size within 0.5 and 1.3", () => {
    const { scene, draw } = setup();
    const scales = [100, 420, 5000].map((side) => {
      scene.resize(side, side, 1);
      scene.update(emptyParams(), 16);
      return (draw as ReturnType<typeof vi.fn>).mock.calls.at(-1)![5];
    });

    expect(scales).toEqual([0.5, 1, 1.3]);
  });

  it("advances spin, ring phase and time with the frame delta", () => {
    const { scene, draw } = setup();
    const params = { ...emptyParams(), spin: 2, ringSpeed: 3 };

    scene.update(params, 500);
    scene.update(params, 500);

    const clock = (draw as ReturnType<typeof vi.fn>).mock.calls.at(-1)![4];
    expect(clock).toEqual({ t: 1, rot: 2, ring: 3 });
  });

  it("freezes time while motion is disabled", () => {
    const { scene, draw } = setup();
    const params = { ...emptyParams(), spin: 2, ringSpeed: 3 };
    scene.update(params, 500);

    scene.setAutoRotate(false);
    scene.update(params, 500);

    const clock = (draw as ReturnType<typeof vi.fn>).mock.calls.at(-1)![4];
    expect(clock.t).toBe(0.5);

    scene.setAutoRotate(true);
    scene.update(params, 500);
    expect((draw as ReturnType<typeof vi.fn>).mock.calls.at(-1)![4].t).toBe(1);
  });

  it("has no interaction to subscribe to", () => {
    const { scene } = setup();
    const unsubscribe = scene.onInteraction(vi.fn(), vi.fn());
    expect(() => unsubscribe()).not.toThrow();
  });

  it("stops drawing after dispose", () => {
    const { scene, draw } = setup();

    scene.dispose();
    scene.update(emptyParams(), 16);

    expect(draw).not.toHaveBeenCalled();
  });
});
