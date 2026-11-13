import {
  BeakerRegular,
  CheckmarkCircleRegular,
  ClockRegular,
  ErrorCircleRegular,
  GaugeRegular,
  ServerRegular,
  WarningRegular,
} from "@fluentui/react-icons";

import type { RetrievalSetting, SessionRun } from "../../lib/types";

function settingLabel(setting: RetrievalSetting) {
  if (setting === "hybrid-minilm220-rrf-rerank-k4-v1") return "Hybrid + rerank";
  if (setting === "hybrid-minilm220-rrf-k4-v1") return "Hybrid";
  return "Lexical";
}

function dispositionLabel(run: SessionRun) {
  if (run.disposition === "answered") return "Answered";
  if (run.disposition === "refused") return "Refused";
  return run.status === "rate_limited" ? "Rate limited" : "Unavailable";
}

export interface RunsPageProps {
  runs: SessionRun[];
}

export function RunsPage({ runs }: RunsPageProps) {
  return (
    <section className="collection-view" aria-labelledby="runs-title">
      <header className="collection-heading">
        <span className="eyebrow"><BeakerRegular aria-hidden="true" />Session evidence</span>
        <h1 id="runs-title">Current session runs</h1>
        <p>Only requests made in this browser session appear here. This is not the experiment results report.</p>
      </header>

      {runs.length === 0 ? (
        <div className="empty-run-state">
          <BeakerRegular aria-hidden="true" />
          <strong>No requests in this browser session yet.</strong>
          <p>Ask a question to record its real returned status, source, retrieval setting, and total latency.</p>
        </div>
      ) : (
        <div className="run-list" aria-label="Session runs">
          {runs.map((run) => {
            const StatusIcon = run.disposition === "answered"
              ? CheckmarkCircleRegular
              : run.disposition === "refused"
                ? WarningRegular
                : ErrorCircleRegular;
            const outcome = dispositionLabel(run);
            const tone = run.disposition === "answered"
              ? "success"
              : run.disposition === "refused"
                ? "warning"
                : "danger";
            return (
              <article className="run-row" key={run.requestId}>
                <div className="run-summary">
                  <span
                    className="run-status"
                    data-tone={tone}
                    aria-label={`Outcome: ${outcome}`}
                  >
                    <StatusIcon aria-hidden="true" />{outcome}
                  </span>
                  <h2 className="run-question">{run.question}</h2>
                  <time dateTime={run.startedAt}>{new Date(run.startedAt).toLocaleString()}</time>
                </div>
                <dl className="run-facts">
                  <div><dt><ServerRegular aria-hidden="true" />Source</dt><dd>{run.source === "stand-in" ? "Stand-in" : "Real"}</dd></div>
                  <div><dt><ClockRegular aria-hidden="true" />Total</dt><dd>{(run.totalMs / 1000).toFixed(2)} s</dd></div>
                  <div><dt><GaugeRegular aria-hidden="true" />Retrieval</dt><dd>{settingLabel(run.retrievalSetting)}</dd></div>
                </dl>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
