import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  DataTexture,
  EdgesGeometry,
  Group,
  HalfFloatType,
  IcosahedronGeometry,
  LineSegments,
  type Material,
  type Object3D,
  PerspectiveCamera,
  Points,
  Scene,
  ShaderMaterial,
  Spherical,
  Sprite,
  SpriteMaterial,
  Vector2,
  WebGLRenderer,
  WebGLRenderTarget,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

import { arcs, fragmentShell, particles, radialStreaks, segmentShades } from "./geometry";
import type { OrbParams } from "./orbParams";

export interface RendererLike {
  setPixelRatio(ratio: number): void;
  setSize(width: number, height: number, updateStyle?: boolean): void;
  setClearColor(color: number, alpha: number): void;
  dispose(): void;
}

export interface ComposerLike {
  render(): void;
  setSize(width: number, height: number): void;
  setPixelRatio(ratio: number): void;
  dispose(): void;
  bloom: { strength: number; radius: number; threshold: number };
}

type InteractionEvent = "start" | "end";

export interface ControlsLike {
  enablePan: boolean;
  enableZoom: boolean;
  enableDamping: boolean;
  dampingFactor: number;
  minDistance: number;
  maxDistance: number;
  autoRotate: boolean;
  autoRotateSpeed: number;
  update(deltaSeconds?: number): void;
  dispose(): void;
  addEventListener(type: InteractionEvent, listener: () => void): void;
  removeEventListener(type: InteractionEvent, listener: () => void): void;
}

export interface OrbSceneDeps {
  createRenderer?: (canvas: HTMLCanvasElement) => RendererLike;
  createComposer?: (renderer: RendererLike, scene: Scene, camera: PerspectiveCamera) => ComposerLike;
  createControls?: (camera: PerspectiveCamera, element: HTMLElement) => ControlsLike;
}

export interface OrbScene {
  update(params: OrbParams, dtMs: number): void;
  resize(width: number, height: number, devicePixelRatio: number): void;
  setAutoRotate(enabled: boolean): void;
  onInteraction(start: () => void, end: () => void): () => void;
  dispose(): void;
}

export const MAX_PIXEL_RATIO = 2;
export const CORE_SIZE = 0.55;
const BACKGROUND = 0x05070a;
const AMBER = "#ffb347";
const DEEP_AMBER = "#ff8c1a";
const CORE_GOLD = "#ffd27a";
const PULSE_RATE = 3.2;
const ARC_COUNT = 6;
const CAMERA_DISTANCE = 5.9;

const LINE_VERTEX = /* glsl */ `
  #define SPARKLE 1.7
  attribute float shade;
  uniform float uTime;
  uniform float uDisplacement;
  uniform float uGlow;
  uniform float uOpacity;
  uniform float uFlicker;
  uniform float uLimb;
  varying float vIntensity;
  varying float vShade;
  void main() {
    vec3 p = position;
    float wave = sin(p.x * 3.1 + uTime * 1.3) * sin(p.y * 2.7 - uTime * 1.1) * sin(p.z * 3.7 + uTime * 1.7);
    p *= 1.0 + uDisplacement * wave;
    vec4 view = modelViewMatrix * vec4(p, 1.0);
    vec3 centre = (modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    float facing = normalize(view.xyz - centre + vec3(0.0, 0.0, 1e-4)).z;
    float depth = mix(0.1, 1.0, smoothstep(-0.9, 0.6, facing));
    float limb = 1.0 + uLimb * pow(1.0 - abs(facing), 3.0);
    float flicker = 1.0 - uFlicker + uFlicker * (0.5 + 0.5 * sin(uTime * (1.5 + shade * 4.0) + shade * 91.0));
    vIntensity = SPARKLE * shade * shade * depth * limb * flicker * uGlow * uOpacity;
    vShade = shade;
    gl_Position = projectionMatrix * view;
  }
`;

