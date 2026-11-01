/** Static CSS orb for browsers without WebGL; its glow follows `data-orb-state` on the stage. */
export function OrbFallback() {
  return (
    <div className="orb-fallback">
      <span className="orb-fallback-shell" />
      <span className="orb-fallback-ring" />
      <span className="orb-fallback-ring tilted" />
      <span className="orb-fallback-core" />
    </div>
  );
}
