import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const readyHealth = {
  status: "ok",
  phase: "part-4",
  corpus_ready: true,
  model_configured: true,
} as const;

function readyLoader() {
  return vi.fn().mockResolvedValue(readyHealth);
}

describe("app shell", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.dataset.theme = "light";
  });

  it("navigates among the three product views", async () => {
    const user = userEvent.setup();
    render(<App loadHealth={readyLoader()} />);

    const navigation = screen.getByRole("navigation", { name: "Primary" });
    expect(navigation).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ask the research library" }))
      .toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Library" }));
    expect(screen.getByRole("heading", { name: "The fixed research library" }))
      .toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Runs" }));
    expect(screen.getByRole("heading", { name: "Current session runs" })).toBeInTheDocument();
  });

  it("exposes named theme controls and applies Black", async () => {
    const user = userEvent.setup();
    render(<App loadHealth={readyLoader()} />);
    await user.click(screen.getByRole("button", { name: "Use Black theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "black");
    expect(localStorage.getItem("relay-theme-v1")).toBe("black");
  });

  it("uses true Black for a fresh visitor", () => {
    render(<App loadHealth={readyLoader()} />);
    expect(document.documentElement).toHaveAttribute("data-theme", "black");
    expect(screen.getByRole("button", { name: "Use Black theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("renders enterprise chrome and view-specific context", async () => {
    const user = userEvent.setup();
    const loadHealth = readyLoader();
    render(<App loadHealth={loadHealth} />);

    expect(screen.getByRole("link", { name: "The Relay home" })).toBeInTheDocument();
    expect(screen.getByText("Fixed research library")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Research library" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Workspace command bar" })).getByText("Ask"))
      .toBeInTheDocument();
    expect(await screen.findByText("Library ready")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Mobile readiness" })).toHaveTextContent("Ready");

    await user.click(screen.getByRole("button", { name: "Library" }));
    expect(screen.getByRole("heading", { name: "Pinned corpus" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Workspace command bar" })).getByText("Library"))
      .toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Runs" }));
    expect(screen.getByRole("heading", { name: "Browser session" })).toBeInTheDocument();
    expect(loadHealth).toHaveBeenCalledOnce();
  });

  it("shows honest one-shot readiness states", async () => {
    const { unmount } = render(
      <App
        loadHealth={vi.fn().mockResolvedValue({
          ...readyHealth,
          corpus_ready: false,
        })}
      />,
    );
    expect(await screen.findByRole("status", { name: "Mobile readiness" }))
      .toHaveTextContent("Library not ready");
    unmount();

    render(
      <App
        loadHealth={vi.fn().mockResolvedValue({
          ...readyHealth,
          model_configured: false,
        })}
      />,
    );
    expect(await screen.findByRole("status", { name: "Mobile readiness" }))
      .toHaveTextContent("Model not configured");
  });

  it("shows unavailable without retrying a failed health check", async () => {
    const user = userEvent.setup();
    const loadHealth = vi.fn().mockRejectedValue(new Error("private failure"));
    render(<App loadHealth={loadHealth} />);
    expect(await screen.findByRole("status", { name: "Mobile readiness" }))
      .toHaveTextContent("Status unavailable");

    await user.click(screen.getByRole("button", { name: "Library" }));
    await user.click(screen.getByRole("button", { name: "Use Black theme" }));
    await waitFor(() => expect(loadHealth).toHaveBeenCalledOnce());
    expect(screen.queryByText("private failure")).not.toBeInTheDocument();
  });
});
