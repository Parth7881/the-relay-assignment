# The Relay UI fidelity ledger

Verified 12 November 2026 against the supplied Power Pages screenshot at
`C:\Users\Dhruv\Downloads\639fb2d079d98b18217af922_Power Pages blog 2.0.png`.
The reference supplies the enterprise visual language only; Relay does not copy
Microsoft branding or site-builder functionality.

## Reference-derived decisions

| Reference signal | Relay implementation |
|---|---|
| Full indigo utility bar | 36 px `#5146C8` identity bar with product and honest local readiness |
| Compact editor rail | 52 px Ask/Library/Runs Fluent icon rail with visible current state |
| Contextual pages panel | 232 px research context, 184 px at intermediate widths |
| Thin command strip | 48 px current-view and Light/Dark/Black control row |
| Calm bordered canvas | Open research workspace with shallow borders and no decorative cards |

## Responsive evidence

- Desktop/reference pair: `artifacts/design-qa/reference-vs-relay-1000x478.png`.
- Header-detail pair: `artifacts/design-qa/reference-vs-relay-header-detail.png`.
- Intermediate: `artifacts/design-qa/relay-intermediate-1024x768.png`.
- Mobile: `artifacts/design-qa/relay-mobile-390x844-valid.png`, captured at an exact
  390 × 844 CSS viewport and device scale factor 1. Viewport/scroll width was 390/390.
- Codex in-app Browser also inspected desktop Light, desktop true Black and mobile
  true Black. Desktop and mobile console logs were empty.

## Behavior and fidelity

- One `GET /health` runs on mount; it is not polled. Malformed/failed checks show
  unavailable and do not invent a ready state.
- The exact three paper versions, current retrieval mode and browser-session scope are
  explicit. No fake usage, quality, recent activity or experiment metrics are shown.
- Evidence remains a 360 px desktop inspector and safe-area-aware mobile sheet.
- Navigation preserves the draft. Theme choice persists. Black uses a real `#000000`
  canvas with `#090909` panels.
- All visible icons use `@fluentui/react-icons`; Lucide is removed.
- The saved `design-qa.md` records the full comparison and `final result: passed`.

## Verification receipts

- Frontend: 8 test files / 31 tests passed.
- Production build: CSS 18.76 kB (4.43 kB gzip), JS 254.65 kB (79.98 kB gzip).
- Production dependency audit: 0 known vulnerabilities at the time checked.
- No Groq call was made for implementation, tests, screenshots or design QA.

## Intentional deviations

- Relay uses the reference's structural language, not its Microsoft marks, company
  navigation, website-editor controls or component palette.
- Mobile removes the context panel and current-view command label; it keeps a compact
  brand bar, accessible theme controls, visible readiness and bottom navigation.
- Visual QA did not fabricate a successful answer. Evidence, refusal, failure and
  cancellation surfaces are verified with deterministic component fixtures.
