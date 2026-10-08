// The Slack /ask answer (B5 posts it to the command's response_url): plain mrkdwn, every piece of stored or model
// text escaped with B5's slackEscape, so nothing in it can ping or hide a link. Ephemeral: only the asker sees it.
import type { ToolOutcome } from "../tools/types.ts";
import { slackEscape } from "../tools/text.ts";
import { spendLine } from "./cost.ts";
import { kindWords, stateWords } from "./words.ts";
import type { AnswerRecord, SpendState } from "./types.ts";

export interface SlackAnswer {
  response_type: "ephemeral";
  replace_original: boolean;
  text: string;
}

export const SLACK_FOOTER = "Paper only, research, never advice.";

export function formatSlackAnswer(outcome: ToolOutcome): SlackAnswer {
  const data = (outcome.data ?? {}) as { answer?: AnswerRecord; spend?: SpendState | null };
  const answer = data.answer;
  const lines: string[] = [];
  if (answer && outcome.result === "accepted") {
    lines.push(`*${slackEscape(stateWords(answer))}*`, slackEscape(answer.text));
    if (answer.cited.length) {
      lines.push("Records used:");
      for (const item of answer.cited) {
        lines.push(`• ${slackEscape(kindWords(item.kind))} \`${slackEscape(item.id)}\`${item.as_of ? ` (data as of ${slackEscape(item.as_of)})` : ""}`);
      }
    }
    lines.push(`Read up to ${slackEscape(answer.as_of)}.`);
  } else {
    lines.push(`Not answered: ${slackEscape(outcome.message ?? outcome.result)}`);
  }
  if (data.spend) lines.push(`_${slackEscape(spendLine(data.spend))}_`);
  lines.push(`_${SLACK_FOOTER}_`);
  return { response_type: "ephemeral", replace_original: true, text: lines.join("\n").slice(0, 3900) };
}

/** The usage line for /ask without a market or a question. */
export const ASK_USAGE = "Usage: `/ask india|us <question>` (at most 500 characters). The answer reads only the stored " +
  "data, cites its records and never advises.";

/** The immediate reply while the answer is looked up. */
export const ASK_WORKING = "Looking that up in the stored data…";
