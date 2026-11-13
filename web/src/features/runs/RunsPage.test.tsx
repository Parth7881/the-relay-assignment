import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SessionRun } from "../../lib/types";
import { RunsPage } from "./RunsPage";

const run: SessionRun = {
  requestId: "request-1",
  question: "What replaces recurrence?",
  source: "stand-in",
  status: "ok",
  disposition: "answered",
  totalMs: 1234,
  retrievalSetting: "hybrid-minilm220-rrf-rerank-k4-v1",
  startedAt: "2026-11-12T10:00:00Z",
};

describe("RunsPage", () => {
  it("is honest when this browser session has no runs", () => {
    render(<RunsPage runs={[]} />);
    expect(screen.getByText("No requests in this browser session yet.")).toBeInTheDocument();
    expect(screen.queryByText(/p95|provider limit/i)).not.toBeInTheDocument();
  });

  it("shows only measured fields from a current-session run", () => {
    render(<RunsPage runs={[run]} />);
    expect(screen.getByText("What replaces recurrence?")).toBeInTheDocument();
    expect(screen.getByText("Stand-in")).toBeInTheDocument();
    expect(screen.getByText("Answered")).toBeInTheDocument();
    expect(screen.getByText("1.23 s")).toBeInTheDocument();
    expect(screen.getByText("Hybrid + rerank")).toBeInTheDocument();
  });

  it("does not style an unavailable run as successful", () => {
    const unavailable = {
      ...run,
      status: "rate_limited",
      disposition: "unavailable",
    } satisfies SessionRun;
    render(<RunsPage runs={[unavailable]} />);
    expect(screen.getByText("Rate limited")).toBeInTheDocument();
    expect(screen.getByLabelText("Outcome: Rate limited")).toBeInTheDocument();
    expect(screen.queryByLabelText("Outcome: Answered")).not.toBeInTheDocument();
  });

  it("uses a warning outcome for evidence refusal rather than danger", () => {
    const refused = { ...run, disposition: "refused" } satisfies SessionRun;
    render(<RunsPage runs={[refused]} />);
    expect(screen.getByLabelText("Outcome: Refused")).toHaveAttribute("data-tone", "warning");
  });

  it("wraps a valid long unbroken question instead of clipping it", () => {
    const longQuestion = "x".repeat(2000);
    render(<RunsPage runs={[{ ...run, question: longQuestion }]} />);
    const heading = screen.getByRole("heading", { name: longQuestion });
    expect(heading).toHaveClass("run-question");
    expect(heading.parentElement).toHaveClass("run-summary");
  });
});