const LINE_FRAGMENT = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  varying float vIntensity;
  varying float vShade;
  void main() {
    gl_FragColor = vec4(mix(uColorA, uColorB, vShade * vShade * vShade) * vIntensity, 1.0);
  }
`;

const POINT_VERTEX = /* glsl */ `
  attribute float shade;
  uniform float uTime;
  uniform float uAgitation;
  uniform float uGlow;
  uniform float uOpacity;
  uniform float uSize;
  uniform float uPixelRatio;
  varying float vIntensity;
  varying float vShade;
  void main() {
    float seed = shade * 47.0;
    vec3 p = position + uAgitation * 0.09 * vec3(
      sin(uTime * 6.1 + seed), sin(uTime * 7.3 + seed * 1.7), sin(uTime * 5.3 + seed * 2.3));
    vec4 view = modelViewMatrix * vec4(p, 1.0);
    vec3 centre = (modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    float facing = normalize(view.xyz - centre + vec3(0.0, 0.0, 1e-4)).z;
    vIntensity = shade * mix(0.25, 1.0, facing * 0.5 + 0.5) * uGlow * uOpacity;
    vShade = shade;
    gl_PointSize = uSize * uPixelRatio * (0.4 + shade) * (5.0 / -view.z);
    gl_Position = projectionMatrix * view;
  }
`;

const POINT_FRAGMENT = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  varying float vIntensity;
  varying float vShade;
  void main() {
    float fade = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
    gl_FragColor = vec4(mix(uColorA, uColorB, vShade) * vIntensity * fade, 1.0);
  }
`;

interface SharedUniforms {
  uTime: { value: number };
  uDisplacement: { value: number };
  uAgitation: { value: number };
  uGlow: { value: number };
  uPixelRatio: { value: number };
}

interface LayerStyle {
  opacity: number;
  flicker: number;
  limb?: number;
  colorA?: string;
  colorB?: string;
}

function glowMaterial(shared: SharedUniforms, style: LayerStyle, vertexShader: string, fragmentShader: string) {
  return new ShaderMaterial({
    uniforms: {
      ...shared,
      uOpacity: { value: style.opacity },
      uFlicker: { value: style.flicker },
      uLimb: { value: style.limb ?? 0 },
      uSize: { value: 2.2 },
      uColorA: { value: new Color(style.colorA ?? DEEP_AMBER) },
      uColorB: { value: new Color(style.colorB ?? AMBER) },
    },
    vertexShader,
    fragmentShader,
    blending: AdditiveBlending,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  });
}

/** Line segments with one random brightness per segment, so the dashes flicker unevenly. */
function lineGeometry(positions: Float32Array, seed: number, minShade: number): BufferGeometry {
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new BufferAttribute(positions, 3));
  geometry.setAttribute("shade", new BufferAttribute(segmentShades(seed, positions.length / 6, minShade), 1));
  return geometry;
}

/** Points with one random brightness each. */
function pointGeometry(positions: Float32Array, seed: number, minShade: number): BufferGeometry {
  const geometry = new BufferGeometry();
  const count = positions.length / 3;
  geometry.setAttribute("position", new BufferAttribute(positions, 3));
  geometry.setAttribute("shade", new BufferAttribute(segmentShades(seed, count, minShade).subarray(0, count), 1));
  return geometry;
}

function lines(name: string, geometry: BufferGeometry, material: ShaderMaterial): LineSegments {
  const object = new LineSegments(geometry, material);
  object.name = name;
  return object;
}

function geodesicShell(radius: number, detail: number, seed: number): BufferGeometry {
  const ico = new IcosahedronGeometry(radius, detail);
  const edges = new EdgesGeometry(ico);
  ico.dispose();
  const positions = edges.getAttribute("position").array as Float32Array;
  edges.dispose();
  return lineGeometry(positions, seed, 0.35);
}

