export interface McpServerInfo {
  label: string;
  description: string;
}

const KNOWN_SERVERS: Record<string, McpServerInfo> = {
  filesystem: {
    label: "File System",
    description: "Lee y escribe archivos en las carpetas de notas permitidas.",
  },
};

function humanize(id: string): string {
  const spaced = id.replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");
  return spaced
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function serverInfo(id: string): McpServerInfo {
  return KNOWN_SERVERS[id] ?? { label: humanize(id), description: "Servidor MCP conectado a este agente." };
}

export function titleCase(name: string): string {
  return name
    .split("/")
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join("/");
}
