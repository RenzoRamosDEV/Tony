import type { MouseEvent } from "react";

import type { WindowBridge } from "../bridge/types";

interface Props {
  window: WindowBridge | null;
}

/** The app draws its own titlebar: the OS window is frameless (see window_controls.py). */
export function TitleBar({ window: controls }: Props) {
  if (controls === null) {
    return null;
  }

  const onBarMouseDown = (event: MouseEvent) => {
    if (event.button === 0 && event.target === event.currentTarget) {
      controls.startMove();
    }
  };

  const onBarDoubleClick = (event: MouseEvent) => {
    if (event.target === event.currentTarget) {
      controls.toggleMaximize();
    }
  };

  return (
    <div className="title-bar" onMouseDown={onBarMouseDown} onDoubleClick={onBarDoubleClick}>
      <span className="title-bar-label">Tony</span>
      <div className="title-bar-buttons">
        <button type="button" className="title-bar-button" aria-label="Minimizar" onClick={() => controls.minimize()}>
          <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
            <path d="M2 6h8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
        </button>
        <button
          type="button"
          className="title-bar-button"
          aria-label="Maximizar"
          onClick={() => controls.toggleMaximize()}
        >
          <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
            <rect x="2.5" y="2.5" width="7" height="7" fill="none" stroke="currentColor" strokeWidth="1.3" />
          </svg>
        </button>
        <button
          type="button"
          className="title-bar-button title-bar-close"
          aria-label="Cerrar"
          onClick={() => controls.close()}
        >
          <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
            <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