/** Radial falloff baked into a small texture: no canvas needed, so it also builds in jsdom. */
function radialTexture(size: number, hardness: number): DataTexture {
  const data = new Uint8Array(size * size * 4);
  const half = (size - 1) / 2;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const distance = Math.min(1, Math.hypot(x - half, y - half) / half);
      const falloff = Math.pow(1 - distance, hardness);
      const value = Math.round(255 * Math.min(1, falloff + 0.6 * Math.pow(1 - distance, hardness * 6)));
      const offset = (y * size + x) * 4;
      data[offset] = value;
      data[offset + 1] = value;
      data[offset + 2] = value;
      data[offset + 3] = value;
    }
  }
  const texture = new DataTexture(data, size, size);
  texture.needsUpdate = true;
  return texture;
}

function glowSprite(name: string, texture: DataTexture, color: string, opacity: number): Sprite {
  const sprite = new Sprite(
    new SpriteMaterial({ map: texture, color, opacity, blending: AdditiveBlending, transparent: true, depthWrite: false, depthTest: false }),
  );
  sprite.name = name;
  return sprite;
}

function buildOrb(shared: SharedUniforms) {
  const orb = new Group();
  orb.name = "shells";

  const geodesic = new Group();
  geodesic.name = "geodesic";
  const geodesicLayers: [number, number, number][] = [
    [1.0, 3, 0.12],
    [1.32, 2, 0.1],
    [0.72, 2, 0.12],
  ];
  geodesicLayers.forEach(([radius, detail, opacity], index) => {
    const layer = lines(
      `geodesic-${index}`,
      geodesicShell(radius, detail, 10 + index),
      glowMaterial(shared, { opacity, flicker: 0.3, limb: 1.5 }, LINE_VERTEX, LINE_FRAGMENT),
    );
    layer.rotation.set(index * 0.7, index * 1.3, index * 0.4);
    geodesic.add(layer);
  });

  const fragments = new Group();
  fragments.name = "fragments";
  const fragmentLayers: [number, number, number, number][] = [
    [0.86, 1800, 0.5, 14],
    [1.12, 3000, 0.55, 18],
    [1.38, 2200, 0.45, 22],
  ];
  fragmentLayers.forEach(([radius, count, opacity, bands], index) => {
    const positions = fragmentShell(20 + index, { radius, count, minLength: 0.02, maxLength: 0.16, bands });
    const layer = lines(
      `fragments-${index}`,
      lineGeometry(positions, 30 + index, 0.15),
      glowMaterial(shared, { opacity, flicker: 0.6, limb: 2.5 }, LINE_VERTEX, LINE_FRAGMENT),
    );
    layer.rotation.set(index * 0.5, index * 0.9, 0);
    fragments.add(layer);
  });

  const arcLines = lines(
    "arcs",
    lineGeometry(
      arcs(40, { count: ARC_COUNT, minRadius: 1.2, maxRadius: 1.62, minSweep: 0.8, maxSweep: 3.6, segments: 128, strands: 4 }),
      41,
      0.55,
    ),
    glowMaterial(shared, { opacity: 0.6, flicker: 0.15, colorB: CORE_GOLD }, LINE_VERTEX, LINE_FRAGMENT),
  );
  arcLines.userData.count = ARC_COUNT;

  // Short sparks tucked just inside the outermost shell, never poking past its
  // silhouette, so the orb reads as one solid form instead of a loose starburst.
  const streaks = lines(
    "streaks",
    lineGeometry(
      radialStreaks(50, { count: 140, innerRadius: 0.5, outerRadius: 1.3, minLength: 0.02, maxLength: 0.08 }),
      51,
      0.3,
    ),
    glowMaterial(shared, { opacity: 0.22, flicker: 0.35 }, LINE_VERTEX, LINE_FRAGMENT),
  );

  const cloudPositions = particles(60);
  const cloud = new Points(
    pointGeometry(cloudPositions, 61, 0.1),
    glowMaterial(shared, { opacity: 0.5, flicker: 0 }, POINT_VERTEX, POINT_FRAGMENT),
  );
  cloud.name = "particles";

  orb.add(geodesic, fragments, arcLines, streaks, cloud);
  return orb;
}

