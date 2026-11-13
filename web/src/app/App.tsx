import { useEffect, useState } from "react";
import {
  BeakerRegular,
  ChatRegular,
  DesktopRegular,
  LayerRegular,
  LibraryRegular,
  WeatherMoonRegular,
  WeatherSunnyRegular,
} from "@fluentui/react-icons";

import { AskPage } from "../features/ask/AskPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { RunsPage } from "../features/runs/RunsPage";
import { getHealth } from "../lib/api";
import type { HealthState, SessionRun } from "../lib/types";
import { ContextPanel, type View } from "./ContextPanel";
import { applyTheme, readInitialTheme, type Theme } from "./theme";

const navigation = [
  { id: "ask", label: "Ask", icon: ChatRegular },
  { id: "library", label: "Library", icon: LibraryRegular },
  { id: "runs", label: "Runs", icon: BeakerRegular },
] satisfies ReadonlyArray<{ id: View; label: string; icon: typeof ChatRegular }>;

const themes = [
  { id: "light", label: "Light", icon: WeatherSunnyRegular },
  { id: "dark", label: "Dark", icon: WeatherMoonRegular },
  { id: "black", label: "Black", icon: DesktopRegular },
] satisfies ReadonlyArray<{ id: Theme; label: string; icon: typeof WeatherSunnyRegular }>;

const healthUtilityLabels: Record<HealthState, string> = {
  checking: "Checking local status",
  ready: "Local service ready",
  library_not_ready: "Local corpus unavailable",
  model_not_configured: "Local model unavailable",
  unavailable: "Local status unavailable",
};

const healthMobileLabels: Record<HealthState, string> = {
  checking: "Checking library",
  ready: "Ready",
  library_not_ready: "Library not ready",
  model_not_configured: "Model not configured",
  unavailable: "Status unavailable",
};

export interface AppProps {
  loadHealth?: typeof getHealth;
}

export function App({ loadHealth = getHealth }: AppProps) {
  const [view, setView] = useState<View>("ask");
  const [draft, setDraft] = useState("");
  const [sessionRuns, setSessionRuns] = useState<SessionRun[]>([]);
  const [healthState, setHealthState] = useState<HealthState>("checking");
  const [theme, setTheme] = useState<Theme>(() =>
    readInitialTheme(
      window.localStorage,
      window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false,
    ),
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const controller = new AbortController();

    void loadHealth(controller.signal)
      .then((health) => {
        if (!health.corpus_ready) {
          setHealthState("library_not_ready");
        } else if (!health.model_configured) {
          setHealthState("model_not_configured");
        } else {
          setHealthState("ready");
        }
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setHealthState("unavailable");
        }
      });

    return () => controller.abort();
  }, [loadHealth]);

  function selectTheme(next: Theme) {
    applyTheme(next, window.localStorage);
    setTheme(next);
  }

  return (
    <div className="app-shell">
      <header className="identity-bar">
        <a className="brand" href="#main-content" aria-label="The Relay home">
          <LayerRegular aria-hidden="true" />
          <span>The Relay</span>
        </a>
        <div className="identity-meta">
          <span>Fixed research library</span>
          <span className="utility-status" data-state={healthState}>
            {healthUtilityLabels[healthState]}
          </span>
        </div>
      </header>

      <section className="commandbar" role="region" aria-label="Workspace command bar">
        <div className="commandbar-current">
          <span>Research workspace</span>
          <strong>{navigation.find((item) => item.id === view)?.label}</strong>
        </div>
        <div className="theme-switcher" role="group" aria-label="Color theme">
          {themes.map(({ id, label, icon: Icon }) => (
            <button
              className="theme-button"
              data-selected={theme === id}
              key={id}
              type="button"
              aria-label={`Use ${label} theme`}
              aria-pressed={theme === id}
              onClick={() => selectTheme(id)}
            >
              <Icon aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </section>

      <nav className="primary-nav" aria-label="Primary">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button
            className="nav-button"
            data-selected={view === id}
            key={id}
            type="button"
            aria-current={view === id ? "page" : undefined}
            onClick={() => setView(id)}
          >
            <Icon aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      <aside className="context-panel-shell" aria-label={`${navigation.find((item) => item.id === view)?.label} context`}>
        <ContextPanel view={view} healthState={healthState} runs={sessionRuns} />
      </aside>

      <div
        className="mobile-status"
        role="status"
        aria-label="Mobile readiness"
        data-state={healthState}
      >
        <span>Local readiness</span>
        <strong>{healthMobileLabels[healthState]}</strong>
      </div>

      <main id="main-content" className="main-content" tabIndex={-1}>
        {view === "ask" ? (
          <AskPage
            draft={draft}
            onDraftChange={setDraft}
            onRun={(run) => setSessionRuns((current) => [run, ...current])}
          />
        ) : view === "library" ? (
          <LibraryPage />
        ) : (
          <RunsPage runs={sessionRuns} />
        )}
      </main>
    </div>
  );
}
