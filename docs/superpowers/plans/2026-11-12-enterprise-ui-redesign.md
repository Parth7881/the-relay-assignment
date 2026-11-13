# The Relay Enterprise UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the existing Relay interface into the approved enterprise research workspace while preserving every tested RAG, citation, failure-state and responsive behavior.

**Architecture:** Keep the existing React state and feature boundaries; add one typed health client and one contextual-shell component around them. `App` owns current view, theme, draft, session runs and the one-shot health state. CSS custom properties implement the approved three-theme visual system, and the existing FastAPI same-origin build remains unchanged.

**Tech Stack:** React 19, TypeScript 7 strict mode, Vite 8, Vitest, Testing Library, plain CSS custom properties, `@fluentui/react-icons` 2.0.341, FastAPI `/health` and existing local stand-in.

**Spec:** `docs/superpowers/specs/2026-11-12-enterprise-ui-redesign-design.md`

## Global Constraints

- Make zero Groq/provider calls during implementation and verification; use deterministic fixtures or the local stand-in only.
- Preserve `GROQ_API_KEY` server-side; never add a `VITE_*` secret or expose raw HTTP/provider detail.
- One `GET /health` request runs on App mount; do not poll, retry automatically or convert readiness into a model call.
- Keep the exact three-paper library and all citation/PDF allowlists unchanged.
- Identity color is `#5146C8`; Light canvas is `#FFFFFF`, Dark `#161616`, Black `#000000`; Black panel is `#090909`.
- Use `"Segoe UI Variable", "Segoe UI", Inter, ui-sans-serif, sans-serif`; no external font request.
- Use borders for hierarchy, 4–6 px radii, 4 px micro-grid/8 px main rhythm and no gradients/glass/AI glow.
- Desktop rail is 52 px, context panel 232 px, identity bar 36 px and command bar 48 px; mobile begins at 960 px.
- Mobile touch targets remain at least 44 px; desktop controls remain at least 36 px.
- Do not change FastAPI, retrieval, provider, policy, budgets, traces or experiment artifacts.
- This repository has no resolvable Git `HEAD`; do not create its first commit without explicit user approval. Record progress without commit steps.

## Review Focus

- A failed, malformed or aborted `/health` response must show “Status unavailable”, not Ready or raw server text; Task 1 tests it.
- `corpus_ready=false` with a configured model must show “Library not ready” independently of model configuration; Task 2 tests it.
- Long paper titles and 200% text zoom must not clip the 961–1200 px layout; Task 3 owns responsive verification.
- Opening/closing evidence must not overlap mobile navigation/composer or lose citation focus; Task 3 retains the interaction regressions.
- Theme persistence, especially explicit Black, must survive the new enterprise chrome without a flash or low-contrast indigo controls; Tasks 2–3 test and visually verify it.

---