function buildCore(shared: SharedUniforms) {
  const swirl = lines(
    "swirl",
    lineGeometry(
      arcs(70, { count: 9, minRadius: 0.08, maxRadius: 0.42, minSweep: 1.4, maxSweep: 4.2, segments: 48, strands: 2 }),
      71,
      0.6,
    ),
    glowMaterial(shared, { opacity: 0.9, flicker: 0.1, colorB: CORE_GOLD }, LINE_VERTEX, LINE_FRAGMENT),
  );
  const texture = radialTexture(128, 2.6);
  const core = glowSprite("core", texture, CORE_GOLD, 0.9);
  const halo = glowSprite("halo", texture, DEEP_AMBER, 0.16);
  return { swirl, core, halo };
}

function defaultRenderer(canvas: HTMLCanvasElement): RendererLike {
  return new WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
}

function defaultComposer(renderer: RendererLike, scene: Scene, camera: PerspectiveCamera): ComposerLike {
  const webgl = renderer as WebGLRenderer;
  const target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples: 4 });
  const composer = new EffectComposer(webgl, target);
  const renderPass = new RenderPass(scene, camera);
  const bloom = new UnrealBloomPass(new Vector2(256, 256), 1.25, 0.42, 0.18);
  const output = new OutputPass();
  composer.addPass(renderPass);
  composer.addPass(bloom);
  composer.addPass(output);
  return {
    render: () => composer.render(),
    setSize: (width, height) => composer.setSize(width, height),
    setPixelRatio: (ratio) => composer.setPixelRatio(ratio),
    dispose: () => {
      renderPass.dispose();
      bloom.dispose();
      output.dispose();
      composer.dispose();
    },
    bloom,
  };
}

function defaultControls(camera: PerspectiveCamera, element: HTMLElement): ControlsLike {
  return new OrbitControls(camera, element);
}

function disposeTree(root: Object3D): void {
  root.traverse((object) => {
    const drawable = object as Partial<LineSegments> & Partial<Sprite>;
    drawable.geometry?.dispose();
    const material = drawable.material as (Material & { map?: { dispose(): void } | null }) | undefined;
    material?.map?.dispose();
    material?.dispose();
  });
}

