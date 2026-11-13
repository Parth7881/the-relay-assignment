# The Relay

Parts 1–5 engineering: a local Python research-paper assistant with pinned PDF
ingestion, three retrieval configurations, bounded evidence expansion, Groq
drafting/verification, persistent budgets, a calibrated streaming stand-in, and a
responsive React interface. The five formal stand-in traffic experiments are retained;
human answer grading is approved and the final two-page write-up is rendered under
`output/pdf/`.

Final submission artifacts:

- `output/pdf/the-relay-assignment-writeup.pdf`: visually verified two-page report.
- `runs/formal-submission/results.csv`: 106 request rows with mandatory columns first.
- `runs/formal-submission/tables.{json,md}`: CSV-derived reproducible tables.
- `docs/assistant-use-account.md`: authentic key-prompt/decision index; the original
  Codex chat remains the canonical full conversation.

## Quick start — Windows PowerShell

Run from this repository folder. Python 3.12 and `uv` are required.

```powershell
uv sync --locked
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Open `.env` locally and set `GROQ_API_KEY` to your own Groq free-account key.
Never paste it into chat, put it in a command argument, or commit it.
`.env`, downloaded data and run artifacts are ignored by Git.

```powershell
uv run relay doctor
uv run relay ingest
uv run relay retrieve "How does scaled dot-product attention work?"
```

`doctor` reports only whether a key is present. `ingest` downloads the exact
three PDFs, checks their printed arXiv version identifiers, and creates:

- `data/papers/*.pdf`: pinned originals, retained for citation verification.
- `data/manifest.json`: URLs, versions, SHA256 hashes, download times, extraction
  and chunk settings, page counts and index hashes.
- `data/pages.jsonl`: extracted text preserving PDF page numbers.
- `data/chunks.jsonl`: stable source IDs and exact character spans into page text.

Existing cached PDFs are reused and checked against recorded hashes. The
manifest is written last; a partially updated index fails its integrity check.
Never edit derived chunks manually. Re-run ingestion after extraction changes.

The installed corpus currently contains 120 pages and 435 chunks. This is an
inventory count, not an extraction-quality or answer-quality score.

## Three retrieval settings

Build the advanced local index once (network is used only to fetch pinned open-source
models; later searches use cached snapshots):

```powershell
uv run relay index
uv run relay retrieve "How does multi-head attention use different representation subspaces?" --setting hybrid-minilm220-rrf-rerank-k4-v1
uv run relay eval-retrieval
```

| Setting | Frozen behavior |
|---|---|
| `lexical-word180-k4-v1` | 180-word/30-overlap chunks; BM25 top 4 |
| `hybrid-minilm220-rrf-k4-v1` | 220-token/40-overlap chunks; BM25 + dense cosine, reciprocal-rank fusion |
| `hybrid-minilm220-rrf-rerank-k4-v1` | Fused top 12, local CrossEncoder rerank, deduplicated top 4 |

The advanced index has 559 exact page spans and 384-dimensional vectors. It pins
`sentence-transformers/all-MiniLM-L6-v2` at revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41` and
`cross-encoder/ms-marco-MiniLM-L6-v2` at
`233902d25c440f23af6f7d6e94d2946bac0bee0a`; both model cards declare Apache-2.0.
The MiniLM 256-token limit is enforced before inference. Index files are hash-checked,
NumPy loads with pickles disabled, and cached search never contacts Hugging Face.
The nominal 220-token windows use original page tokenization; 9/559 extracted
substrings re-tokenize to 221 tokens alone, still safely below the 256-token limit.

The pipeline may perform one additional retrieval after empty evidence, a model
refusal, invalid citations or verifier rejection. The second pass expands top-k from
4 to 6 (and hybrid candidates from 12 to 24); total draft/verify cycles stay capped
at two. Every model call still passes the same budget/retry gateway, and no draft is
released without deterministic citation checks plus semantic verification.

`docs/evaluation-questions.json` contains 18 assistant-draft questions: 15 marked
answerable and 3 deliberate unanswerables. The user reviewed the set and approved it
on 12 November 2026, so its status is `approved_by_user`; approval does not relabel
the questions as user-authored. `eval-retrieval` makes no hosted calls and saves every
ranked passage to `runs/retrieval-evaluation.json` for review.

Run the end-to-end comparison in small, resumable batches:

```powershell
uv run relay eval-quality --max-new 3
```

This schedules question/configuration pairs in a stable order and atomically updates
`runs/quality-evaluation.json` after every provider outcome. A verified answer or
evidence refusal completes a case. Rate limits, timeouts and service errors are kept
as separate attempts but remain eligible on the next run. Answers, cited evidence and
preliminary labels are preserved; `answer_grade` and `grading_rationale` stay null
until explicit human review. Therefore the artifact cannot yet support a quality
claim. The default batch is three new provider outcomes to reduce accidental free-tier
consumption; use the local budget counters and observed headers before increasing it.
The offline evaluator uses a recorded 120-second whole-case deadline and may wait within
one minute-reset window for calculated capacity between stages, with at most two
boundary recalculations. Interactive Ask keeps its 30-second deadline and fails fast
instead of holding a person through a reset.

Current real quality collection checkpoint (12 November 2026): 48 preserved evaluation
records contain 42 completed answer/refusal cases across 14 questions, with every one
of those questions run against all three retrieval settings. The 42 completed cases
contain 22 answers and 20 evidence refusals. Five minute-budget outcomes and one
daily-budget outcome are preserved separately; all six remain ungraded operational
attempts. Every record resolves to a raw request trace, and all 48 `answer_grade`
fields remain null. These are outcome counts, not correctness scores.

The configured rolling local day ledger stopped the next case at 192,038/200,000
tokens before any provider call. This leaves the assignment's minimum 15-question
quality comparison incomplete by one question. Do not raise or erase the ledger to
hide that result. Based on stored charge timestamps, 1,522 tokens expire from the
rolling window at 13 November 2026 15:10:04 IST and 5,758 by 15:40:29 IST. Resume with
`uv run relay eval-quality --max-new 1`; the incomplete fifteenth question is selected
automatically. Recheck the ledger rather than treating these timestamps as a Groq
provider reset promise—the local policy is not Groq's undocumented reset algorithm.

Current candidate-only retrieval screening (warm local run, n=18 per setting):

| Setting | All expected papers in top 4 | Median retrieval | Median context characters |
|---|---:|---:|---:|
| Lexical | 100.0% | 1.96 ms | 4,377.5 |
| Hybrid | 93.3% | 13.09 ms | 3,571.5 |
| Hybrid + rerank | 93.3% | 324.07 ms | 3,807.5 |

This is coarse paper-level recall on assistant labels, not passage recall, answer
correctness or a final quality result. It revealed one multi-paper miss: hybrid and
reranked top 4 returned only H-Net passages for the Moshi/H-Net synthesis question,
while lexical returned both papers. Other observed top-rank failures include the
reranker preferring a generic self-attention passage over positional encoding, and
all settings returning superficially related passages for unanswerable cost/RAG
chunk-size questions. These are retrieval examples; the refusal gate still needs
the reviewed end-to-end quality run.

## Ask with Groq

```powershell
uv run relay ask "What does the Transformer use instead of recurrence?"
```

This can make **up to six real Groq attempts**: at most two draft/verify cycles,
plus no more than two retries across the complete user request, subject to the
budget and deadline. It sends the question and selected public-paper passages,
plus instructions; the verifier also receives the generated draft it must check.
It does not access web search or another
hosted model provider. Default model is a candidate, `openai/gpt-oss-20b`;
account access and the draft/verify path have passed the smoke checks below.
Broader model quality remains unmeasured.

The tool prints JSON with the answer/refusal, citations, evidence and token usage
when supplied by Groq. A cited claim is released only after its IDs and exact
quoted spans validate and the separate verifier accepts its support/relevance.
Verification is fallible; these checks do not prove factual correctness.

Each request stores `runs/<request_id>.json`, retaining question, evidence,
model prompts/responses, stage timings, model-call usage and allowlisted rate-limit
headers. Authorization headers are never stored. Groq-key patterns are redacted.
Treat run files as private until reviewed: they include the user's question.

Transport failures are `error`, `rate_limited` or `timeout`, not “correct refusals.”
No automatic quality grades are assigned. Unknown token usage stays null.
Provider first-content timings are recorded per model attempt. `first_token_ms`
at the end-to-end level stays null until measured by the client/load harness;
`answer_ready_ms` is explicitly server-side readiness, not user-visible TTFT.
No benchmark CSV or fabricated result tables are generated by this phase.

## Local API

Build the local interface once, then start the Python service:

```powershell
Set-Location web
npm install
npm test -- --run
npm run build
Set-Location ..
uv run relay serve
```

Open [The Relay](http://127.0.0.1:8000). The same-origin production build keeps
the Groq key and all provider policy server-side. During frontend development,
run `npm run dev` from `web/`; Vite proxies `/api` and `/health` to the local
service on port 8000. Frontend tests use deterministic fixtures and do not call
Groq. The enterprise research workspace provides Light, Dark and true Black themes,
a compact Fluent icon rail, section-specific research context, a passage citation
inspector (mobile bottom sheet), the exact fixed library and honest current-session
runs. It performs one local `GET /health` on mount and does not poll. Those session
rows are not the formal experiment report.

```powershell
uv run relay serve
```

Open [API docs](http://127.0.0.1:8000/docs). Endpoints:

| Method / path | Purpose |
|---|---|
| `GET /health` | Advanced-corpus/model-source readiness, without a provider call |
| `GET /api/library` | Fixed paper versions and source URLs |
| `POST /api/retrieve` | Evidence-only search; body `{"question":"..."}` |
| `POST /api/ask` | Verified answer/refusal; same request body |

The API binds to localhost: two active requests, eight FIFO waiting slots,
five-second queue wait and a 30-second total deadline including queue time.
Operational failures use the assignment status inside returned Answer JSON;
validation/configuration failures use HTTP 4xx/503. Queue overflow is
`status=rate_limited`, `reason=queue_full`, not an evidence refusal.
The body limit is 16 KiB; disconnects cancel work and release admission.
Use one API process: multiple processes do not share an admission queue.
The REST response is buffered until verification; provider streaming remains
internal. The UI exposes honest pending/cancel/error states without fake progress.

## Provider policies and calibration

```powershell
uv run relay calibrate --requests 12
```

This makes real calls: 4–20 samples, two prompt lengths, concurrency one then two,
output cap 128. Calibration has no retries and stops on a rate limit or HTTP
configuration error (an already in-flight parallel call may finish). Raw attempts
are saved before the derived `runs/calibration-profile.json` is written.

`runs/budget-real.sqlite3` persists attempts, reservations, lower observed ceilings
and cooldowns. Stand-in accounting uses a separate ledger. Local defaults:
30 RPM / 8,000 TPM / 1,000 RPD / 200,000 TPD. These are protective settings based
on documentation, not experimentally reached account boundaries. Lower observed
RPD/TPM caps are retained; higher headers do not silently raise configured limits.

- Local windows are rolling 60 s and 24 h, not a replica of Groq's reset algorithm.
- Daily draft + verifier allowance is reserved before drafting. Minute allowance
  is checked per attempt; verification can still be blocked, withholding the draft.
  Unused holds are released; crashed holds count until expiry. Prior Part 1 calls
  were imported into this workspace's ledger with original timestamps and usage.
- Input reservation uses UTF-8 byte length / 3 plus message overhead, plus maximum
  output. This heuristic is not a tokenizer upper bound. Known usage replaces the
  estimate; unknown usage retains it and exported token usage stays null. Activity
  outside this app is not locally accounted for.
- Retry only 429, selected 5xx, transport failures and timeouts. Honor Retry-After
  (seconds or HTTP date), otherwise exponential delay+jitter. The request deadline
  bounds sleep too. Authentication, validation and daily exhaustion never retry.
  A daily provider error creates a conservative 24 h cooldown. Retries need new quota.
- Retrieval timeout 3 s, connect/pool 3 s, stream inactivity 10 s. Traces retain planned
  retry delay and actual wait, all attempts, queue depth/wait/outcome and policies.
  Zero-call rejections report zero tokens; missing usage after an attempt is unknown.

On 12 November 2026, calibration recorded **12/12 successful real calls**, 4,284 input /
324 output tokens, zero retries. Median provider first-content 483.92 ms, total 485.80 ms.
Returned model: `openai/gpt-oss-20b`. These are echo prompts, not RAG latency or quality.

| Concurrency | Input group | n | Median first content (ms) | Median total (ms) |
|---:|---|---:|---:|---:|
| 1 | short | 3 | 502.31 | 504.20 |
| 1 | long | 3 | 591.15 | 592.72 |
| 2 | short | 3 | 248.64 | 283.60 |
| 2 | long | 3 | 398.72 | 400.37 |

These cells are too small and order-confounded to claim concurrency improves latency.
`calibration_profile()` regenerates them from
`runs/calibration-8fadd30233cd4bf49e305085b7217c96.json`.

Successful headers advertised **1,000 RPD** and **8,000 TPM**. [Groq's documentation](https://console.groq.com/docs/rate-limits)
defines request headers as daily, token headers as per minute. Last sample reported
remaining requests 988 and tokens 5045. Real RPM/TPD boundaries, 429, saturation, daily
exhaustion and recovery time were **not measured**. Reset strings remain verbatim.

Authentic failures remain saved: initial 12 HTTP 400 responses in
`calibration-50e60e596b934eca8746473870a529a1.json`; one diagnostic HTTP 400 in
`calibration-fdabd68450354e37a5458eef47851aa4.json` confirmed the prompt lacked the
word JSON required by JSON mode. The prompt and early-stop guard were fixed with
regressions. Those 13 failures are excluded from successful calibration, not deleted.
Part 2 made 25 real attempts; including Part 1, retained evidence contains 28 attempts.

## Streaming stand-in (no hosted calls)

Terminal 1:

```powershell
uv run relay simulate --profile runs/calibration-profile.json
```

Terminal 2:

```powershell
$env:RELAY_SOURCE = 'stand-in'
uv run relay ask "What does the Transformer use instead of recurrence?"
Remove-Item Env:RELAY_SOURCE
```

Default synthetic replies refuse. For plumbing checks with a captured answer,
add `--replay runs/d44ce5b192524734a79392439ab057fd.json` to the server command.
Replay ignores new question meaning and **must never be used for quality grading**.
`source=stand-in` distinguishes evidence. Calibrated replay HTTP smoke
`cb0d98cf0d774c1997d6979e6e89453a` completed draft/verify in 961.85 ms (synthetic).

| `--scenario` | Behavior |
|---|---|
| `normal` | Profile delays, or explicit uncalibrated 600/20 ms defaults |
| `slow` | 15 s first-content delay; omit `--profile` |
| `failure` | Every second request returns 503 |
| `rate-limit` | Every second request returns 429 with 1 s Retry-After |
| `load` | Adds 1,500 ms per other active stream |
| `half-minute` | Server 15 RPM / 4,000 TPM |
| `daily-exhausted` | Server RPD zero; terminal 429 |

`--seed 42` controls profile sampling. Load/failure controls are
injected assumptions. Synthetic usage is byte-based, not model-token measurement.
The stand-in resamples first-content/tail pairs across eight chunks; it does not
fit provider infrastructure or token-rate behavior. Groq keys are never forwarded.
Use fresh **stand-in-only** run folders for independent future scenarios; never
reset the real ledger to evade limits.

## Part 5 traffic harness and formal results

The `load` command now measures one already-running local Relay API at a time. It
uses a fixed open-loop dispatch schedule, so slow responses do not silently reduce
offered traffic. The default source is `stand-in`; a real-source run requires the
explicit `--allow-real` flag and is capped at 12 requests. The target is restricted
to loopback HTTP. A `/health` source preflight stops a mismatched `real`/`stand-in`
server before the first question is sent. The harness never starts a provider or
changes a budget ledger.

Each run creates `runs/experiments/<run_id>/run.json`, `raw.jsonl`, and
`results.csv`. The mandatory assignment columns come first. Supplementary schedule
and run fields follow them. `first_token_ms` is measured by the load client at the
first response-body byte; because `/api/ask` releases only the final verified JSON,
it is user-visible response timing, not internal provider TTFT. `answer_grade` stays
empty until the saved answer and evidence receive explicit human review.

Example stand-in-only burst setup (no Groq use):

```powershell
# Terminal 1: isolated stand-in provider
uv run relay simulate --profile runs/calibration-profile.json --scenario normal --port 8021

# Terminal 2: isolated Relay API and trace directory
$env:RELAY_SOURCE = 'stand-in'
$env:RELAY_SIMULATOR_PORT = '8021'
$env:RELAY_RUNS_DIR = 'runs/stand-in-burst-server'
uv run relay serve --port 8020

# Terminal 3: measured client
uv run relay load --scenario burst --source stand-in --requests 6 `
  --rate-per-minute 30 --base-url http://127.0.0.1:8020 `
  --server-runs-dir runs/stand-in-burst-server

# Reconcile traffic, retained real calibration and quality attempts offline.
uv run relay report --input-root runs/formal-experiments `
  --output-dir runs/formal-submission `
  --calibration runs/calibration-8fadd30233cd4bf49e305085b7217c96.json `
  --quality runs/quality-evaluation.json `
  --grades runs/grading-decisions.json `
  --service-facts runs/groq-service-facts.json
```

For `sustained_overload`, restart the simulator with `--scenario load`; for
`minute_limit_halved`, use `--scenario half-minute`; for
`daily_budget_exhausted`, use `--scenario daily-exhausted`. These are reproduction
commands for the harness; the completed formal matrix is documented below.
The initial two-request stand-in smoke is retained as run
`e14be3495a4b4c7d8752ca168c9da5f0`; it produced two CSV rows and two raw traces.
Its 50% success/50% local-rate-limit outcome is plumbing evidence only, not a formal
benchmark. `runs/submission/tables.md` is regenerated from the CSV and explicitly
marks retrieval quality as pending user grading.

Two open-loop steady pilots were then retained under `runs/pilots/`:

| Run | Offered load | Requests | Success | Rate limited | Peak queue |
|---|---:|---:|---:|---:|---:|
| `b0fe700207a148e19e735bdd2c4c1677` | 4 RPM | 4 | 25.0% | 75.0% | 0 |
| `5444f681093c411e8d6247c4e6d354f7` | 1 RPM | 3 | 66.7% | 33.3% | 0 |

These small pilots show the configured 8,000-TPM rolling window limiting work before
the API queue saturates; they do not establish a production capacity claim.

The approved formal stand-in matrix was executed on isolated ports 8020/8021. The
12-request burst exceeded the API's two active plus eight queued slots, so queue
saturation was measured rather than assumed. All 46 rows retain matching raw client
records and copied server traces under `runs/formal-experiments/`; every row has
`source=stand-in`, the exact mandatory columns first, and a blank `answer_grade`
pending human review.

| Scenario | Run ID | Offered load | Requests | Outcomes | Peak queue | Duration |
|---|---|---:|---:|---|---:|---:|
| steady | `7c3d64d72cda49308a28d41c206b34e1` | 0.75 RPM | 3 | 3 ok | 0 | 162.593 s |
| burst | `ff2e702330d14df7aea3035fd9e24221` | simultaneous | 12 | 1 ok, 11 rate-limited | 8 | 7.423 s |
| sustained overload | `fd25f2674dd0409b80e2154d0c068e18` | 12 RPM | 24 | 2 ok, 22 rate-limited | 0 | 115.663 s |
| minute limit halved | `94cc1b31966a48f399df49e9511a8f95` | 0.75 RPM | 3 | 3 rate-limited | 0 | 161.811 s |
| daily budget exhausted | `36dd7fe7e18b4b8185f90475bff06d26` | simultaneous | 4 | 4 rate-limited | 1 | 2.092 s |

The half-minute traces retain observed simulator headers with
`x-ratelimit-limit-tokens: 4000`; this is stand-in evidence, not a claim about the
Groq account. The overload run's zero API queue means its configured token/provider
controls rejected work before an API backlog formed. Pilot rows remain separate and
are not relabelled as formal results.

The required `runs/formal-submission/results.csv` now contains 106 unique request
rows: 46 formal stand-in load rows, 12 retained real calibration attempts and 48
retained real quality attempts. Its mandatory 12 columns remain first. `record_kind`
and other supplementary columns keep the three populations separable. The 42 completed
quality responses carry approved grades; six operational failures and non-quality rows
remain honestly ungraded. Table figures are regenerated from this CSV.

A supplementary injected-failure probe is retained separately from the formal matrix
under `runs/supplementary-experiments/`. In run
`96388c9072b141e4be8f8c5ee71219d1`, a failed model attempt scheduled a retry and
waited 628.4 ms, but the next attempt was rejected by the stand-in minute budget. The
request therefore became slower without recovering (`total_ms=1393.5`,
`retry_wait_ms=628.4`, `status=rate_limited`). The mandatory `retries` field remains
zero because no second provider attempt actually began; the supplementary trace is
what distinguishes planned/elapsed retry wait from completed retries.

## Checks

Current enterprise UI verification: **8 frontend files / 32 tests passed** and the
Vite production build completed at CSS 4.51 kB gzip and JavaScript 80.02 kB gzip.
The production dependency audit reported zero known vulnerabilities when checked.
Browser verification used only localhost and made zero Groq calls. See
[`design-qa.md`](design-qa.md) and
[`docs/ui/fidelity-ledger.md`](docs/ui/fidelity-ledger.md) for normalized reference,
responsive and interaction evidence. A fresh unrestricted Windows run passed all
**103 Python tests**, including the loopback streaming integration test and the new
Part 5 load/CSV safety contracts. The restricted Codex sandbox can block Python's
internal event-loop socket pair; the same suite passes in a normal VS Code terminal.
A completed standard Codex Security source scan found no reportable vulnerability;
it excluded secrets, generated/runtime data, dependency internals and public deployment.

Part 3 final verification: **70 tests passed in 6.31 s**; Ruff lint and formatting
checks passed. Tests include real loopback HTTP streaming/503 retry and local dense/
rerank behavior; the test suite makes no hosted model calls.

```powershell
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Tests use synthetic model responses at the external HTTP/model boundary and
exercise real retrieval, citation checks, pipeline branches and trace recording.
They do not consume Groq quota and are not answer-quality measurements.
In Codex's restricted Windows sandbox, event-loop socket initialization may hang;
the same tests were run outside that restriction. A normal VS Code terminal can
run the commands above.

## Known limitations and next gates

Part 1 verification: 33 offline tests passed, Ruff checks passed,
and actual localhost HTTP checks returned health 200, library with three entries,
retrieval 200, and missing-key 503. Three rendered PDF pages were spot-checked
(Transformer p4, Moshi p1, Dynamic Chunking p1); this is not an audit of all 120 pages.
The review caught whitespace quotation bypass and malformed-SSE shape handling;
both were reproduced by failing regression tests and fixed before the green suite.

Real smoke checks on 12 November 2026 (local run artifacts are intentionally ignored
by Git; retain them for the final submission):

| Request ID | Outcome | Pipeline time (ms) | Input / output tokens |
|---|---|---:|---:|
| `d44ce5b192524734a79392439ab057fd` | Transformer question: cited answer, draft + verifier | 1358.6 | 2849 / 220 |
| `86f2a9bd5f114a1894bdc2492c839764` | Moshi dollar-cost question: evidence refusal | 584.6 | 1409 / 38 |

These two user requests consumed three successful provider calls with zero retries.
The first answer's citation resolves to Transformer v7, PDF page 2, whose passage
explicitly describes relying on attention instead of recurrence. Draft/verify
provider first-content times were 708.1 / 639.8 ms. These are internal provider
timings; pipeline time excludes CLI startup and is not browser-visible latency.
No general quality score or percentile can be inferred from these smoke checks.
The refusal establishes observed behaviour on retrieved evidence, not exhaustive
proof that no passage anywhere in the library contains the requested fact.

Observed headers on both successful calls of the first request included
`x-ratelimit-limit-requests=1000` and `x-ratelimit-limit-tokens=8000`.
Preserve their raw names/values in the run files. No real 429, daily
exhaustion or concurrency ceiling was observed in these checks.

- The lexical baseline uses word spans; hybrid settings use MiniLM tokenizer spans.
  These configurations jointly change chunking and retrieval technique, so results
  cannot isolate a single causal improvement.
- Extraction uses pypdf plain text. Page identity is checked, but multi-column
  ordering, mathematical notation, repeated headers and table reading remain
  quality risks. No OCR or formula reconstruction is claimed.
- One additional retrieval/draft/verify cycle is implemented; there is no unbounded
  agent loop. The second model pair consumes additional real quota.
- Timeout: 30-second whole-pipeline deadline, 3-second connection timeout,
  10-second stream inactivity timeout. Measurements exist, but no production latency
  service-level target is claimed.
- The question set has explicit user approval. Formal end-to-end answer grades now
  wait for human review of each saved answer/evidence pair. No grading rationales or
  final retrieval quality claims exist yet.
- Part 5 has a guarded loopback load harness, five completed formal stand-in runs,
  reproducible per-run CSV/raw artifacts and reconciled tables. The two-page write-up
  draft waits only for human grades and authentic personal statements. Do not run
  deliberate burst/overload experiments against real Groq.
- Returned model/fingerprint are captured when supplied. No public deployment
  security certification or production scalability claim is made.
- Independent Part 2 source review found no Critical/Important issue. One minor
  is deferred: at tiny output caps, multilingual replay truncation counts characters
  rather than UTF-8 bytes, making synthetic token accounting inaccurate. Truncated
  responses are still rejected. Fix before multilingual truncation experiments.
  A later formal Codex Security source scan completed with no reportable findings;
  dependency advisory status and host ACLs remain outside that review.
- Independent Part 3 review found no Critical issue. Its two Important findings—an
  abandoned verifier hold and event-loop-blocking model load—were reproduced and
  fixed. Deferred minors: stage-specific retrieval errors, standalone 220→221 token
  validation, and index fingerprints in retrieval reports.
- The approved question set, request-ID-bound grading rationale, Vaani feedback and
  assistant-use reflection are retained. Export the original Codex chat as a separate
  attachment if the assessor requires a full transcript rather than the prompt index.

## Provenance

The source was independently implemented. We inspected
[RAG-Document-BeFree](https://github.com/Parth7881/RAG-Document-BeFree/tree/f67c7dd7a00b887b9ad9d3c9fabf675dd5413d38)
for page-aware extraction and citation design ideas. No upstream code was copied;
reuse rights were not established. The detailed design, references, assignment
ambiguities and five-part roadmap are in [the PRD](docs/relay-design.md).

Provider contract references:
[Groq chat API](https://console.groq.com/docs/api-reference),
[Groq limits](https://console.groq.com/docs/rate-limits),
[pypdf extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
