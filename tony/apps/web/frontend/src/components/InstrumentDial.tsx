const LABELS = ["SYS", "ENG", "VOZ", "LINK", "MEM", "I/O", "NET", "AUX"];

function polar(cx: number, cy: number, r: number, angleDeg: number): [number, number] {
  const a = ((angleDeg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

/** Purely decorative instrument-dial ring around the orb: ticks, labels, no live telemetry. */
export function InstrumentDial() {
  const cx = 250;
  const cy = 250;
  const ticks = Array.from({ length: 72 }, (_, i) => i * 5);

  return (
    <svg className="dial" viewBox="0 0 500 500" aria-hidden="true">
      <circle cx={cx} cy={cy} r={238} className="dial-ring dial-ring-outer" />
      <circle cx={cx} cy={cy} r={196} className="dial-ring dial-ring-dashed" />
      <circle cx={cx} cy={cy} r={160} className="dial-ring dial-ring-thin" />

      {ticks.map((deg) => {
        const major = deg % 30 === 0;
        const [x1, y1] = polar(cx, cy, 238, deg);
        const [x2, y2] = polar(cx, cy, major ? 222 : 230, deg);
        return <line key={deg} x1={x1} y1={y1} x2={x2} y2={y2} className={major ? "dial-tick major" : "dial-tick"} />;
      })}

      {LABELS.map((label, i) => {
        const deg = (360 / LABELS.length) * i;
        const [x, y] = polar(cx, cy, 206, deg);
        return (
          <text key={label} x={x} y={y} className="dial-label" textAnchor="middle" dominantBaseline="middle">
            {label}
          </text>
        );
      })}

      <circle cx={cx} cy={cy} r={236} className="dial-ring dial-spin-slow" />
      <circle cx={cx} cy={cy} r={176} className="dial-ring dial-spin-rev" />
    </svg>
  );
}
