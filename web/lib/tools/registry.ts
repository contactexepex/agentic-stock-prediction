// Typed access to the generated tool and agent definitions (mcp/tools.yaml, mcp/agents/*.yaml).
import type { AgentDefinition, Channel, ToolDefinition } from "./types.ts";
import { AGENT_DEFINITIONS, CHANNELS, REFUSAL_CODES, TOOL_DEFINITIONS } from "./registry.generated.ts";

export const TOOLS = TOOL_DEFINITIONS as readonly ToolDefinition[];
export const AGENTS = AGENT_DEFINITIONS as readonly AgentDefinition[];
export const ALL_CHANNELS = CHANNELS as readonly Channel[];
export const ALL_REFUSAL_CODES = REFUSAL_CODES as readonly string[];

const toolsByName = new Map(TOOLS.map((tool) => [tool.name, tool]));
const agentsByName = new Map(AGENTS.map((agent) => [agent.agent, agent]));

export function getTool(name: string): ToolDefinition | null {
  return toolsByName.get(name) ?? null;
}

export function getAgent(name: string): AgentDefinition | null {
  return agentsByName.get(name) ?? null;
}

/** A tools.yaml channel value: false = not allowed; true or a note (e.g. "/trade") = allowed. */
export function allowedInChannel(tool: ToolDefinition, channel: Channel): boolean {
  const value = tool.channels[channel];
  return value !== false && value !== undefined;
}

/** The tools an agent may call in a channel: in its list and allowed there by tools.yaml. */
export function agentTools(agent: AgentDefinition, channel: Channel): ToolDefinition[] {
  if (!agent.channels.includes(channel)) return [];
  return TOOLS.filter((tool) => agent.tools.includes(tool.name) && allowedInChannel(tool, channel));
}

/** The data kind a write tool's import appends to (besides command_log). */
export function writeKind(tool: ToolDefinition): string | null {
  return (tool.writes ?? []).find((kind) => kind !== "command_log") ?? null;
}
