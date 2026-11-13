import { useEffect, useState } from "react";
import { ArrowUpRightRegular, DocumentRegular, LockClosedRegular } from "@fluentui/react-icons";

import { getLibrary } from "../../lib/api";
import type { Paper } from "../../lib/types";

const ALLOWED_PAPERS = new Set(["1706.03762v7", "2410.00037v1", "2507.07955v2"]);

export interface LibraryPageProps {
  loadLibrary?: (signal?: AbortSignal) => Promise<Paper[]>;
}

export function LibraryPage({ loadLibrary = getLibrary }: LibraryPageProps) {
  const [papers, setPapers] = useState<Paper[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setPapers(null);
    setFailed(false);
    void loadLibrary(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setPapers(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [loadLibrary]);

  return (
    <section className="collection-view" aria-labelledby="library-title">
      <header className="collection-heading">
        <span className="eyebrow"><LockClosedRegular aria-hidden="true" />Pinned corpus</span>
        <h1 id="library-title">The fixed research library</h1>
        <p>Answers can cite only these exact paper versions. Uploads are intentionally disabled.</p>
      </header>

      {failed ? (
        <div className="inline-state" role="alert">
          <strong>The fixed library could not be loaded.</strong>
          <p>Check that the local API is running, then return to this view.</p>
        </div>
      ) : papers === null ? (
        <div className="inline-state" role="status">Loading the fixed library…</div>
      ) : papers.length === 0 ? (
        <div className="inline-state">No pinned papers are available.</div>
      ) : (
        <div className="paper-list" aria-label="Pinned papers">
          {papers.map((paper, index) => {
            const pdfUrl = ALLOWED_PAPERS.has(paper.id)
              ? `https://arxiv.org/pdf/${paper.id}`
              : null;
            return (
              <article className="paper-row" key={paper.id}>
                <div className="paper-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</div>
                <DocumentRegular aria-hidden="true" />
                <div className="paper-copy">
                  <h2>{paper.title}</h2>
                  <p>arXiv {paper.id} <span className="paper-status">Pinned</span></p>
                </div>
                {pdfUrl ? (
                  <a href={pdfUrl} target="_blank" rel="noreferrer" aria-label={`Open pinned PDF: ${paper.title}`}>
                    <span>PDF</span><ArrowUpRightRegular aria-hidden="true" />
                  </a>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
