# The Relay Enterprise Research Workspace — Design Specification

**Status:** Approved by user 12 November 2026  
**Date:** 12 November 2026  
**Visual target:** `C:\Users\Dhruv\Downloads\639fb2d079d98b18217af922_Power Pages blog 2.0.png`  
**Chosen direction:** Option A — Enterprise Research Workspace

## Intent

Redesign The Relay so it feels like a mature enterprise research tool rather than a
generic AI chat surface. The Power Pages reference supplies the visual language:
compact utility chrome, strong indigo identity, precise dividers, shallow hierarchy,
small purposeful controls and a large calm work canvas. The product must still explain
itself immediately to a first-time user and keep evidence, refusal and capacity states
more important than decorative chrome.

The primary users are assessors, researchers and developers who need to ask questions
against the fixed three-paper library, inspect exact supporting passages and understand
what happened operationally without mistaking synthetic or session-only data for formal
experiment results.

## Goals

- Deliver an original enterprise workspace inspired by the reference, without copying
  Microsoft branding, logos, labels or site-builder functionality.
- Make Ask, Library and Runs readable at a glance through persistent, compact navigation.
- Keep the question, verified answer/refusal and evidence passage as the dominant flow.
- Preserve Light, Dark and true Black themes with consistent hierarchy in all three.
- Retain every existing safety behavior: fixed-paper scope, allowlisted citations,
  cancellation, honest capacity/configuration errors and current-session labeling.
- Remain smooth and usable from 390 px mobile to large desktop screens.

## Non-goals and anti-goals

- No website-editor canvas, component palette, drag-and-drop behavior or fake authoring
  controls from the reference.
- No Microsoft names, logos, Fluent product marks or pixel-for-pixel cloning.
- No marketing hero, gradients, glassmorphism, oversized floating cards, purple AI glow,
  decorative charts, avatars, authentication or fabricated readiness/quality metrics.
- No backend, provider, retrieval, budget or experiment-policy change in this redesign.
- No external webfont request; the interface must remain fast and private locally.

## Approaches considered

### A. Enterprise Research Workspace — selected

Translate the reference's utility bar, icon rail, contextual navigation and calm work
canvas into The Relay's research workflow. This provides the strongest professional
identity while keeping the product task-specific and understandable.

### B. Minimal Relay reskin

Keep the current two-column shell and only change tokens, typography and component
styling. It is lower risk but would not deliver the structural polish the reference
communicates.

### C. Close Power Pages adaptation

Recreate three layers of editor navigation and dense command bars. It would look closest
to the screenshot but creates false affordances and unnecessary cognitive load for a
three-view research assistant.

## Desktop information architecture

The desktop shell uses four purposeful layers, not the reference's editor controls:

1. **Identity bar — 36 px:** full-width enterprise indigo. Left: compact Relay mark and
   “The Relay”. Right: “Fixed research library”, local service state and no account UI.
   Readiness comes from one `GET /health` request on page load; there is no polling.
   A failed or malformed check shows an honest unavailable state and never a fake Ready.
2. **Command bar — 48 px:** begins after the rail/context columns and shows the current
   section title, one-line scope reminder and Light/Dark/Black theme control. It can also
   host the current retrieval label where relevant.
3. **Primary icon rail — 52 px:** Ask, Library and Runs icons with tooltips and visible
   selected state. The selected rail item is indicated by a 3 px indigo edge plus a soft
   tinted background. Icons remain paired with accessible names.
4. **Context panel — 232 px:** title and section-specific supporting information:
   - Ask: “Research library”, readiness label, the three pinned titles and active
     retrieval setting.
   - Library: fixed-corpus explanation and exact version list.
   - Runs: “Current browser session” explanation and observed outcome legend only.

The remaining area is the **workspace canvas**. An optional 360 px evidence inspector
occupies its right edge only after a valid returned citation is selected.

## Ask workspace

- A compact workspace header uses the title “Ask the research library” and one sentence:
  “Answers are released only when the cited passages support them.”
- Before submission, the large central canvas stays intentionally quiet. It may show
  three short scope prompts drawn from the pinned papers, but no fake recent questions.
- The submitted question appears as a bordered query band, not a chat bubble.
- Loading is an inline process row with the existing honest copy and no percentage.
- Verified answers use 16–18 px text at a maximum 70 character measure. Verification and
  retrieval metadata sit in a compact status strip above the answer.
- Citation controls look like enterprise reference chips: square 4 px corners, thin
  indigo border, document icon, short paper label and page.
- Refusal and operational states are open message bands with a status icon and border,
  never success cards or assistant bubbles.
- The composer remains at the bottom of the reading column, with a restrained border,
  character count and one primary indigo action. Cancel replaces submit while pending.

## Evidence inspector

- Desktop: 360 px right inspector with header, close control, paper/title/page metadata,
  exact passage, evidence ID and allowlisted arXiv action.
- The passage is rendered as normal selectable text with a 3 px indigo rule. No invented
  highlighting is applied unless the backend provides a real supported span.
- Opening moves focus to Close; closing or Escape returns focus to the originating
  citation.
- Mobile: bottom sheet starts above the bottom navigation and temporarily hides the
  composer. Safe-area padding and the existing height constraint remain.

## Library workspace

- Maintain an open list rather than cards.
- Each paper row has a small document icon, exact title, arXiv version, “Pinned” status
  and allowlisted PDF action.
