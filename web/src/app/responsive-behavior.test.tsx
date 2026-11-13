import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Hit } from "../lib/types";
import { EvidencePanel } from "../features/ask/EvidencePanel";
import { App } from "./App";

const evidence: Hit = {
  chunk: {
    id: "1706.03762v7:p2:w150",
    paper_id: "1706.03762v7",
    title: "Attention Is All You Need",
    page: 2,
    start: 100,
    end: 240,
    text: "The Transformer relies entirely on self-attention.",
  },
  score: 1,
  scores: { bm25: 1 },
};

describe("responsive product behavior", () => {
  it("keeps the question draft while primary views change", async () => {
    const user = userEvent.setup();
    render(<App />);
    const question = screen.getByLabelText("Question");
    await user.type(question, "Keep this research question");
    await user.click(screen.getByRole("button", { name: "Library" }));
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(screen.getByLabelText("Question")).toHaveValue("Keep this research question");
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
  });

  it("focuses the citation surface and lets Escape close it", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<EvidencePanel evidence={evidence} onClose={onClose} />);
    expect(screen.getByRole("button", { name: "Close source passage" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });
});
