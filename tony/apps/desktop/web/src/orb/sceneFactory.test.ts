import { describe, expect, it } from "vitest";

import { fakeContext } from "./fakeContext";
import { emptyParams } from "./orbParams";
import { loadSceneFactory } from "./sceneFactory";
import { createOrbScene } from "./scene";

function canvasWith(fake = fakeContext()) {
  return { canvas: { width: 0, height: 0, getContext: () => fake.ctx } as unknown as HTMLCanvasElement, fake };
}

describe("loadSceneFactory", () => {
  it("keeps the WebGL scene for holo", async () => {
    expect(await loadSceneFactory("holo")).toBe(createOrbScene);
  });

  it.each(["aurora", "instrumento"] as const)("builds a canvas 2d scene for %s", async (theme) => {
    const { canvas, fake } = canvasWith();
    const scene = (await loadSceneFactory(theme))(canvas);

    scene.resize(400, 300, 1);
    scene.update(emptyParams(), 16);

    expect(fake.called("clearRect")).toBe(1);
    expect(fake.calls.length).toBeGreaterThan(10);
  });

  it("draws different pictures for aurora and instrumento", async () => {
    const [a, b] = [canvasWith(), canvasWith()];
    (await loadSceneFactory("aurora"))(a.canvas).update(emptyParams(), 16);
    (await loadSceneFactory("instrumento"))(b.canvas).update(emptyParams(), 16);

    expect(JSON.stringify(a.fake.calls)).not.toBe(JSON.stringify(b.fake.calls));
  });
});
