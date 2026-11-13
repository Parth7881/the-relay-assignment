import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Answer, Hit } from "../../lib/types";
import { ApiError } from "../../lib/api";
import { AskPage, type AskPageProps } from "./AskPage";

const hit: Hit = {
  chunk: {
    id: "1706.03762v7:p2:w150",
    paper_id: "1706.03762v7",
    title: "Attention Is All You Need",
    page: 2,
    start: 100,
    end: 240,
    text: "The Transformer relies entirely on self-attention instead of recurrence.",
  },
  score: 1,
  scores: { bm25: 1 },
};

const verified: Answer = {
  request_id: "request-1",
  question: "What replaces recurrence?",
  start_time: "2026-11-12T10:00:00+00:00",
  source: "real",
  status: "ok",
  disposition: "answered",
  answer: "The Transformer relies entirely on self-attention. [1706.03762v7:p2:w150]",
  evidence: [hit],
  first_token_ms: null,
  total_ms: 1200,
  tokens_in: 100,
  tokens_out: 20,
  retries: 0,
  retrieval_setting: "hybrid-minilm220-rrf-rerank-k4-v1",
  reason: "support_checks_passed",
};

function Harness(props: Omit<AskPageProps, "draft" | "onDraftChange">) {
  const [draft, setDraft] = useState("");
  return <AskPage {...props} draft={draft} onDraftChange={setDraft} />;
}

describe("AskPage", () => {
  it("names the enterprise research workspace and evidence inspector controls", () => {
    render(<Harness ask={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Ask the research library" })).toBeInTheDocument();
    expect(screen.getByText("Answers are released only when the cited passages support them."))
      .toBeInTheDocument();
  });

  it("does not submit an empty question", async () => {
    const ask = vi.fn();
    render(<Harness ask={ask} />);
    expect(screen.getByRole("button", { name: "Ask The Relay" })).toBeDisabled();
    expect(ask).not.toHaveBeenCalled();
  });

  it("shows honest loading, a verified answer, and the selected source passage", async () => {
    const user = userEvent.setup();
    let resolve!: (value: Answer) => void;
    const ask = vi.fn(() => new Promise<Answer>((done) => (resolve = done)));
    const onRun = vi.fn();
    render(<Harness ask={ask} onRun={onRun} />);

    await user.type(screen.getByLabelText("Question"), "What replaces recurrence?");
    await user.click(screen.getByRole("button", { name: "Ask The Relay" }));
    expect(screen.queryByRole("heading", { name: "Ask the research library" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Your question" })).toHaveTextContent(
      "What replaces recurrence?",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Searching papers and checking evidence…",
    );

    resolve(verified);
    expect(await screen.findByText("The Transformer relies entirely on self-attention.")).toBeInTheDocument();
    expect(screen.getByLabelText("Question")).toHaveValue("");
    expect(screen.getByRole("article", { name: "Relay response" })).toBeInTheDocument();
    expect(screen.getByText("Verified against cited passages")).toBeInTheDocument();
    const citation = screen.getByRole("button", { name: "Open citation: Attention Is All You Need, page 2" });
    await user.click(citation);
    expect(screen.getByRole("dialog", { name: "Source passage" })).toHaveTextContent(
      "The Transformer relies entirely on self-attention instead of recurrence.",
    );
    await user.click(screen.getByRole("button", { name: "Close source passage" }));
    expect(citation).toHaveFocus();
    expect(onRun).toHaveBeenCalledOnce();
  });

  it("distinguishes an evidence refusal from daily capacity exhaustion", async () => {
    const user = userEvent.setup();
    const refused = {
      ...verified,
      request_id: "request-2",
      disposition: "refused",
      answer: "I couldn't find enough supporting evidence in these three papers to answer that question.",
      evidence: [],
      reason: "model_refused",
    } satisfies Answer;
    const exhausted = {
      ...verified,
      request_id: "request-3",
      status: "rate_limited",
      disposition: "unavailable",
      answer: "No unverified answer was released.",
      evidence: [],
      tokens_in: 0,
      tokens_out: 0,
      reason: "daily_budget_exhausted",
    } satisfies Answer;
    const ask = vi.fn().mockResolvedValueOnce(refused).mockResolvedValueOnce(exhausted);
    render(<Harness ask={ask} />);

    const input = screen.getByLabelText("Question");
    await user.type(input, "What did the papers spend on training?");
    await user.click(screen.getByRole("button", { name: "Ask The Relay" }));
    expect(await screen.findByText("Evidence insufficient")).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "Try another question");
    await user.click(screen.getByRole("button", { name: "Ask The Relay" }));
    expect(await screen.findByText("Today's model budget is used up.")).toBeInTheDocument();
  });

  it("maps connection failures to safe copy", async () => {
    const user = userEvent.setup();
    render(<Harness ask={vi.fn().mockRejectedValue(new TypeError("network detail"))} />);
    await user.type(screen.getByLabelText("Question"), "Can the service answer?");
    await user.click(screen.getByRole("button", { name: "Ask The Relay" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAccessibleName("Relay response");
    expect(alert).toHaveTextContent(
      "The Relay could not connect to the local service.",
    );
    expect(alert.querySelector(".assistant-message-copy")).toHaveTextContent(
      "Check that the API is running and try again.",
    );
    expect(screen.queryByText("network detail")).not.toBeInTheDocument();
  });

  it("distinguishes configuration HTTP failures from offline failures", async () => {
    const user = userEvent.setup();
    render(<Harness ask={vi.fn().mockRejectedValue(new ApiError("Set GROQ_API_KEY locally", 503))} />);
    await user.type(screen.getByLabelText("Question"), "Can the service answer?");
    await user.click(screen.getByRole("button", { name: "Ask The Relay" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The model service is not configured.",
    );
    expect(screen.queryByText("Set GROQ_API_KEY locally")).not.toBeInTheDocument();
    expect(screen.queryByText(/could not connect/i)).not.toBeInTheDocument();
  });

  it("labels a backend queue timeout as queue behavior", async () => {
    const user = userEvent.setup();
    const queueTimeout = {
      ...verified,
      status: "timeout",
      disposition: "unavailable",
      answer: "No unverified answer was released.",
      evidence: [],
      reason: "queue_timeout",
    } satisfies Answer;
    render(<Harness ask={vi.fn().mockResolvedValue(queueTimeout)} />);
    await user.type(screen.getByLabelText("Question"), "Can the queue accept this?");
    await user.click(screen.getByRole("button", { name: "Ask The Relay" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The request waited too long in the queue.",
    );
  });

  it("cancels the request without erasing the draft or showing an error", async () => {
    const user = userEvent.setup();
    const ask = vi.fn((_input, signal?: AbortSignal) =>
      new Promise<Answer>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }),
    );
    render(<Harness ask={ask} />);
    const input = screen.getByLabelText("Question");
    await user.type(input, "Keep this draft");
    await user.click(screen.getByRole("button", { name: "Ask The Relay" }));
    await user.click(screen.getByRole("button", { name: "Cancel request" }));
    expect(input).toHaveValue("Keep this draft");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
