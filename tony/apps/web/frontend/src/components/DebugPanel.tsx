import { useEffect, useMemo, useState } from "react";

import type { ChatState, TaskNode } from "../protocol/reducer";
import {
  currentRootTask,
  exportJson,
  formatTokens,
  formatUsd,
  taskTree,
  toolRows,
  usageSummary,
  type ToolViewRow,
} from "../protocol/selectors";
import { CopyIcon, PanelIcon, WarningIcon } from "./icons";

export const PANEL_KEY = "tony.debug_open";
export const TOKEN_ALERT_TEXT = "Tarea > 50 k tokens";
export const EMPTY_TASKS = "Sin tareas delegadas todavía.";

interface Props {
  state: ChatState;
  storage?: Storage;
}

function readOpen(storage: Storage | undefined): boolean {
  try {
    return storage?.getItem(PANEL_KEY) !== "false";
  } catch {
    return true;
  }
}

async function copyText(text: string): Promise<boolean> {
  const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
  if (!clipboard?.writeText) {
    return false;
  }
  try {
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function DebugPanel({ state, storage }: Props) {
  const [open, setOpen] = useState(() => readOpen(storage));
  const root = useMemo(() => currentRootTask(state), [state]);

  useEffect(() => {
    try {
      storage?.setItem(PANEL_KEY, String(open));
    } catch {
      return;
    }
  }, [open, storage]);

  return (
    <aside className="debug" data-open={open} aria-label="Panel de debug">
      <div className="debug-header">
        {open ? <h2>Debug</h2> : null}
        <button
          type="button"
          className="icon"
          aria-label={open ? "Plegar panel de debug" : "Desplegar panel de debug"}
          aria-expanded={open}
          aria-controls="debug-body"
          onClick={() => setOpen((value) => !value)}
        >
          <PanelIcon />
        </button>
      </div>
      {open ? (
        <div id="debug-body" className="debug-body">
          {state.alert ? (
            <p role="alert" className="alert">
              <WarningIcon /> {TOKEN_ALERT_TEXT}
            </p>
          ) : null}
          {root ? <TaskSection state={state} root={root} /> : <p className="muted">{EMPTY_TASKS}</p>}
          <UsageMeter state={state} />
          <ReloadList state={state} />
        </div>
      ) : null}
    </aside>
  );
}

function TaskSection({ state, root }: { state: ChatState; root: TaskNode }) {
  const rows = useMemo(() => taskTree(state, root), [state, root]);
  const tools = useMemo(() => toolRows(state, root), [state, root]);
  return (
    <>
      <section>
        <h3>Tareas</h3>
        <TaskTree rows={rows} />
        {root.logPath ? <LogPath path={root.logPath} /> : null}
        <CopyJsonButton json={exportJson(state, root)} />
      </section>
      <section>
        <h3>Tool calls</h3>
        <ToolList rows={tools} />
      </section>
    </>
  );
}

function TaskTree({ rows }: { rows: [TaskNode, number][] }) {
  return (
    <ul className="task-tree" role="tree" aria-label="Árbol de tareas">
      {rows.map(([node, depth]) => (
        <li key={node.taskId} role="treeitem" aria-level={depth + 1} style={{ paddingLeft: `${depth}rem` }}>
          <span className="task-node">
            <code>{node.agent ? `${node.taskId} · ${node.agent}` : node.taskId}</code>
            <span className="status" data-status={node.status}>
              {node.status}
            </span>
            {node.usage ? (
              <span className="muted">
                {`${formatTokens(node.usage.inputTokens)} / ${formatTokens(node.usage.outputTokens)}`}
              </span>
            ) : null}
            {node.usage ? <span className="muted">{formatUsd(node.usage.costUsd)}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function ToolList({ rows }: { rows: ToolViewRow[] }) {
  if (rows.length === 0) {
    return <p className="muted">Sin llamadas todavía.</p>;
  }
  return (
    <ul className="tool-list">
      {rows.map((row, index) => (
        <li key={`${row.taskId}-${index}`}>
          <code>{row.tool}</code>
          {row.done ? (
            row.error ? (
              <span className="warn">{row.error}</span>
            ) : (
              <span className="muted">{row.durationMs} ms</span>
            )
          ) : (
            <span className="muted">en curso</span>
          )}
          <pre>{JSON.stringify(row.args, null, 2)}</pre>
        </li>
      ))}
    </ul>
  );
}

function UsageMeter({ state }: { state: ChatState }) {
  const summary = useMemo(() => usageSummary(state), [state]);
  return (
    <section>
      <h3>Tokens de la conversación</h3>
      <p>
        {`${formatTokens(summary.tokens)} tokens (${formatTokens(summary.inputTokens)} entrada, ` +
          `${formatTokens(summary.outputTokens)} salida), ${formatUsd(summary.costUsd)}`}
      </p>
    </section>
  );
}

function ReloadList({ state }: { state: ChatState }) {
  if (state.reloads.length === 0) {
    return null;
  }
  return (
    <section>
      <h3>Recargas de configuración</h3>
      <ul className="reload-list">
        {state.reloads.map((entry, index) => (
          <li key={index} className={entry.ok ? undefined : "warn"}>
            <code>{entry.agent}</code>: {entry.ok ? entry.detail : `error: ${entry.detail}`}
          </li>
        ))}
      </ul>
    </section>
  );
}

function LogPath({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <p className="log-path">
      <code>{path}</code>
      <button
        type="button"
        className="icon"
        aria-label="Copiar ruta"
        onClick={() => void copyText(path).then(setCopied)}
      >
        <CopyIcon />
      </button>
      {copied ? <span className="muted">Copiado</span> : null}
    </p>
  );
}

function CopyJsonButton({ json }: { json: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "fallback">("idle");
  const copy = async () => {
    setStatus((await copyText(json)) ? "copied" : "fallback");
  };
  return (
    <div>
      <button type="button" className="secondary" onClick={() => void copy()}>
        <CopyIcon /> Copiar JSON
      </button>
      {status === "copied" ? <span className="muted"> Copiado</span> : null}
      {status === "fallback" ? (
        <textarea className="json-export" aria-label="JSON de la tarea" readOnly value={json} />
      ) : null}
    </div>
  );
}
