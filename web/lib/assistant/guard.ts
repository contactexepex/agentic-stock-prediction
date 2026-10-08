// Deterministic checks on the model's answer: citations must be ids that the read tools returned, and an answer that
// reads as advice is replaced by the fixed decline. The model is told the same rules; these checks do not trust it.
import { CITED_KINDS, type CitedKind } from "./constants.ts";
import type { AnswerSource, CitedRecord } from "./types.ts";

export const ADVICE_DECLINE =
  "I can't advise real trades: this is a research tool and every signal here is a paper record. I can show what the " +
  "stored data says: paper predictions, paper trades and how the strategies have done.";

/** A question that asks for advice or a real trade (checked before the model is called, so it costs nothing). */
const ADVICE_QUESTION = [
  /\b(should|shall|would you|do you recommend|is it (a )?good (time|idea)( to)?)\b[^?.!]{0,60}\b(buy|sell|short|invest|hold|trade|exit|enter)\b/i,
  /\b(real|my own) money\b/i,
  /\b(which|what) (stock|share|company)s? (should|to) (i|we) (buy|sell|invest)/i,
  /\bprice target\b.*\b(should|would you)\b/i,
];

/** Answer text that gives advice: a recommendation to act, addressed to the reader. */
const ADVICE_ANSWER = [
  /\b(you|i|we) (should|could|might want to|may want to|ought to)\s+(consider\s+)?(buy|sell|short|hold|invest|exit|enter|add|trim|accumulate)\b/i,
  /\bi (would )?(recommend|suggest|advise)\b/i,
  /\b(strong )?(buy|sell) (it|this|now|today|tomorrow|before|after)\b/i,
  /\b(good|great|right) time to (buy|sell|invest)\b/i,
];

export function asksForAdvice(question: string): boolean {
  return ADVICE_QUESTION.some((pattern) => pattern.test(question));
}

export function readsAsAdvice(text: string): boolean {
  return ADVICE_ANSWER.some((pattern) => pattern.test(text));
}

/** What one tool call returned: the text the model saw (cut to the limit) and each read-model source in full. */
export interface ReadText {
  text: string;
  sources: { source: AnswerSource; text: string }[];
}

/** A JSON string value (not a key): the quoted id followed by `,`, `}` or `]`. */
function valuePattern(id: string): RegExp {
  return new RegExp(`${JSON.stringify(id).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=\\s*[,}\\]])`);
}

/** Keeps each cited id that occurs as a whole JSON string value in what the model saw of the read tools' results;
 * drops the others. The id's as_of is the as-of time of the read model it was found in. */
export function verifyCitations(cited: { id: string; kind: string }[], reads: ReadText[]): { kept: CitedRecord[]; dropped: string[] } {
  const kept: CitedRecord[] = [];
  const dropped: string[] = [];
  const seen = new Set<string>();
  for (const item of cited) {
    const id = item.id.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const value = valuePattern(id);
    const read = id.length >= 3 ? reads.find((candidate) => value.test(candidate.text)) : undefined;
    const found = read ? read.sources.find((part) => value.test(part.text)) ?? read.sources[0] : undefined;
    if (!found) {
      dropped.push(id.slice(0, 120));
      continue;
    }
    const kind = (CITED_KINDS as readonly string[]).includes(item.kind) ? (item.kind as CitedKind) : "record";
    kept.push({ id, kind, as_of: found.source.as_of, source: `${found.source.read_model} ${found.source.page_key}` });
  }
  return { kept, dropped };
}

/** The reader's question as quoted data: the closing tag cannot be forged, control characters are dropped. */
export function quotedQuestion(question: string): string {
  return question.replace(/<\/?question>/gi, "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "").trim();
}
