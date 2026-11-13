import { DataUsageRegular, DocumentRegular } from "@fluentui/react-icons";

import type { HealthState, SessionRun } from "../lib/types";

export type View = "ask" | "library" | "runs";

export interface ContextPanelProps {
  view: View;
  healthState: HealthState;
  runs: SessionRun[];
}

const healthLabels: Record<HealthState, string> = {
  checking: "Checking library",
  ready: "Library ready",
  library_not_ready: "Library not ready",
  model_not_configured: "Model not configured",
  unavailable: "Status unavailable",
};

const papers = [
  { shortTitle: "Attention Is All You Need", version: "1706.03762v7" },
  { shortTitle: "Moshi", version: "2410.00037v1" },
  { shortTitle: "Dynamic Chunking", version: "2507.07955v2" },
] as const;

function Readiness({ healthState }: { healthState: HealthState }) {
  return (
    <div className="context-status" data-state={healthState} aria-live="polite">
      <DataUsageRegular aria-hidden="true" />
      <div>
        <span>Service status</span>
        <strong>{healthLabels[healthState]}</strong>
      </div>
    </div>
  );
}

export function ContextPanel({ view, healthState, runs }: ContextPanelProps) {
  if (view === "library") {
    return (
      <div className="context-panel">
        <div className="context-heading">
          <span>Collection</span>
          <h2>Pinned corpus</h2>
        </div>
        <Readiness healthState={healthState} />
        <div className="context-section">
          <span className="context-label">Exact paper versions</span>
          <ul className="context-list">
            {papers.map((paper) => (
              <li key={paper.version}>
                <DocumentRegular aria-hidden="true" />
                <div>
                  <strong>{paper.shortTitle}</strong>
                  <span>{paper.version}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  if (view === "runs") {
    return (
      <div className="context-panel">
        <div className="context-heading">
          <span>Activity</span>
          <h2>Browser session</h2>
        </div>
        <Readiness healthState={healthState} />
        <div className="context-section context-copy">
          <span className="context-label">Local history</span>
          <strong>{runs.length === 0 ? "No requests yet" : `${runs.length} request${runs.length === 1 ? "" : "s"} recorded`}</strong>
          <p>This view records the current browser session. It is not the formal experiment report.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="context-panel">
      <div className="context-heading">
        <span>Workspace</span>
        <h2>Research library</h2>
      </div>
      <Readiness healthState={healthState} />
      <div className="context-section">
        <span className="context-label">Available sources</span>
        <ul className="context-list compact">
          {papers.map((paper) => (
            <li key={paper.version}>
              <DocumentRegular aria-hidden="true" />
              <strong>{paper.shortTitle}</strong>
            </li>
          ))}
        </ul>
      </div>
      <div className="context-section context-copy">
        <span className="context-label">Retrieval</span>
        <strong>Hybrid + rerank</strong>
        <p>Answers are checked against retrieved evidence before they are shown.</p>
      </div>
    </div>
  );
}
