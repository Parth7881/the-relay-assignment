import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  CheckmarkCircleRegular,
  DocumentRegular,
  SendRegular,
  StopRegular,
  WarningRegular,
} from "@fluentui/react-icons";

import { ApiError, askQuestion } from "../../lib/api";
import type { Answer, AskInput, Hit, SessionRun } from "../../lib/types";
import { splitAnswer } from "./answer-parts";
import { EvidencePanel } from "./EvidencePanel";

type AskFunction = (input: AskInput, signal?: AbortSignal) => Promise<Answer>;
type RequestError = { title: string; body: string };

export interface AskPageProps {
  draft: string;
  onDraftChange: (value: string) => void;
  ask?: AskFunction;
  onRun?: (run: SessionRun) => void;
}

function runFrom(answer: Answer): SessionRun {
  return {
    requestId: answer.request_id,
    question: answer.question,
    source: answer.source,
    status: answer.status,
    disposition: answer.disposition,
    totalMs: answer.total_ms,
    retrievalSetting: answer.retrieval_setting,
    startedAt: answer.start_time,
  };
}

function unavailableCopy(answer: Answer): { title: string; body: string } {
  if (answer.reason === "daily_budget_exhausted") {
    return {
      title: "Today's model budget is used up.",
      body: "I can't generate a verified answer right now. You can still read the three papers and inspect available passages. Please try again after the budget resets.",
    };
  }
  if (answer.reason === "queue_timeout") {
    return {
      title: "The request waited too long in the queue.",
      body: "No unverified answer was shown. Please retry after an active request finishes.",
    };
  }
  if (answer.status === "rate_limited") {
    if (answer.reason === "queue_full") {
      return {
        title: "The request queue is full.",
        body: "No unverified answer was shown. Please wait for an active request to finish, then retry.",
      };
    }
    if (
      answer.reason === "minute_budget_exhausted" ||
      answer.reason === "request_exceeds_minute_budget"
    ) {
      return {
        title: "The minute token budget is temporarily used up.",
        body: "No unverified answer was shown. Please retry after the current minute window recovers.",
      };
    }
    return {
      title: "The model is at capacity right now.",
      body: "No unverified answer was shown. Please try again shortly.",
    };
  }
  if (answer.status === "timeout") {
    return {
      title: "The request took too long.",
      body: "No unverified answer was shown. Your question is still here so you can retry.",
    };
  }
  return {
    title: "The model service could not complete this request.",
    body: "No unverified answer was shown. Please check the local service and try again.",
  };
}

function requestFailureCopy(error: unknown): RequestError {
  if (error instanceof ApiError) {
    if (error.status === 503 && error.message.includes("GROQ_API_KEY")) {
      return {
        title: "The model service is not configured.",
        body: "Add the key to the ignored local .env file, then restart the local service.",
      };
    }
    if (error.status === 503 && /retriever|ingest|index|corpus/i.test(error.message)) {
      return {
        title: "The research library is not ready.",
        body: "Run the local ingestion and index commands, then retry.",
      };
    }
    return {
      title: "The local service could not complete this request.",
      body: `The service returned HTTP ${error.status}. No answer was generated.`,
    };
  }
  return {
    title: "The Relay could not connect to the local service.",
    body: "Check that the API is running and try again. No answer was generated.",
  };
}