export function createOrbScene(canvas: HTMLCanvasElement, deps: OrbSceneDeps = {}): OrbScene {
  const renderer = (deps.createRenderer ?? defaultRenderer)(canvas);
  renderer.setClearColor(BACKGROUND, 1);

  const scene = new Scene();
  scene.background = new Color(BACKGROUND);
  const camera = new PerspectiveCamera(42, 1, 0.1, 50);
  camera.position.set(0, 0.35, CAMERA_DISTANCE);
  camera.lookAt(0, 0, 0);

  const shared: SharedUniforms = {
    uTime: { value: 0 },
    uDisplacement: { value: 0 },
    uAgitation: { value: 0 },
    uGlow: { value: 1 },
    uPixelRatio: { value: 1 },
  };
  const orb = buildOrb(shared);
  const { swirl, core, halo } = buildCore(shared);
  scene.add(orb, swirl, halo, core);
  const geodesicLayers = orb.getObjectByName("geodesic")!.children;
  const fragmentLayers = orb.getObjectByName("fragments")!.children;
  const arcLines = orb.getObjectByName("arcs")!;
  const streaks = orb.getObjectByName("streaks")!;

  const composer = (deps.createComposer ?? defaultComposer)(renderer, scene, camera);
  const controls = (deps.createControls ?? defaultControls)(camera, canvas);
  controls.enablePan = false;
  controls.enableZoom = false;
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.minDistance = 3.2;
  controls.maxDistance = 9;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0;

  // Idle drift: when not dragged, the camera wanders the orb along a random
  // diagonal (up-right, down-left, ...) instead of spinning on one fixed axis,
  // so it keeps "orbiting" the way it does under a real mouse drag.
  let driftEnabled = true;
  let dragging = false;
  controls.addEventListener("start", () => {
    dragging = true;
  });
  controls.addEventListener("end", () => {
    dragging = false;
  });
  const driftSpherical = new Spherical();
  const MIN_POLAR = 0.45;
  const MAX_POLAR = Math.PI - 0.45;
  const DRIFT_SPEED = 0.16;
  let azimuthVelocity = 0;
  let polarVelocity = 0;
  let azimuthTarget = 0;
  let polarTarget = 0;
  let driftTimer = 0;

  function pickDriftDirection(): void {
    const angle = Math.random() * Math.PI * 2;
    azimuthTarget = Math.cos(angle) * DRIFT_SPEED;
    polarTarget = Math.sin(angle) * DRIFT_SPEED * 0.6;
    driftTimer = 4 + Math.random() * 5;
  }
  pickDriftDirection();

  let pulsePhase = 0;

  return {
    update(params, dtMs) {
      const dt = dtMs / 1000;

      if (driftEnabled && !dragging) {
        driftTimer -= dt;
        if (driftTimer <= 0) {
          pickDriftDirection();
        }
        const ease = Math.min(1, dt * 0.5);
        azimuthVelocity += (azimuthTarget - azimuthVelocity) * ease;
        polarVelocity += (polarTarget - polarVelocity) * ease;
        driftSpherical.setFromVector3(camera.position);
        driftSpherical.theta += azimuthVelocity * dt;
        driftSpherical.phi = Math.min(MAX_POLAR, Math.max(MIN_POLAR, driftSpherical.phi + polarVelocity * dt));
        driftSpherical.makeSafe();
        camera.position.setFromSpherical(driftSpherical);
        camera.lookAt(0, 0, 0);
      }

      shared.uTime.value += dt;
      pulsePhase += dt * PULSE_RATE;
      shared.uDisplacement.value = params.displacement;
      shared.uAgitation.value = params.agitation;
      shared.uGlow.value = params.glow * (1 + params.pulse * Math.sin(pulsePhase));

      orb.rotation.y += params.spin * dt;
      orb.scale.setScalar(params.shellScale);
      geodesicLayers.forEach((layer, index) => {
        layer.rotation.x += params.spin * dt * (index % 2 === 0 ? 0.35 : -0.5);
      });
      fragmentLayers.forEach((layer, index) => {
        layer.rotation.y += params.spin * dt * (index % 2 === 0 ? -0.6 : 0.4);
      });
      arcLines.rotation.z += params.ringSpeed * dt * 0.6;
      arcLines.rotation.x += params.ringSpeed * dt * 0.2;
      streaks.rotation.y -= params.spin * dt * 0.3;
      swirl.rotation.z -= params.ringSpeed * dt * 2.4;
      swirl.rotation.y += params.ringSpeed * dt * 0.8;

      core.scale.setScalar(CORE_SIZE * params.coreScale);
      halo.scale.setScalar(CORE_SIZE * 3.4 * params.coreScale);
      composer.bloom.strength = params.bloom;

      controls.update(dt);
      composer.render();
    },
    resize(width, height, devicePixelRatio) {
      const ratio = Math.min(devicePixelRatio, MAX_PIXEL_RATIO);
      shared.uPixelRatio.value = ratio;
      renderer.setPixelRatio(ratio);
      renderer.setSize(width, height, false);
      composer.setPixelRatio(ratio);
      composer.setSize(width, height);
      camera.aspect = width / Math.max(1, height);
      camera.updateProjectionMatrix();
    },
    setAutoRotate(enabled) {
      controls.autoRotate = enabled;
      driftEnabled = enabled;
    },
    onInteraction(start, end) {
      controls.addEventListener("start", start);
      controls.addEventListener("end", end);
      return () => {
        controls.removeEventListener("start", start);
        controls.removeEventListener("end", end);
      };
    },
    dispose() {
      disposeTree(scene);
      composer.dispose();
      controls.dispose();
      renderer.dispose();
    },
  };
}