- A narrow top status band explains that uploads are intentionally disabled and only
  exact versions are valid evidence.
- Loading, empty and API-error states remain explicit and do not expose raw server data.

## Runs workspace

- Keep the heading “Current session runs” and the explicit statement that this is not
  the formal experiment report.
- Rows remain factual: question, time, source, outcome, total latency and retrieval
  setting. No aggregate percentiles, provider ceilings or quality claims.
- Answered uses green, refused uses neutral/amber, and rate-limited/unavailable uses the
  danger token. Status icons must match their semantic meaning.

## Visual system

### Typography

- `"Segoe UI Variable", "Segoe UI", Inter, ui-sans-serif, sans-serif`.
- UI labels: 12–13 px, 600 weight.
- Body/answer: 16 px minimum, 1.55–1.65 line height.
- Workspace heading: 24–32 px depending on viewport, 650–700 weight.
- Use sentence case. Avoid all caps except 11 px metadata eyebrows.

### Color tokens

| Token | Light | Dark | Black |
|---|---|---|---|
| Identity | `#5146C8` | `#5146C8` | `#5146C8` |
| Canvas | `#FFFFFF` | `#161616` | `#000000` |
| Panel | `#F7F7F8` | `#202020` | `#090909` |
| Raised | `#FFFFFF` | `#252525` | `#0D0D0D` |
| Text | `#242424` | `#F5F5F5` | `#F5F5F5` |
| Muted | `#616161` | `#B3B3B3` | `#AFAFAF` |
| Border | `#E1E1E1` | `#3B3B3B` | `#292929` |
| Accent | `#5146C8` | `#A9A2FF` | `#B5AFFF` |
| Accent soft | `#EEEFFD` | `#29264A` | `#17152D` |

Success, warning and danger retain accessible semantic colors and are never replaced by
the identity purple. Focus uses a 2 px high-contrast ring.

### Shape, spacing and elevation

- Use a 4 px micro-grid and 8 px main rhythm.
- Most controls use 4 px radius; panels use 0–6 px. Pills are reserved for statuses.
- Borders establish hierarchy; shadows appear only beneath mobile sheets or transient
  overlays. No decorative gradients.
- Desktop touch/click controls are at least 36 px; mobile controls remain at least 44 px.

### Icon system

Use Microsoft Fluent UI System Icons through `@fluentui/react-icons`, selected for their
close visual fit to the reference. Import individual icons only. Do not copy Microsoft
product logos or use text glyphs/emoji as icons. The existing Relay layer mark may remain
as an original generic product symbol if implemented from the icon library.

## Responsive behavior

- **≥ 1201 px:** identity bar, 52 px rail, 232 px context panel, fluid workspace and
  conditional 360 px inspector.
- **961–1200 px:** keep the icon rail; collapse the context panel to a compact 184 px
  variant and the inspector to 320 px. Runs facts stack without clipping.
- **≤ 960 px:** remove the context panel and desktop command bar, retain a compact 60–64
  px branded header, and use the existing three-item bottom navigation.
- **≤ 600 px:** use 20–24 px horizontal workspace padding, icon-only theme controls with
  accessible names and a full-width composer. No horizontal overflow at 390 px.

Navigation changes never erase the question draft. Current-session runs remain in App
state. Evidence close and mobile navigation must not overlap.

## State and accessibility requirements

- Preserve keyboard order, semantic headings, navigation labels, live loading status,
  alerts and dialog semantics.
- Theme choice persists and the no-flash initializer remains.
- Support 200% text zoom, reduced motion and visible focus in all themes.
- Do not rely on color alone for selection or operational status.
- Runtime API validation and allowlisted paper/PDF behavior stay unchanged.
- Every control shown in the core Ask → citation → Runs journey remains functional.

## Implementation boundaries

- Restructure the existing React shell and CSS; reuse the tested Ask, Library and Runs
  behavior rather than replacing application logic.
- Add only purposeful presentational components if App becomes difficult to read.
- Replace Lucide with Fluent icons only where the redesigned chrome/components use them;
  remove the unused icon dependency only after the migration is complete.
- Do not modify FastAPI, retrieval, policy, provider, traces or experiment artifacts.
- Frontend tests continue to use deterministic fixtures and must make zero Groq calls.

## Verification and acceptance

- Existing 23 frontend tests remain green; add focused tests only for newly introduced
  shell behavior or accessibility contracts.
- `npm run build` passes with no TypeScript errors and no material unexplained bundle
  regression.
- Verify through the Codex in-app browser at 1440 × 1000, 1024 × 768 and 390 × 844.
- Exercise all three views, all three themes, draft preservation, loading/refusal/error,
  evidence open/close and current-session Runs using fixtures or the stand-in only.
- Compare implementation and reference at equivalent desktop viewport. Design QA must
  confirm hierarchy, density, color, borders, typography, spacing, icon consistency,
  focus and overflow. P0/P1/P2 differences must be fixed before handoff.
- No real provider call is permitted for this redesign or its verification.

## Builder discretion

- Exact tooltip implementation, transition duration below 180 ms, and the small-screen
  placement of nonessential scope metadata may be chosen during implementation as long
  as accessibility and the hierarchy above are preserved.
- The unavailable AVIF reference is not required for this direction; if it contains a
  materially different visual target, the user can supply a PNG/JPG before coding.