export function AskPage({ draft, onDraftChange, ask = askQuestion, onRun }: AskPageProps) {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<Hit | null>(null);
  const [pending, setPending] = useState(false);
  const [requestError, setRequestError] = useState<RequestError | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const citationTriggerRef = useRef<HTMLButtonElement | null>(null);

  const closeEvidence = useCallback(() => {
    citationTriggerRef.current?.focus();
    setSelectedEvidence(null);
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || pending) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setPending(true);
    setRequestError(null);
    setSelectedEvidence(null);
    setAnswer(null);
    setSubmittedQuestion(question);
    try {
      const result = await ask(
        {
          question,
          retrieval_setting: "hybrid-minilm220-rrf-rerank-k4-v1",
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setAnswer(result);
      if (result.status === "ok") {
        onDraftChange("");
      }
      onRun?.(runFrom(result));
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setRequestError(requestFailureCopy(error));
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setPending(false);
      }
    }
  }

  function cancel() {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setPending(false);
    setRequestError(null);
  }

  const operational = answer && answer.status !== "ok" ? unavailableCopy(answer) : null;
  const parts = answer?.disposition === "answered" ? splitAnswer(answer.answer, answer.evidence) : [];

  return (
    <div className="ask-workspace" data-evidence-open={Boolean(selectedEvidence)}>
      <section
        className="ask-column"
        aria-label={submittedQuestion ? "Ask The Relay conversation" : undefined}
        aria-labelledby={submittedQuestion ? undefined : "ask-title"}
      >
        {!submittedQuestion ? (
          <header className="ask-heading">
            <h1 id="ask-title">Ask the research library</h1>
            <p>Answers are released only when the cited passages support them.</p>
          </header>
        ) : null}

        {submittedQuestion ? (
          <div className="conversation-stream">
            <article className="question-row" aria-label="Your question">
              <span>{submittedQuestion}</span>
            </article>

            {pending ? (
              <div className="assistant-message request-state" role="status" aria-label="Relay response">
                <span className="status-dot" aria-hidden="true" />
                <div className="assistant-message-copy">
                  <span className="message-author">The Relay</span>
                  <strong>Searching papers and checking evidence…</strong>
                  <p>A verified answer may require more than one retrieval pass.</p>
                </div>
              </div>
            ) : null}

            {requestError ? (
              <div className="assistant-message request-state error-state" role="alert" aria-label="Relay response">
                <WarningRegular aria-hidden="true" />
                <div className="assistant-message-copy">
                  <span className="message-author">The Relay</span>
                  <strong>{requestError.title}</strong>
                  <p>{requestError.body}</p>
                </div>
              </div>
            ) : null}

            {operational ? (
              <div className="assistant-message request-state error-state" role="alert" aria-label="Relay response">
                <WarningRegular aria-hidden="true" />
                <div className="assistant-message-copy">
                  <span className="message-author">The Relay</span>
                  <strong>{operational.title}</strong>
                  <p>{operational.body}</p>
                </div>
              </div>
            ) : null}

            {answer?.status === "ok" && answer.disposition === "refused" ? (
              <article className="assistant-message answer-block" aria-label="Relay response">
                <span className="message-author">The Relay</span>
                <div className="answer-label">Evidence insufficient</div>
                <p>{answer.answer}</p>
              </article>
            ) : null}

            {answer?.status === "ok" && answer.disposition === "answered" ? (
              <article className="assistant-message answer-block" aria-label="Relay response">
                <span className="message-author">The Relay</span>
                <div className="verification-row">
                  <span><CheckmarkCircleRegular aria-hidden="true" />Verified against cited passages</span>
                  <span>Retrieval: Hybrid + rerank</span>
                </div>
                <p className="answer-text">
                  {parts.map((part, index) =>
                    part.type === "text" ? (
                      <span key={`${index}-${part.text.slice(0, 12)}`}>{part.text}</span>
                    ) : (
                      <button
                        className="citation-button"
                        key={`${index}-${part.evidence.chunk.id}`}
                        type="button"
                        aria-label={`Open citation: ${part.evidence.chunk.title}, page ${part.evidence.chunk.page}`}
                        onClick={(event) => {
                          citationTriggerRef.current = event.currentTarget;
                          setSelectedEvidence(part.evidence);
                        }}
                      >
                        <DocumentRegular aria-hidden="true" />
                        {part.evidence.chunk.title === "Attention Is All You Need"
                          ? "Transformer"
                          : part.evidence.chunk.title.split(":")[0]} · p. {part.evidence.chunk.page}
                      </button>
                    ),
                  )}
                </p>
              </article>
            ) : null}
          </div>
        ) : null}

        <form className="question-composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="relay-question">Question</label>
          <textarea
            id="relay-question"
            maxLength={2000}
            rows={2}
            value={draft}
            placeholder="Ask a question about the library…"
            onChange={(event) => onDraftChange(event.target.value)}
          />
          <div className="composer-footer">
            <span>{draft.length.toLocaleString()} / 2,000</span>
            {pending ? (
              <button className="secondary-button" type="button" onClick={cancel}>
                <StopRegular aria-hidden="true" />Cancel request
              </button>
            ) : (
              <button className="primary-button" type="submit" disabled={!draft.trim()}>
                <SendRegular aria-hidden="true" />Ask The Relay
              </button>
            )}
          </div>
        </form>
      </section>

      {selectedEvidence ? (
        <EvidencePanel evidence={selectedEvidence} onClose={closeEvidence} />
      ) : null}
    </div>
  );
}
