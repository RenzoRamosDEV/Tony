import type { ServerRow, TaskNode, ToolNode } from "../state/reducer";
import { CollapsiblePanel } from "./CollapsiblePanel";

export const DOWN_COLOUR = "#D93025";

function Calls({ calls }: { calls: ToolNode[] }) {
  return (
    <ul>
      {calls.map((call, index) => (
        <li key={index}>{call.label}</li>
      ))}
    </ul>
  );
}

interface Props {
  tasks: TaskNode[];
  servers: ServerRow[];
}

export function ActivityPanel({ tasks, servers }: Props) {
  return (
    <CollapsiblePanel title="Actividad" className="activity-panel">
      {tasks.length === 0 && servers.length === 0 ? <p className="panel-empty">Sin tareas delegadas.</p> : null}
      <ul className="activity-tasks">
        {tasks.map((task) => (
          <li key={task.task_id}>
            <span className="task-label">{task.label}</span>
            <Calls calls={task.calls} />
            <ul>
              {task.subagents.map((subagent) => (
                <li key={subagent.name}>
                  <span className="subagent-label">{subagent.name}</span>
                  <Calls calls={subagent.calls} />
                </li>
              ))}
            </ul>
            <span className="task-summary">{task.summary}</span>
          </li>
        ))}
      </ul>
      <ul className="activity-servers">
        {servers.map((server) => (
          <li
            key={`${server.agent}/${server.server}`}
            data-down={server.down}
            style={server.down ? { color: DOWN_COLOUR } : undefined}
          >
            {server.label}
          </li>
        ))}
      </ul>
    </CollapsiblePanel>
  );
}
