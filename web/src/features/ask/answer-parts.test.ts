import { describe, expect, it } from "vitest";

import type { Hit } from "../../lib/types";
import { splitAnswer } from "./answer-parts";

const evidence: Hit = {
  chunk: {
    id: "1706.03762v7:p2:w150",
    paper_id: "1706.03762v7",
    title: "Attention Is All You Need",
    page: 2,
    start: 100,
    end: 200,
    text: "The Transformer relies entirely on self-attention.",
  },
  score: 1,
  scores: { bm25: 1 },
};

describe("splitAnswer", () => {
  it("preserves order and turns only an exact returned chunk ID into a citation", () => {
    expect(
      splitAnswer(
        "First claim. [1706.03762v7:p2:w150] Unknown [outside:p1] end.",
        [evidence],
      ),
    ).toEqual([
      { type: "text", text: "First claim. " },
      { type: "citation", evidence },
      { type: "text", text: " Unknown [outside:p1] end." },
    ]);
  });

  it("keeps malformed markers inert and reuses one evidence object for duplicates", () => {
    const parts = splitAnswer(
      "A [1706.03762v7:p2:w150] B [1706.03762v7:p2:w150] C [unfinished",
      [evidence],
    );
    expect(parts.map((part) => part.type)).toEqual([
      "text",
      "citation",
      "text",
      "citation",
      "text",
    ]);
    expect(parts[1]?.type === "citation" && parts[1].evidence).toBe(evidence);
    expect(parts[3]?.type === "citation" && parts[3].evidence).toBe(evidence);
    expect(parts[4]).toEqual({ type: "text", text: " C [unfinished" });
  });
});
