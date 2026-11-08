import type { TaskNode, ToolNode } from "../state/reducer";
import { CollapsiblePanel } from "./CollapsiblePanel";

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
}

export function ActivityPanel({ tasks }: Props) {
  return (
    <CollapsiblePanel title="Actividad" className="activity-panel">
      {tasks.length === 0 ? <p className="panel-empty">Sin tareas delegadas.</p> : null}
      <ul className="activity-tasks">
        {[...tasks].reverse().map((task) => (
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
          </li>
        ))}
      </ul>
    </CollapsiblePanel>
  );
}
