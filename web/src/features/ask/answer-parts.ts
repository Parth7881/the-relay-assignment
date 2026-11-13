import type { Hit } from "../../lib/types";

export type AnswerPart =
  | { type: "text"; text: string }
  | { type: "citation"; evidence: Hit };

const MARKER = /\[([^\]\r\n]{1,200})\]/g;

export function splitAnswer(answer: string, evidence: Hit[]): AnswerPart[] {
  const byId = new Map(evidence.map((hit) => [hit.chunk.id, hit]));
  const parts: AnswerPart[] = [];
  let cursor = 0;
  for (const match of answer.matchAll(MARKER)) {
    const hit = byId.get(match[1]);
    if (!hit || match.index === undefined) continue;
    const text = answer.slice(cursor, match.index);
    if (text) parts.push({ type: "text", text });
    parts.push({ type: "citation", evidence: hit });
    cursor = match.index + match[0].length;
  }
  const remainder = answer.slice(cursor);
  if (remainder) parts.push({ type: "text", text: remainder });
  return parts;
}
