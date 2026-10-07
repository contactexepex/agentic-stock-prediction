// Refusals and anything ambiguous go to the owner in Slack (a DM from the bot), never retried by an agent.
import type { OwnerNotifier, OwnerReport } from "./types.ts";
import type { FetchLike } from "./http.ts";
import { slackEscape } from "./text.ts";

export function ownerReportText(report: OwnerReport): string {
  const lines = [
    `:warning: market-brief: a command was ${report.result}`,
    `• tool: ${report.tool ?? "(none)"} · channel: ${report.channel} · from: ${report.actor}`,
    report.refusal_code ? `• code: ${report.refusal_code}` : null,
    report.message ? `• why: ${report.message.slice(0, 500)}` : null,
    `• command: ${report.command_id}`,
  ];
  return slackEscape(lines.filter((line) => line !== null).join("\n"));
}

export class SlackOwnerNotifier implements OwnerNotifier {
  readonly botToken: string | null;
  readonly ownerUserId: string | null;
  readonly fetcher: FetchLike;

  constructor(botToken: string | null, ownerUserId: string | null, fetcher: FetchLike) {
    this.botToken = botToken;
    this.ownerUserId = ownerUserId;
    this.fetcher = fetcher;
  }

  async notify(report: OwnerReport): Promise<boolean> {
    if (!this.botToken || !this.ownerUserId) return false;
    const response = await this.fetcher("https://slack.com/api/chat.postMessage", {
      method: "POST",
      headers: { Authorization: `Bearer ${this.botToken}`, "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ channel: this.ownerUserId, text: ownerReportText(report), unfurl_links: false, unfurl_media: false }),
    });
    if (!response.ok) return false;
    const body = (await response.json().catch(() => null)) as { ok?: boolean } | null;
    return body?.ok === true;
  }
}
