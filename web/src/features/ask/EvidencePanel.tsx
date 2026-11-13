import { useEffect, useRef } from "react";
import { DismissRegular, DocumentRegular, OpenRegular } from "@fluentui/react-icons";

import type { Hit } from "../../lib/types";

const ALLOWED_PAPERS = new Set(["1706.03762v7", "2410.00037v1", "2507.07955v2"]);

export interface EvidencePanelProps {
  evidence: Hit;
  onClose: () => void;
}

export function EvidencePanel({ evidence, onClose }: EvidencePanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const { chunk } = evidence;
  const pdfUrl = ALLOWED_PAPERS.has(chunk.paper_id)
    ? `https://arxiv.org/pdf/${chunk.paper_id}#page=${chunk.page}`
    : null;

  useEffect(() => {
    closeRef.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <aside
      className="evidence-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="source-passage-title"
    >
      <div className="sheet-handle" aria-hidden="true" />
      <header className="evidence-header">
        <h2 id="source-passage-title">Source passage</h2>
        <button ref={closeRef} className="icon-button" type="button" aria-label="Close source passage" onClick={onClose}>
          <DismissRegular aria-hidden="true" />
        </button>
      </header>
      <div className="evidence-paper">
        <DocumentRegular aria-hidden="true" />
        <div>
          <strong>{chunk.title}</strong>
          <span>Page {chunk.page}</span>
        </div>
        {pdfUrl ? (
          <a href={pdfUrl} target="_blank" rel="noreferrer" aria-label="Open original PDF">
            <OpenRegular aria-hidden="true" />
          </a>
        ) : null}
      </div>
      <div className="verified-line">Verified against cited passages</div>
      <blockquote>{chunk.text}</blockquote>
      <div className="evidence-id">{chunk.paper_id} · p. {chunk.page}</div>
    </aside>
  );
}
