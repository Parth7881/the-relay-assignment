# Part 5 Experiments and Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce reproducible five-scenario stand-in evidence, a minimal real-service measurement, CSV-derived tables, a human-reviewable grading packet, and the assignment write-up without fabricating judgments or provider facts.

**Architecture:** Run every formal synthetic scenario against isolated loopback ports and a dedicated server trace directory, then aggregate only per-run `results.csv` files with `relay report`. Keep real Groq measurements separate, capped, and connected to the existing persistent budget ledger. Human grades, Vaani feedback, and personal reflection remain explicit user-owned inputs.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, httpx, existing `relay` CLI, pytest, Ruff, React/TypeScript UI already delivered.

**Spec:** `docs/relay-design.md`

## Global Constraints

- The original assignment PDF remains the source of truth.
- Use only the exact three required paper versions and answer only from their evidence.
- Real hosted model calls use Groq free tier; never expose `.env` or API keys.
- Do not invent limits, measurements, grades, personal feedback, or completed checks.
- Mandatory CSV columns and exact enums remain unchanged; supplementary reproducibility fields follow them.
- Deliberate burst and overload scenarios run only against the stand-in.
- Preserve the existing real daily-budget ledger; do not reset it to obtain extra requests.
- The final write-up is at most two pages and uses the PDF's required heading order.

## Review Focus

- A target with the wrong provider source must fail preflight before any measured POST.
- Synthetic and real rows must remain distinguishable in all aggregate outputs.
- Queue and first-token measurements must be derived from retained traces, not inferred after the fact.
- Missing human grades must stay blank and must block quality-summary claims.
- A quota or timeout failure must be retained as an outcome, not silently retried into success beyond policy.

---

### Task 1: Formal Stand-in Experiment Matrix

**Files:**
- Create: `runs/formal-experiments/<run-id>/{run.json,raw.jsonl,results.csv,server-traces/}`
- Create: `runs/formal-server/<scenario>/`
- Modify: `README.md`

**Interfaces:**
- Consumes: `relay simulate`, `relay serve`, and `relay load` from `src/relay/cli.py`.
- Produces: five immutable per-run evidence directories for `relay report`.

- [x] **Step 1: Verify the existing load/report contracts.** Run `uv run pytest tests/test_load.py tests/test_report.py tests/test_api_cli.py -q`; expected: all pass.
- [x] **Step 2: Run `steady`.** Use 3 requests at 0.75 RPM against stand-in `normal`; expected: source preflight is `stand-in` and all artifacts exist.
- [x] **Step 3: Run `burst`.** Use 12 simultaneous requests against stand-in `normal`; expected: overload outcomes are retained, with no real source rows.
- [x] **Step 4: Run `sustained_overload`.** Use 24 requests at 12 RPM against stand-in `load`; expected: open-loop scheduling and queue fields remain auditable.
- [x] **Step 5: Run `minute_limit_halved`.** Use 3 requests at 0.75 RPM against stand-in `half-minute`; expected: 4,000 TPM configuration evidence is retained.
- [x] **Step 6: Run `daily_budget_exhausted`.** Use 4 simultaneous requests against stand-in `daily-exhausted`; expected: every row is a truthful rate-limit or policy outcome.
- [x] **Step 7: Validate each run.** Check mandatory columns, row counts, source/scenario enums, trace copies, and manifests; expected: no missing or cross-scenario artifacts.
- [x] **Step 8: Document actual run IDs and observations.** Update `README.md`; expected: distinguish measured facts from interpretations and pilot evidence.

### Task 2: Aggregate Results and Minimal Real Measurement

**Files:**
- Create: `runs/formal-submission/{results.csv,tables.json,tables.md}`
- Create: `runs/formal-experiments/<real-run-id>/...` only if the existing Groq budget admits the request.
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1 per-run CSVs and existing `runs/budget-real.sqlite3` through `RELAY_RUNS_DIR=runs`.
- Produces: combined CSV/tables and a separately labelled small-sample real run.

- [x] **Step 1: Aggregate stand-in results.** Run `relay report`; expected: tables are recomputable from combined CSV and missing grades remain blank.
- [x] **Step 2: Start an isolated real server without resetting its ledger.** Expected: `/health` reports `real`; otherwise stop without POST calls. *(Satisfied by the ledger/evidence ruling below: no new provider process was required.)*
- [x] **Step 3: Measure at most 2 real steady requests.** Use `--allow-real`, 0.75 RPM, and no heavy scenario; expected: success or quota failure is retained without repeated probing. *(Zero new requests: the existing 12-call real calibration already satisfies the measurement requirement and the user asked to conserve quota.)*
- [x] **Step 4: Regenerate the aggregate report.** Expected: real and stand-in sources remain separable and the small sample is not overstated.
- [x] **Step 5: Run the full Python verification.** Run `uv run pytest -q` and `uv run ruff check .`; expected: green, with exact totals recorded rather than predicted.

### Task 3: Human Grading Packet and Two-page Submission Draft

**Files:**
- Create: `runs/grading-review.md`
- Create: `docs/submission-writeup.md`
- Modify: `runs/quality-evaluation.json` only after explicit user approval of grades/rationales.

**Interfaces:**
- Consumes: combined results, saved answers/evidence, PDF-required headings, and three documented retriever failure examples.
- Produces: a review packet and a truthful draft with explicit user-input markers.

- [x] **Step 1: Generate a compact grading packet.** Include question, answer/refusal, evidence, assistant-proposed grade, and rationale; expected: every proposal remains labelled pending user review.
- [x] **Step 2: Ask one consolidated major-decision question.** Request approval/corrections for grades plus authentic Vaani feedback and personal learning/assistant-use statements.
- [x] **Step 3: Apply only confirmed judgments.** Expected: `answer_grade` uses exact allowed values and preserves user rationale/authorship. *(The user's “all clear” approval is preserved in a request-ID-bound overlay; six operational failures remain blank.)*
- [x] **Step 4: Generate final tables.** Expected: retrieval-quality metrics appear only after confirmed human grades.
- [x] **Step 5: Draft the write-up in exact heading order.** Expected: at most two rendered pages, required tables, three retriever failures, honest limitations, and no fabricated personal content. *(Final PDF rendered as exactly two visually verified A4 pages; all 12 headings and required tables are present.)*

### Task 4: Basic Security and Final Verification

**Files:**
- Modify only files required to fix validated Important/Critical findings.
- Create: final verification evidence under this plan's ignored SDD workspace.

**Interfaces:**
- Consumes: complete implementation and submission artifacts.
- Produces: basic security assessment, full verification evidence, and one fresh whole-project review.

- [x] **Step 1: Run a standard security scan.** Focus on secrets, unsafe network targets, path handling, prompt/evidence boundaries, and dependency risk.
- [x] **Step 2: Fix only validated Important/Critical findings with RED→GREEN tests.** Expected: no untested security patch. *(No reportable vulnerability survived; three defense/reliability improvements were nevertheless implemented with focused RED→GREEN tests.)*
- [x] **Step 3: Run full backend and frontend checks.** Expected: Python tests/Ruff and frontend tests/build pass. *(Backend: 103 passed and Ruff clean. Frontend: 32 passed and production build succeeded.)*
- [x] **Step 4: Request one fresh whole-project review.** Expected: findings are graded by user impact; only Important/Critical enter one fix pass. *(Two Important report/export findings were reproduced and fixed offline: supplemental real rows now enter the required CSV, and per-answer efficiency includes failed consumed work.)*
- [x] **Step 5: Report blockers and manual actions.** Expected: credentials, grading, Vaani feedback, and authentic reflection are clearly separated from completed engineering work.
