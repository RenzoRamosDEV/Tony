import { type ReactNode, useId, useState } from "react";

interface Props {
  title: string;
  className: string;
  children: ReactNode;
}

/** A HUD side panel whose body is hidden, not unmounted, when collapsed. */
export function CollapsiblePanel({ title, className, children }: Props) {
  const [open, setOpen] = useState(true);
  const bodyId = useId();
  return (
    <section className={`side-panel holo-frame ${className}`} aria-label={title}>
      <button
        type="button"
        className="side-panel-toggle holo-frame holo"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((value) => !value)}
      >
        {title} {open ? "▾" : "▸"}
      </button>
      <div id={bodyId} className="side-panel-body" hidden={!open}>
        {children}
      </div>
    </section>
  );
}
