import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, askQuestion, getHealth } from "./api";

const answer = {
  request_id: "request-1",
  question: "What replaces recurrence?",
  start_time: "2026-11-12T10:00:00+00:00",
  source: "real",
  status: "ok",
  disposition: "answered",
  answer: "Self-attention. [1706.03762v7:p2:w150]",
  evidence: [],
  first_token_ms: null,
  total_ms: 1200,
  tokens_in: 100,
  tokens_out: 20,
  retries: 0,
  retrieval_setting: "hybrid-minilm220-rrf-rerank-k4-v1",
  reason: "support_checks_passed",
} as const;

afterEach(() => vi.unstubAllGlobals());

describe("askQuestion", () => {
  it("sends only the question and selected retrieval setting with the abort signal", async () => {
    const signal = new AbortController().signal;
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(answer), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetcher);

    await expect(
      askQuestion(
        {
          question: "What replaces recurrence?",
          retrieval_setting: "hybrid-minilm220-rrf-rerank-k4-v1",
        },
        signal,
      ),
    ).resolves.toEqual(answer);

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: "What replaces recurrence?",
        retrieval_setting: "hybrid-minilm220-rrf-rerank-k4-v1",
      }),
      signal,
    });
  });

  it("uses a safe server detail and a generic message for malformed responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "Model access is not configured." }), {
            status: 503,
          }),
        )
        .mockResolvedValueOnce(new Response("not-json", { status: 502 }))
        .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" }), { status: 200 }))
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ ...answer, evidence: [{}] }), { status: 200 }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ ...answer, retrieval_setting: "invented" }), { status: 200 }),
        ),
    );

    await expect(
      askQuestion({ question: "Question", retrieval_setting: "lexical-word180-k4-v1" }),
    ).rejects.toMatchObject({ message: "Model access is not configured.", status: 503 });
    await expect(
      askQuestion({ question: "Question", retrieval_setting: "lexical-word180-k4-v1" }),
    ).rejects.toEqual(
      new ApiError("The Relay service could not complete the request.", 502),
    );
    await expect(
      askQuestion({ question: "Question", retrieval_setting: "lexical-word180-k4-v1" }),
    ).rejects.toEqual(new ApiError("The Relay returned an invalid response.", 200));
    await expect(
      askQuestion({ question: "Question", retrieval_setting: "lexical-word180-k4-v1" }),
    ).rejects.toEqual(new ApiError("The Relay returned an invalid response.", 200));
    await expect(
      askQuestion({ question: "Question", retrieval_setting: "lexical-word180-k4-v1" }),
    ).rejects.toEqual(new ApiError("The Relay returned an invalid response.", 200));
  });
});

describe("getHealth", () => {
  it("requests same-origin readiness once and validates the exact response", async () => {
    const signal = new AbortController().signal;
    const health = {
      status: "ok",
      phase: "part-4",
      corpus_ready: true,
      model_configured: false,
    } as const;
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(health), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetcher);

    await expect(getHealth(signal)).resolves.toEqual(health);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/health", { signal });
  });

  it("rejects malformed health data without exposing its body", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              status: "ok",
              phase: "part-4",
              corpus_ready: "yes",
              model_configured: false,
            }),
            { status: 200 },
          ),
        )
        .mockResolvedValueOnce(new Response("internal detail", { status: 503 })),
    );

    await expect(getHealth()).rejects.toEqual(
      new ApiError("The Relay returned an invalid health response.", 200),
    );
    await expect(getHealth()).rejects.toEqual(
      new ApiError("The Relay health check is unavailable.", 503),
    );
  });
});
