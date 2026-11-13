export type RetrievalSetting =
  | "lexical-word180-k4-v1"
  | "hybrid-minilm220-rrf-k4-v1"
  | "hybrid-minilm220-rrf-rerank-k4-v1";

export type AnswerStatus = "ok" | "rate_limited" | "timeout" | "error";
export type AnswerDisposition = "answered" | "refused" | "unavailable";

export interface Chunk {
  id: string;
  paper_id: string;
  title: string;
  page: number;
  start: number;
  end: number;
  text: string;
}

export interface Hit {
  chunk: Chunk;
  score: number;
  scores: Record<string, number>;
}

export interface Answer {
  request_id: string;
  question: string;
  start_time: string;
  source: "real" | "stand-in";
  status: AnswerStatus;
  disposition: AnswerDisposition;
  answer: string;
  evidence: Hit[];
  first_token_ms: number | null;
  total_ms: number;
  tokens_in: number | null;
  tokens_out: number | null;
  retries: number;
  retrieval_setting: RetrievalSetting;
  reason: string;
}

export interface AskInput {
  question: string;
  retrieval_setting: RetrievalSetting;
}

export interface Paper {
  id: string;
  title: string;
  url: string;
}

export interface HealthStatus {
  status: "ok";
  phase: string;
  corpus_ready: boolean;
  model_configured: boolean;
}

export type HealthState =
  | "checking"
  | "ready"
  | "library_not_ready"
  | "model_not_configured"
  | "unavailable";

export interface SessionRun {
  requestId: string;
  question: string;
  source: Answer["source"];
  status: AnswerStatus;
  disposition: AnswerDisposition;
  totalMs: number;
  retrievalSetting: RetrievalSetting;
  startedAt: string;
}
