import type { ResizeEdge, WindowBridge } from "../bridge/types";

interface Props {
  window: WindowBridge | null;
}

const EDGES: ResizeEdge[] = ["top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right"];

/** Invisible strips along the frameless window's border: the OS no longer offers edge-drag resize. */
export function ResizeHandles({ window: controls }: Props) {
  if (controls === null) {
    return null;
  }

  return (
    <div className="resize-handles">
      {EDGES.map((edge) => (
        <div
          key={edge}
          className={`resize-handle resize-${edge}`}
          onMouseDown={(event) => {
            if (event.button === 0) {
              controls.startResize(edge);
            }
          }}
        />
      ))}
    </div>
  );
}
