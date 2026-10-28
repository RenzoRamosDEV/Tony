import type { ChatState, TaskNode, ToolRow, UsageTotal } from "./reducer";

export interface ToolViewRow extends ToolRow {
  taskId: string;
}

export interface ExportedTask {
  task_id: string;
  parent_id: string | null;
  agent: string | null;
  status: string;
  log_path: string | null;
  usage: TaskNode["usage"] | null;
  tools: ToolRow[];
  children: ExportedTask[];
}

export function currentRootTask(state: ChatState): TaskNode | null {
  const id = state.activeRootId ?? state.lastRootId;
  return id === null ? null : (state.tasks[id] ?? null);
}

/** Depth-first list of a task and its descendants: [node, depth]. */
export function taskTree(state: ChatState, root: TaskNode): [TaskNode, number][] {
  const rows: [TaskNode, number][] = [];
  const visit = (node: TaskNode, depth: number) => {
    rows.push([node, depth]);
    for (const childId of node.children) {
      const child = state.tasks[childId];
      if (child) {
        visit(child, depth + 1);
      }
    }
  };
  visit(root, 0);
  return rows;
}

export function toolRows(state: ChatState, root: TaskNode): ToolViewRow[] {
  return taskTree(state, root).flatMap(([node]) =>
    node.tools.map((tool) => ({ ...tool, taskId: node.taskId })),
  );
}

export function usageSummary(state: ChatState): UsageTotal & { tokens: number } {
  const total = state.usageTotal;
  return { ...total, tokens: total.inputTokens + total.outputTokens };
}

export function exportJson(state: ChatState, root: TaskNode): string {
  const build = (node: TaskNode): ExportedTask => ({
    task_id: node.taskId,
    parent_id: node.parentId,
    agent: node.agent,
    status: node.status,
    log_path: node.logPath,
    usage: node.usage ?? null,
    tools: node.tools,
    children: node.children
      .map((id) => state.tasks[id])
      .filter((child): child is TaskNode => child !== undefined)
      .map(build),
  });
  return JSON.stringify(build(root), null, 2);
}

export function formatTokens(value: number): string {
  return Math.round(value)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

export function formatUsd(value: number): string {
  const digits = value < 0.01 && value > 0 ? 4 : 2;
  return `${value.toFixed(digits).replace(".", ",")} USD`;
}
