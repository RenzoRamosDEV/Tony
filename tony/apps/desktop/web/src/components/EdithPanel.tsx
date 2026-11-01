import type { AuditRow } from "../bridge/types";
import type { AuditFilter } from "../state/reducer";
import { CollapsiblePanel } from "./CollapsiblePanel";

const FILTERS: [AuditFilter, string][] = [
  ["all", "Todos"],
  ["allow", "allow"],
  ["confirm", "confirm"],
  ["deny", "deny"],
];

interface Props {
  rows: AuditRow[];
  filter: AuditFilter;
  onFilter: (filter: AuditFilter) => void;
}

export function EdithPanel({ rows, filter, onFilter }: Props) {
  return (
    <CollapsiblePanel title="Edith" className="edith-panel">
      <label className="edith-filter">
        Veredicto{" "}
        <select aria-label="Veredicto" value={filter} onChange={(event) => onFilter(event.target.value as AuditFilter)}>
          {FILTERS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <table className="audit-table">
        <thead>
          <tr>
            <th scope="col">Hora</th>
            <th scope="col">Agente</th>
            <th scope="col">Herramienta</th>
            <th scope="col">Veredicto</th>
            <th scope="col">Regla</th>
            <th scope="col">Decisión</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} data-verdict={row.verdict}>
              <td>{row.time}</td>
              <td>{row.agent}</td>
              <td>{row.tool}</td>
              <td>{row.verdict}</td>
              <td>{row.rule}</td>
              <td>{row.user_decision ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </CollapsiblePanel>
  );
}
