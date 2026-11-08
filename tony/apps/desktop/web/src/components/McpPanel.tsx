import { serverInfo } from "../mcpServers";
import type { ServerRow } from "../state/reducer";
import { CollapsiblePanel } from "./CollapsiblePanel";

export const DOWN_COLOUR = "#D93025";

interface Props {
  servers: ServerRow[];
}

export function McpPanel({ servers }: Props) {
  return (
    <CollapsiblePanel title="MCPs" className="mcp-panel">
      {servers.length === 0 ? <p className="panel-empty">Sin servidores conectados.</p> : null}
      <ul className="activity-servers">
        {servers.map((server) => (
          <li key={`${server.agent}/${server.server}`} data-down={server.down}>
            <span style={server.down ? { color: DOWN_COLOUR } : undefined}>{server.label}</span>
            <button
              type="button"
              className="info-icon"
              title={serverInfo(server.server).description}
              aria-label={`Información de ${serverInfo(server.server).label}`}
            >
              <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.3" />
                <circle cx="8" cy="4.6" r="1" fill="currentColor" />
                <path d="M8 7v5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
            </button>
          </li>
        ))}
      </ul>
    </CollapsiblePanel>
  );
}
