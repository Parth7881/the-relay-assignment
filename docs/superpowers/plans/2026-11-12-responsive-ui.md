# The Relay Responsive UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production-ready React/TypeScript Ask workspace, pinned library view, session Runs view, passage citations, and Light/Dark/Black themes without consuming Groq quota during frontend development.

**Architecture:** A Vite single-page app under `web/` calls the existing same-origin FastAPI `/api` contract. React owns view, theme, draft, cancellation, selected citation, and current-session run state; FastAPI remains the only owner of retrieval, model calls, secrets, budgets, and raw traces. The production Python service optionally serves `web/dist` while development uses Vite's localhost proxy.

**Tech Stack:** React, TypeScript strict mode, Vite, Vitest, Testing Library, plain CSS custom properties, direct Lucide icon imports, FastAPI static files.

**Spec:** `docs/relay-design.md` section 7; visual specs `docs/ui/relay-desktop-concept.png` and `docs/ui/relay-mobile-concept.png`.

## Global Constraints

- Do not make Groq calls while building or testing the UI; use deterministic fetch fixtures and existing saved answer shapes.
- Keep `GROQ_API_KEY` server-side in ignored `.env`; never expose environment secrets through Vite.
- Preserve the three exact retrieval settings and fixed three-paper library.
- Main backgrounds are exact: Light `#FFFFFF`, Dark `#151515`, Black `#000000`; Black surface is `#0A0A0A`.
- Use 16px answer text, approximately 70-character reading width, 8px spacing rhythm, restrained radii, 44px touch targets, visible focus, and reduced-motion support.
- No Markdown/HTML rendering for answers; turn only validated `[chunk_id]` markers matching returned evidence into citation buttons.
- No marketing hero, purple gradient, fake metrics, fake progress, card grid, chat bubbles, uploads, auth, or new provider integration.
- Desktop uses left navigation, reading column, and conditional evidence rail. Mobile uses bottom navigation and an accessible citation bottom sheet.
- Keep files purposeful; no Tailwind, component generator, state framework, animation library, or duplicate backend.
- The repository has no tracked baseline; do not create its first Git commit without explicit user approval.

## Review Focus

- A malformed answer marker must remain inert text and never create an arbitrary citation/link.
- Cancelling a request must abort fetch, preserve the draft, and avoid showing a false error.
- `daily_budget_exhausted`, minute/queue limits, timeouts, missing key, and offline failures must have distinct honest copy.
- Theme initialization must avoid a visible flash, persist explicit Black, and honor system preference only before a saved choice.
- At 390px width, the composer, citation sheet, and bottom navigation must not overlap or create horizontal scroll.

---

### Task 1: Frontend foundation, tokens, theme, and app shell

**Files:**
- Create: `web/package.json`
- Create: `web/package-lock.json`
- Create: `web/index.html`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/src/main.tsx`
- Create: `web/src/app/App.tsx`
- Create: `web/src/app/theme.ts`
- Create: `web/src/styles.css`
- Test: `web/src/app/theme.test.ts`
- Test: `web/src/app/App.test.tsx`

**Interfaces:**
- Produces: `Theme = "light" | "dark" | "black"`, `readInitialTheme(storage, media)`, and an app shell with `ask | library | runs` navigation.
- Consumes: design tokens and copy from the approved concepts.

- [x] **Step 1: Scaffold the minimal Vite/React/TypeScript project and pin dependencies in the lockfile.**

- [x] **Step 2: Write failing theme tests.** Assert saved Black wins over system preference, missing saved choice maps dark system preference to Dark, invalid storage is ignored, and setting a theme updates `data-theme` plus `localStorage`.

- [x] **Step 3: Run `npm test -- --run src/app/theme.test.ts` from `web/`.** Expected: FAIL because theme functions do not exist.

- [x] **Step 4: Implement the theme contract and no-flash initialization.** Keep storage key `relay-theme-v1`; never read storage repeatedly during render.

- [x] **Step 5: Write a failing app-shell test.** Assert semantic navigation exposes Ask, Library, Runs; keyboard/click selection changes the visible heading; theme controls have accessible names.

- [x] **Step 6: Run the focused shell test.** Expected: FAIL because the shell is incomplete.

- [x] **Step 7: Implement the responsive shell and exact CSS tokens.** Use direct Lucide imports and shared button/control classes; keep `App` as composition glue.

- [x] **Step 8: Run focused tests and `npm run build`.** Expected: PASS with no type errors.

### Task 2: Typed API client and Ask/evidence workflow

**Files:**
- Create: `web/src/lib/types.ts`
- Create: `web/src/lib/api.ts`
- Create: `web/src/features/ask/answer-parts.ts`
- Create: `web/src/features/ask/AskPage.tsx`
- Create: `web/src/features/ask/EvidencePanel.tsx`
- Test: `web/src/lib/api.test.ts`
- Test: `web/src/features/ask/answer-parts.test.ts`
- Test: `web/src/features/ask/AskPage.test.tsx`

**Interfaces:**
- Consumes: `POST /api/ask`, `GET /health`, and the existing `Answer`/`Hit` JSON shapes.
- Produces: `askQuestion(input, signal)`, `splitAnswer(answer, evidence)`, selected evidence state, and `SessionRun` records for Task 3.

- [x] **Step 1: Write failing API-client tests.** Assert exact request body, abort signal propagation, typed success parsing, safe error extraction, and no secret/env fields.

- [x] **Step 2: Run the focused client test.** Expected: FAIL because `api.ts` is absent.

- [x] **Step 3: Implement the minimal fetch client.** Use same-origin relative URLs, JSON content type, and a generic message when error bodies are malformed.

- [x] **Step 4: Write failing answer-part tests.** Assert a matching `[chunk_id]` becomes a citation part, unknown/malformed markers remain plain text, ordering is preserved, and duplicate markers share one evidence object.

- [x] **Step 5: Implement plain-text answer parsing.** Never use `dangerouslySetInnerHTML` or a Markdown renderer.

- [x] **Step 6: Write failing Ask workflow tests.** Cover empty submission, loading copy, successful answer, evidence refusal, daily exhaustion, connection failure, citation selection, and cancellation preserving the draft.

- [x] **Step 7: Implement `AskPage` and `EvidencePanel`.** One request at a time; use `AbortController`; show “Searching papers and checking evidence…” without percentages; map backend status/reason to honest user copy.

- [x] **Step 8: Run Task 2 tests and build.** Expected: PASS; tests use fixtures only and perform zero network/model calls.

### Task 3: Library, session Runs, and mobile citation behavior

**Files:**
- Create: `web/src/features/library/LibraryPage.tsx`
- Create: `web/src/features/runs/RunsPage.tsx`
- Modify: `web/src/app/App.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/features/library/LibraryPage.test.tsx`
- Test: `web/src/features/runs/RunsPage.test.tsx`
- Test: `web/src/app/responsive-behavior.test.tsx`

**Interfaces:**
- Consumes: `GET /api/library`, `SessionRun[]`, and selected evidence from Task 2.
- Produces: fixed-library rows with allowlisted arXiv links, honest current-session run history, desktop rail/mobile dialog variants, and draft persistence across navigation.

- [x] **Step 1: Write failing Library tests.** Assert exactly returned papers render as rows, links open the pinned `https://arxiv.org/pdf/...` URL safely, loading/empty/error states are explicit, and no upload action exists.

