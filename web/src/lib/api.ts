import type { Answer, AskInput, HealthStatus, Paper } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const RETRIEVAL_SETTINGS = new Set([
  "lexical-word180-k4-v1",
  "hybrid-minilm220-rrf-k4-v1",
  "hybrid-minilm220-rrf-rerank-k4-v1",
]);
const PAPER_IDS = new Set(["1706.03762v7", "2410.00037v1", "2507.07955v2"]);

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isNumberRecord(value: unknown): value is Record<string, number> {
  return isRecord(value) && Object.values(value).every(
    (entry) => typeof entry === "number" && Number.isFinite(entry),
  );
}

function isHit(value: unknown): boolean {
  if (!isRecord(value) || !isRecord(value.chunk)) return false;
  const chunk = value.chunk;
  return (
    typeof chunk.id === "string" &&
    typeof chunk.paper_id === "string" && PAPER_IDS.has(chunk.paper_id) &&
    typeof chunk.title === "string" &&
    typeof chunk.page === "number" && Number.isInteger(chunk.page) && chunk.page >= 1 &&
    typeof chunk.start === "number" && Number.isFinite(chunk.start) &&
    typeof chunk.end === "number" && Number.isFinite(chunk.end) && chunk.end > chunk.start &&
    typeof chunk.text === "string" &&
    typeof value.score === "number" &&
    Number.isFinite(value.score) &&
    isNumberRecord(value.scores)
  );
}

function isAnswer(value: unknown): value is Answer {
  if (!isRecord(value)) return false;
  return (
    typeof value.request_id === "string" &&
    typeof value.question === "string" &&
    typeof value.start_time === "string" &&
    (value.source === "real" || value.source === "stand-in") &&
    ["ok", "rate_limited", "timeout", "error"].includes(String(value.status)) &&
    ["answered", "refused", "unavailable"].includes(String(value.disposition)) &&
    typeof value.answer === "string" &&
    Array.isArray(value.evidence) && value.evidence.every(isHit) &&
    isNullableNumber(value.first_token_ms) &&
    typeof value.total_ms === "number" && Number.isFinite(value.total_ms) &&
    isNullableNumber(value.tokens_in) &&
    isNullableNumber(value.tokens_out) &&
    Number.isInteger(value.retries) &&
    RETRIEVAL_SETTINGS.has(String(value.retrieval_setting)) &&
    typeof value.reason === "string"
  );
}

function isPaper(value: unknown): value is Paper {
  return (
    isRecord(value) &&
    typeof value.id === "string" && PAPER_IDS.has(value.id) &&
    typeof value.title === "string" &&
    value.url === `https://arxiv.org/pdf/${value.id}`
  );
}

function isHealthStatus(value: unknown): value is HealthStatus {
  return (
    isRecord(value) &&
    value.status === "ok" &&
    typeof value.phase === "string" &&
    typeof value.corpus_ready === "boolean" &&
    typeof value.model_configured === "boolean"
  );
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function askQuestion(input: AskInput, signal?: AbortSignal): Promise<Answer> {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
  const data = await readJson(response);
  if (!response.ok) {
    const detail = isRecord(data) && typeof data.detail === "string" ? data.detail : null;
    throw new ApiError(
      detail ?? "The Relay service could not complete the request.",
      response.status,
    );
  }
  if (!isAnswer(data)) throw new ApiError("The Relay returned an invalid response.", response.status);
  return data;
}

export async function getLibrary(signal?: AbortSignal): Promise<Paper[]> {
  const response = await fetch("/api/library", { signal });
  const data = await readJson(response);
  if (!response.ok) {
    throw new ApiError("The fixed library could not be loaded.", response.status);
  }
  if (!Array.isArray(data) || !data.every(isPaper)) {
    throw new ApiError("The Relay returned an invalid library response.", response.status);
  }
  return data;
}

export async function getHealth(signal?: AbortSignal): Promise<HealthStatus> {
  const response = await fetch("/health", { signal });
  const data = await readJson(response);
  if (!response.ok) {
    throw new ApiError("The Relay health check is unavailable.", response.status);
  }
  if (!isHealthStatus(data)) {
    throw new ApiError("The Relay returned an invalid health response.", response.status);
  }
  return data;
}