### Task 1: Typed one-shot health status and Fluent icon foundation

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/api.test.ts`

**Interfaces:**
- Consumes: same-origin `GET /health` JSON.
- Produces: `HealthStatus`, `HealthState = "checking" | "ready" | "library_not_ready" | "unavailable"`, and `getHealth(signal?: AbortSignal): Promise<HealthStatus>` for Task 2.

- [x] **Step 1: Write failing health-client tests.** Extend `api.test.ts` to assert one `GET /health` request with abort propagation, accepted exact fields (`status`, `phase`, `corpus_ready`, `model_configured`), and rejection of malformed booleans/JSON using the safe `ApiError` message “The Relay returned an invalid health response.”

- [x] **Step 2: Run the focused test.** Run `npm test -- --run src/lib/api.test.ts` from `web/`; expect failure because `getHealth` and its types do not exist.

- [x] **Step 3: Implement the health contract.** Add the exact types to `types.ts`; validate every field in `api.ts`; call relative `/health`; never surface a body detail from this readiness request.

- [x] **Step 4: Pin the approved icon dependency.** Run `npm install --save-exact @fluentui/react-icons@2.0.341`; retain `lucide-react` until Task 3 completes the migration. Confirm the lockfile audit reports no known vulnerability rather than inferring it.

- [x] **Step 5: Verify Task 1.** Run the focused API tests and `npm run build`; expect pass with zero network/model calls from tests.

### Task 2: Enterprise chrome, contextual panel and honest readiness

**Files:**
- Create: `web/src/app/ContextPanel.tsx`
- Modify: `web/src/app/App.tsx`
- Modify: `web/src/app/App.test.tsx`
- Modify: `web/src/app/responsive-behavior.test.tsx`

**Interfaces:**
- Consumes: Task 1 `getHealth`, `HealthStatus`, existing `Theme`, `SessionRun[]` and `ask | library | runs` view state.
- Produces: `AppProps { loadHealth?: typeof getHealth }`, `ContextPanelProps { view: View; healthState: HealthState; runs: SessionRun[] }`, identity bar, command bar, 52 px semantic primary rail and 232 px contextual panel.

- [x] **Step 1: Write failing shell tests.** Assert the app exposes “The Relay” identity, “Fixed research library”, semantic Primary navigation, current command title, and the view-specific context heading (“Research library”, “Pinned corpus”, “Browser session”).

- [x] **Step 2: Write failing readiness tests.** Inject resolved health fixtures and assert `corpus_ready=true` → “Library ready”; `corpus_ready=false` → “Library not ready”; a rejected/malformed client → “Status unavailable”. Assert `loadHealth` is called once across navigation/theme changes.

- [x] **Step 3: Run the focused tests.** Run `npm test -- --run src/app/App.test.tsx src/app/responsive-behavior.test.tsx`; expect failure because the enterprise chrome/context contract is absent.

- [x] **Step 4: Implement `ContextPanel`.** Render only truthful local state and existing fixed-paper/session facts. Do not add counts derived from provider quotas, formal experiment claims, fake recent items or an account avatar.

- [x] **Step 5: Restructure `App`.** Add the one-shot abortable health effect, identity bar, command bar, Fluent primary rail and context panel while preserving App-owned draft/session runs/theme state. Use accessible `aria-current`, `aria-pressed`, headings and hidden tooltip labels.

- [x] **Step 6: Verify Task 2.** Focused shell/readiness tests pass, including draft persistence and Black-theme storage.

### Task 3: Enterprise visual system and feature-surface migration

**Files:**
- Modify: `web/src/styles.css`
- Modify: `web/src/features/ask/AskPage.tsx`
- Modify: `web/src/features/ask/EvidencePanel.tsx`
- Modify: `web/src/features/library/LibraryPage.tsx`
- Modify: `web/src/features/runs/RunsPage.tsx`
- Modify: `web/src/features/ask/AskPage.test.tsx`
- Modify: `web/src/features/library/LibraryPage.test.tsx`
- Modify: `web/src/features/runs/RunsPage.test.tsx`
- Modify: `web/package.json`
- Modify: `web/package-lock.json`

**Interfaces:**
- Consumes: Task 2 shell classes/data attributes and all existing feature props.
- Produces: approved Light/Dark/Black tokens, responsive grid at ≥1201/961–1200/≤960 px, Fluent icons throughout the visible application, and unchanged functional feature contracts.

- [x] **Step 1: Add failing regression assertions for the redesigned surfaces.** Preserve existing behavior assertions and add semantic labels for the workspace title, fixed pinned state, outcome-specific Runs icons and evidence inspector controls. Do not assert raw CSS class names except where no semantic behavior exists.

- [x] **Step 2: Run feature tests.** Run Ask, Library and Runs test files; expect only the new enterprise-label/icon assertions to fail.

- [x] **Step 3: Replace visible feature icons with direct Fluent imports.** Use regular icons for navigation/actions and filled variants only for selected/current state where useful. Keep `aria-hidden` on decorative SVGs and accessible names on controls.

- [x] **Step 4: Implement exact theme tokens and typography.** Replace the current blue system with the approved `#5146C8` identity/accent family, Segoe stack, 4–6 px geometry and restrained borders. Keep semantic success/warning/danger separate from purple.

