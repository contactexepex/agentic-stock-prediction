// Argument validation from the tool's inputs in mcp/tools.yaml, plus the cheap tool-specific checks the web tier can
// make. The importer runs the full Python validators (F8, WS4) again before anything reaches data/.
import type { InputSpec, ToolArgs, ToolDefinition } from "./types.ts";

export const MAX_STRING_LENGTH = 500;          // any string input without its own max_length
const STRATEGY_ID = /^[a-z0-9_.-]{1,80}$/;     // ids of config/strategies.yaml, e.g. rule.model_news_1x.v1
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$/;

export type Validation = { ok: true; args: ToolArgs } | { ok: false; message: string };

function typeMatches(value: unknown, type: string): boolean {
  switch (type) {
    case "string":
      return typeof value === "string";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    default:
      return false;
  }
}

function realDate(text: string): boolean {
  const parsed = new Date(`${text.slice(0, 10)}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === text.slice(0, 10);
}

function checkValue(name: string, value: unknown, spec: InputSpec): string | null {
  const types = Array.isArray(spec.type) ? spec.type : [spec.type];
  if (!types.some((type) => typeMatches(value, type))) return `${name} must be ${types.join(" or ")}`;
  if (value === null) return null;
  if (spec.enum && !spec.enum.includes(value as string | number)) return `${name} must be one of ${spec.enum.join(", ")}`;
  if (typeof value === "string") {
    const max = spec.max_length ?? MAX_STRING_LENGTH;
    if (value.length > max) return `${name} is longer than ${max} characters`;
    if (spec.pattern && !new RegExp(spec.pattern).test(value)) return `${name} has an invalid format`;
    if (spec.format === "date" && !(DATE.test(value) && realDate(value))) return `${name} must be a date YYYY-MM-DD`;
    if (spec.format === "date-time" && !(DATE_TIME.test(value) && realDate(value))) {
      return `${name} must be an ISO 8601 time with a zone`;
    }
  }
  if (typeof value === "number") {
    if (spec.minimum !== undefined && value < spec.minimum) return `${name} must be at least ${spec.minimum}`;
    if (spec.exclusive_minimum !== undefined && value <= spec.exclusive_minimum) {
      return `${name} must be above ${spec.exclusive_minimum}`;
    }
  }
  return null;
}

/** Checks the arguments against the tool's inputs; unknown arguments are refused (identity is never an argument). */
export function validateArguments(tool: ToolDefinition, raw: unknown, today: string): Validation {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { ok: false, message: "arguments must be an object" };
  const input = raw as ToolArgs;
  const unknown = Object.keys(input).filter((key) => !Object.hasOwn(tool.inputs, key));
  if (unknown.length) return { ok: false, message: `unknown argument(s): ${unknown.slice(0, 5).join(", ").slice(0, 120)}` };
  const args: ToolArgs = {};
  for (const [name, spec] of Object.entries(tool.inputs)) {
    const value = input[name];
    if (value === undefined) {
      if (spec.required) return { ok: false, message: `${name} is required` };
      if (spec.default !== undefined) args[name] = spec.default;
      continue;
    }
    const problem = checkValue(name, value, spec);
    if (problem) return { ok: false, message: problem };
    args[name] = value;
  }
  const extra = toolSpecificProblem(tool.name, args, today);
  return extra ? { ok: false, message: extra } : { ok: true, args };
}

function toolSpecificProblem(name: string, args: ToolArgs, today: string): string | null {
  if (typeof args.strategy_id === "string" && !STRATEGY_ID.test(args.strategy_id)) return "strategy_id has an invalid format";
  if (name === "delete_company" && args.confirm !== args.ticker) {
    return "confirm must equal the ticker, typed exactly (decision 20)";
  }
  if (name === "add_paper_trade") {
    if (args.price_basis === "manual" && typeof args.price !== "number") return "price is required with price_basis manual";
    if (args.price_basis !== "manual" && args.price !== undefined) return "price is only allowed with price_basis manual";
    if (typeof args.price === "number" && !(args.price > 0)) return "price must be above 0";
    if (args.market === "india" && typeof args.quantity === "number" && !Number.isInteger(args.quantity)) {
      return "India trades are whole shares (decision 4)";
    }
    if (typeof args.trade_date === "string" && args.trade_date > today) return "trade_date is in the future";
  }
  return null;
}
