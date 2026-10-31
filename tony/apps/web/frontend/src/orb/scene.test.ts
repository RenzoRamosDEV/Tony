import { AdditiveBlending, LineSegments, Material, Object3D, Points, Scene, ShaderMaterial, Sprite, Texture } from "three";
import { describe, expect, it, vi } from "vitest";

import { PARTICLE_COUNT } from "./geometry";
import { emptyParams, type OrbParams } from "./orbParams";
import { type ComposerLike, type ControlsLike, createOrbScene, CORE_SIZE, MAX_PIXEL_RATIO, type RendererLike } from "./scene";

type Listener = () => void;

function fakeRenderer() {
  return {
    setPixelRatio: vi.fn(),
    setSize: vi.fn(),
    setClearColor: vi.fn(),
    dispose: vi.fn(),
  } satisfies RendererLike;
}

function fakeComposer() {
  return {
    render: vi.fn(),
    setSize: vi.fn(),
    setPixelRatio: vi.fn(),
    dispose: vi.fn(),
    bloom: { strength: 0, radius: 0, threshold: 0 },
  } satisfies ComposerLike;
}

class FakeControls implements ControlsLike {
  enablePan = true;
  enableZoom = true;
  enableDamping = false;
  dampingFactor = 0;
  minDistance = 0;
  maxDistance = Infinity;
  autoRotate = false;
  autoRotateSpeed = 0;
  listeners = new Map<string, Set<Listener>>();
  update = vi.fn();
  dispose = vi.fn();
  addEventListener(type: "start" | "end", listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }
  removeEventListener(type: "start" | "end", listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }
  emit(type: "start" | "end"): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener();
    }
  }
}

function build() {
  const renderer = fakeRenderer();
  const composer = fakeComposer();
  const controls = new FakeControls();
  let scene: Scene | null = null;
  const orb = createOrbScene(document.createElement("canvas"), {
    createRenderer: () => renderer,
    createComposer: (_renderer, created) => {
      scene = created;
      return composer;
    },
    createControls: () => controls,
  });
  return { orb, renderer, composer, controls, scene: scene! as Scene };
}

function params(overrides: Partial<OrbParams> = {}): OrbParams {
  return { ...emptyParams(), glow: 1, bloom: 1, ...overrides };
}

function named<T extends Object3D>(scene: Scene, name: string): T {
  const found = scene.getObjectByName(name);
  if (!found) {
    throw new Error(`no ${name}`);
  }
  return found as T;
}

function uniformsOf(object: Object3D): Record<string, { value: unknown }> {
  return ((object as LineSegments).material as ShaderMaterial).uniforms;
}

