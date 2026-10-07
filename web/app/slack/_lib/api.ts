// The few Slack Web API calls the commands need, through the allowlisted fetch.
import type { FetchLike } from "../../../lib/tools/http.ts";

export interface SlackApi {
  viewsOpen(triggerId: string, view: unknown): Promise<boolean>;
  viewsUpdate(viewId: string, view: unknown): Promise<boolean>;
  respond(responseUrl: string, body: unknown): Promise<boolean>;
  /** Posts a message; returns its ts, or null when Slack did not take it. */
  postMessage(channel: string, text: string): Promise<string | null>;
  updateMessage(channel: string, ts: string, text: string): Promise<boolean>;
}

export function isSlackResponseUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "hooks.slack.com" && !parsed.username && !parsed.password;
  } catch {
    return false;
  }
}

export class SlackWebApi implements SlackApi {
  readonly botToken: string | null;
  readonly fetcher: FetchLike;

  constructor(botToken: string | null, fetcher: FetchLike) {
    this.botToken = botToken;
    this.fetcher = fetcher;
  }

  private async call(method: string, body: unknown): Promise<boolean> {
    return (await this.callFor(method, body)) !== null;
  }

  /** The parsed answer of a Web API call when Slack says ok, else null. */
  private async callFor(method: string, body: unknown): Promise<Record<string, unknown> | null> {
    if (!this.botToken) return null;
    const response = await this.fetcher(`https://slack.com/api/${method}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.botToken}`, "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify(body),
    });
    const parsed = (await response.json().catch(() => null)) as Record<string, unknown> | null;
    return response.ok && parsed?.ok === true ? parsed : null;
  }

  async postMessage(channel: string, text: string): Promise<string | null> {
    const answer = await this.callFor("chat.postMessage", { channel, text, unfurl_links: false, unfurl_media: false });
    return typeof answer?.ts === "string" ? answer.ts : null;
  }

  updateMessage(channel: string, ts: string, text: string): Promise<boolean> {
    return this.call("chat.update", { channel, ts, text });
  }

  viewsOpen(triggerId: string, view: unknown): Promise<boolean> {
    return this.call("views.open", { trigger_id: triggerId, view });
  }

  viewsUpdate(viewId: string, view: unknown): Promise<boolean> {
    return this.call("views.update", { view_id: viewId, view });
  }

  async respond(responseUrl: string, body: unknown): Promise<boolean> {
    if (!isSlackResponseUrl(responseUrl)) return false;
    const response = await this.fetcher(responseUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify(body),
    });
    return response.ok;
  }
}
