import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Paper } from "../../lib/types";
import { LibraryPage } from "./LibraryPage";

const papers: Paper[] = [
  {
    id: "1706.03762v7",
    title: "Attention Is All You Need",
    url: "https://arxiv.org/pdf/1706.03762v7",
  },
  {
    id: "2410.00037v1",
    title: "Moshi: a speech-text foundation model for real-time dialogue",
    url: "https://arxiv.org/pdf/2410.00037v1",
  },
  {
    id: "2507.07955v2",
    title: "Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
    url: "https://arxiv.org/pdf/2507.07955v2",
  },
];

describe("LibraryPage", () => {
  it("shows loading then the fixed paper rows with safe pinned links", async () => {
    let resolve!: (papers: Paper[]) => void;
    const loadLibrary = vi.fn(() => new Promise<Paper[]>((done) => (resolve = done)));
    render(<LibraryPage loadLibrary={loadLibrary} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the fixed library…");

    resolve(papers);
    expect(await screen.findByText("Attention Is All You Need")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getAllByText("Pinned")).toHaveLength(3);
    const links = screen.getAllByRole("link", { name: /Open pinned PDF/ });
    expect(links[0]).toHaveAttribute("href", "https://arxiv.org/pdf/1706.03762v7");
    expect(links[0]).toHaveAttribute("rel", "noreferrer");
    expect(screen.queryByRole("button", { name: /upload/i })).not.toBeInTheDocument();
  });

  it("shows explicit empty and safe failure states", async () => {
    const { rerender } = render(<LibraryPage loadLibrary={vi.fn().mockResolvedValue([])} />);
    expect(await screen.findByText("No pinned papers are available.")).toBeInTheDocument();

    rerender(<LibraryPage loadLibrary={vi.fn().mockRejectedValue(new Error("private detail"))} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The fixed library could not be loaded.",
    );
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
  });
});