describe("createOrbScene", () => {
  it("builds geodesic shells, fragment shells, arcs, streaks, particles and a core", () => {
    const { scene } = build();

    const geodesic = named(scene, "geodesic").children;
    expect(geodesic.length).toBeGreaterThanOrEqual(2);
    expect(geodesic.length).toBeLessThanOrEqual(3);
    expect(geodesic.every((child) => child instanceof LineSegments)).toBe(true);
    expect(named(scene, "fragments").children.length).toBeGreaterThanOrEqual(2);
    const arcs = named<LineSegments>(scene, "arcs");
    expect(arcs.userData.count).toBeGreaterThanOrEqual(4);
    expect(arcs.userData.count).toBeLessThanOrEqual(6);
    expect(named(scene, "streaks")).toBeInstanceOf(LineSegments);
    const cloud = named<Points>(scene, "particles");
    expect(cloud).toBeInstanceOf(Points);
    expect(cloud.geometry.getAttribute("position").count).toBe(PARTICLE_COUNT);
    const core = named<Sprite>(scene, "core");
    expect(core).toBeInstanceOf(Sprite);
    expect(core.material.map).toBeInstanceOf(Texture);
  });

  it("draws everything with additive glow and no depth writes", () => {
    const { scene } = build();
    const materials: Material[] = [];
    scene.traverse((object) => {
      const material = (object as LineSegments).material as Material | undefined;
      if (material) {
        materials.push(material);
      }
    });

    expect(materials.length).toBeGreaterThan(5);
    for (const material of materials) {
      expect(material.blending).toBe(AdditiveBlending);
      expect(material.depthWrite).toBe(false);
      expect(material.transparent).toBe(true);
    }
  });

  it("keeps the draw calls low", () => {
    const { scene } = build();
    let drawables = 0;
    scene.traverse((object) => {
      if ((object as LineSegments).isLineSegments || (object as Points).isPoints || (object as Sprite).isSprite) {
        drawables += 1;
      }
    });

    expect(drawables).toBeLessThanOrEqual(14);
  });

  it("clears to the near-black background", () => {
    const { renderer } = build();

    expect(renderer.setClearColor).toHaveBeenCalledWith(0x05070a, 1);
  });

  it("applies the params to uniforms, scales and bloom, then renders once", () => {
    const { orb, scene, composer, controls } = build();

    orb.update(params({ displacement: 0.2, agitation: 0.5, coreScale: 1.3, shellScale: 1.1, bloom: 1.7, glow: 1.2 }), 16);

    const shell = named(scene, "geodesic").children[0]!;
    expect(uniformsOf(shell).uDisplacement!.value).toBe(0.2);
    expect(uniformsOf(named(scene, "particles")).uAgitation!.value).toBe(0.5);
    expect(uniformsOf(shell).uGlow!.value).toBeCloseTo(1.2, 6);
    expect(named(scene, "core").scale.x).toBeCloseTo(CORE_SIZE * 1.3, 6);
    expect(named(scene, "shells").scale.x).toBeCloseTo(1.1, 6);
    expect(composer.bloom.strength).toBeCloseTo(1.7, 6);
    expect(controls.update).toHaveBeenCalledTimes(1);
    expect(composer.render).toHaveBeenCalledTimes(1);
  });

  it("pulses the glow over time by the pulse amount", () => {
    const { orb, scene } = build();
    const shell = named(scene, "geodesic").children[0]!;
    const seen = new Set<number>();
    for (let i = 0; i < 40; i += 1) {
      orb.update(params({ pulse: 0.5 }), 50);
      seen.add(Math.round((uniformsOf(shell).uGlow!.value as number) * 100));
    }

    expect(Math.max(...seen) / 100).toBeGreaterThan(1.3);
    expect(Math.min(...seen) / 100).toBeLessThan(0.7);
  });

  it("spins proportionally to spin and ringSpeed, and not at all when both are 0", () => {
    const { orb, scene } = build();
    const shells = named(scene, "shells");
    const arcs = named(scene, "arcs");

    orb.update(params(), 16);
    expect(shells.rotation.y).toBe(0);
    expect(arcs.rotation.z).toBe(0);

    orb.update(params({ spin: 0.5, ringSpeed: 2 }), 100);
    expect(shells.rotation.y).toBeCloseTo(0.05, 6);
    expect(Math.abs(arcs.rotation.z)).toBeGreaterThan(0);
  });

  it("caps the pixel ratio at 2 on resize", () => {
    const { orb, renderer, composer } = build();

    orb.resize(1920, 1080, 3);

    expect(MAX_PIXEL_RATIO).toBe(2);
    expect(renderer.setPixelRatio).toHaveBeenLastCalledWith(2);
    expect(composer.setPixelRatio).toHaveBeenLastCalledWith(2);
    expect(renderer.setSize).toHaveBeenLastCalledWith(1920, 1080, false);
    expect(composer.setSize).toHaveBeenLastCalledWith(1920, 1080);
  });

  it("keeps a low pixel ratio as is", () => {
    const { orb, renderer } = build();

    orb.resize(800, 600, 1);

    expect(renderer.setPixelRatio).toHaveBeenLastCalledWith(1);
  });

  it("configures the controls: rotate and bounded zoom, no pan, damping, auto-rotation", () => {
    const { controls } = build();

    expect(controls.enablePan).toBe(false);
    expect(controls.enableZoom).toBe(false);
    expect(controls.enableDamping).toBe(true);
    expect(controls.minDistance).toBeGreaterThan(0);
    expect(controls.maxDistance).toBeGreaterThan(controls.minDistance);
    expect(Number.isFinite(controls.maxDistance)).toBe(true);
    expect(controls.autoRotate).toBe(true);
  });

  it("toggles auto-rotation and reports drags until unsubscribed", () => {
    const { orb, controls } = build();
    const start = vi.fn();
    const end = vi.fn();

    orb.setAutoRotate(false);
    expect(controls.autoRotate).toBe(false);
    const unsubscribe = orb.onInteraction(start, end);
    controls.emit("start");
    controls.emit("end");
    unsubscribe();
    controls.emit("start");

    expect(start).toHaveBeenCalledTimes(1);
    expect(end).toHaveBeenCalledTimes(1);
  });

  it("releases every geometry, material, texture, the composer, controls and renderer", () => {
    const { orb, scene, composer, controls, renderer } = build();
    const spies: ReturnType<typeof vi.spyOn>[] = [];
    scene.traverse((object) => {
      const drawable = object as LineSegments;
      if (drawable.geometry) {
        spies.push(vi.spyOn(drawable.geometry, "dispose"));
      }
      const material = drawable.material as Material | undefined;
      if (material) {
        spies.push(vi.spyOn(material, "dispose"));
      }
    });
    const texture = named<Sprite>(scene, "core").material.map!;
    const textureDispose = vi.spyOn(texture, "dispose");

    orb.dispose();

    expect(spies.length).toBeGreaterThan(10);
    for (const spy of spies) {
      expect(spy).toHaveBeenCalled();
    }
    expect(textureDispose).toHaveBeenCalled();
    expect(composer.dispose).toHaveBeenCalled();
    expect(controls.dispose).toHaveBeenCalled();
    expect(renderer.dispose).toHaveBeenCalled();
  });
});