- [x] **Step 5: Implement desktop and intermediate layouts.** At ≥1201 px render 52/232/fluid/optional-360 columns; at 961–1200 px use the compact 184 px context and 320 px evidence rail. Stack Runs facts before they clip and keep 70ch answer measure.

- [x] **Step 6: Implement mobile layout.** At ≤960 px hide the contextual panel/desktop command bar, use compact brand header plus bottom navigation, keep 44 px targets, anchor evidence above navigation and hide the composer while the sheet is open. Verify 390 px has no horizontal overflow.

- [x] **Step 7: Remove unused Lucide dependency.** After `rg -n "lucide-react" web/src` returns no imports, run `npm uninstall lucide-react`; verify lockfile/audit output and build.

- [x] **Step 8: Verify Task 3.** Run `npm test -- --run` and `npm run build`; expect all frontend tests green and no TypeScript error. Record actual bundle sizes rather than claiming an improvement.

### Task 4: Reference comparison, design QA and handoff evidence

**Files:**
- Create: `design-qa.md`
- Modify: `docs/ui/fidelity-ledger.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-11-12-enterprise-ui-redesign.md`

**Interfaces:**
- Consumes: built `web/dist`, approved reference screenshot, the implementation from Tasks 1–3 and existing same-origin local service.
- Produces: verified browser state, a passing `design-qa.md`, updated review commands and an honest visual-fidelity record.

- [x] **Step 1: Build and start locally without Groq.** Use the existing FastAPI static server; use deterministic fixtures or the local stand-in only if a populated result state is required.

- [x] **Step 2: Verify through Codex in-app Browser.** At 1440 × 1000 exercise Light enterprise chrome, navigation, live health state, Library, draft persistence, error/refusal and Runs. At 1024 × 768 confirm compact context/evidence behavior. At 390 × 844 verify Black, bottom navigation, composer and no overflow.

- [x] **Step 3: Capture equivalent reference/implementation states.** Compare the provided Power Pages screenshot and Relay desktop implementation at matched proportions; compare current mobile implementation against the approved mobile behaviors rather than inventing a Power Pages mobile clone.

- [x] **Step 4: Run the blocking design-QA workflow.** Create `design-qa.md` covering hierarchy, density, typography, color, borders, icon consistency, spacing, focus, loading/error states and overflow. Fix every P0/P1/P2 and repeat capture/comparison until `final result: passed`; retain P3 notes without endless polish loops.

- [x] **Step 5: Update fidelity and setup documentation.** Record the reference-derived decisions, intentional deviations, viewport/console evidence, health behavior, exact test totals, build sizes and zero-Groq statement.

- [x] **Step 6: Run final verification.** `npm test -- --run`, `npm run build`, dependency audit, source scan for `dangerouslySetInnerHTML`, `VITE_*KEY`, `GROQ_API_KEY` exposure and remaining Lucide imports, plus localhost `/health` and static-root smoke. Report exact outcomes; do not call this a production security certification.

## Self-review

- **Spec coverage:** Enterprise chrome, contextual information, Ask/Evidence/Library/Runs, exact tokens, Fluent icons, one-shot health, three themes, responsive breakpoints, accessibility, operational honesty and visual QA each have an owning task.
- **Step scan:** Each step performs one test, implementation or verification action; dependency removal occurs only after source migration.
- **Type consistency:** `HealthStatus`, `HealthState`, `getHealth`, `AppProps` and `ContextPanelProps` have one named owner and explicit consumers.
- **Review focus:** malformed health, corpus-not-ready, intermediate overflow, evidence focus/overlap and Black persistence have test or browser coverage in their owning tasks.
- **Proportion:** Four tasks match one frontend redesign; no backend or experiment work is mixed into the plan.