- [x] **Step 2: Implement `LibraryPage`.** Keep open list/rail layout rather than card grid.

- [x] **Step 3: Write failing Runs tests.** Assert initial empty copy is honest, a session run exposes source/status/latency/retrieval setting, and no fabricated percentile/limit value appears.

- [x] **Step 4: Implement `RunsPage` from current-session data only.** Label it clearly; persisted experiment runs remain Part 5.

- [x] **Step 5: Write failing responsive behavior tests.** Assert citation surface uses dialog semantics with close/focus behavior, mobile nav remains operable, and draft text survives view/citation changes.

- [x] **Step 6: Implement responsive boundaries.** At 961–1200 px, compact the evidence rail and stack run facts; at 960 px and below, use bottom navigation and a safe-area-aware citation sheet above it; prevent horizontal overflow.

- [x] **Step 7: Run Task 3 tests and build.** Expected: PASS with fixture-only calls.

### Task 4: Same-origin production serving and visual verification

**Files:**
- Modify: `src/relay/api.py`
- Modify: `src/relay/config.py`
- Modify: `tests/test_api_cli.py`
- Modify: `README.md`
- Create: `docs/ui/fidelity-ledger.md`

**Interfaces:**
- Consumes: built `web/dist/index.html` and `web/dist/assets/`.
- Produces: optional same-origin SPA serving without changing `/api/*` behavior; verified desktop/mobile screenshots and run commands.

- [x] **Step 1: Write failing backend tests.** Assert an existing UI directory serves `/` and hashed assets, missing UI keeps API-only behavior, and unknown `/api/*` never falls through to `index.html`.

- [x] **Step 2: Implement optional static serving.** Add `relay_ui_dir: Path = Path("web/dist")`; mount assets only when present; use a GET SPA fallback after API routes; keep TrustedHost and body limits.

- [x] **Step 3: Run Python focused tests and full frontend tests/build.** Expected: PASS without Groq calls.

- [x] **Step 4: Start `uv run relay serve` and verify through Browser/IAB.** Exercise empty Ask, Library, theme persistence, fixture/stand-in answer if available, citation open/close, cancel, and Runs navigation. Do not call real Groq.

- [x] **Step 5: Capture desktop 1440×1000 and mobile 390×844 screenshots.** Inspect both concepts and both implementation captures; compare copy, layout, typography, palette, evidence surface, spacing, icons, focus, and overflow.

- [x] **Step 6: Record and fix the fidelity ledger.** List at least five comparison points, material mismatches fixed, any intentional deviation, and above-the-fold copy diff.

- [x] **Step 7: Run final verification.** `npm test -- --run`, `npm run build`, Python `pytest -q`, Ruff lint/format, and a local health/static smoke. Report exact results; never infer production certification.

## Self-review

- Spec coverage: Ask, Library, Runs, evidence, three themes, responsive navigation/sheet, cancel, loading/refusal/capacity/offline states, safe same-origin deployment, and visual QA are assigned.
- Intentional gap: persistent experiment Runs data and grading UI remain Part 5; this slice labels session-only data and fabricates nothing.
- Type consistency: `Theme`, `SessionRun`, `Answer`, `Hit`, `askQuestion`, and `splitAnswer` have one owner and named consumers.
- Review focus: every listed failure mode has a corresponding test step.
- Proportion: four tasks match Part 4 boundaries; no empty placeholder module or speculative framework is introduced.
