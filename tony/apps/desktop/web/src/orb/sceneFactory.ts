import type { ThemeId } from "../theme/themes";
import { drawAuroraOrb } from "./auroraOrb";
import { type OrbDrawing, createCanvasScene } from "./canvasScene";
import { drawDialOrb } from "./dialOrb";
import type { OrbScene } from "./scene";

export type SceneFactory = (canvas: HTMLCanvasElement) => OrbScene;

const CANVAS_DRAWINGS: Record<Exclude<ThemeId, "holo">, OrbDrawing> = {
  aurora: drawAuroraOrb,
  instrumento: drawDialOrb,
};

/** Holo keeps the WebGL orb, loaded on demand so three.js stays out of the other themes. */
export async function loadSceneFactory(theme: ThemeId): Promise<SceneFactory> {
  if (theme === "holo") {
    return (await import("./scene")).createOrbScene;
  }
  const drawing = CANVAS_DRAWINGS[theme];
  return (canvas) => createCanvasScene(canvas, drawing);
}
