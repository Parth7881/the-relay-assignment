# The Relay - assignment write-up

## 1. What I built and why.

I built a Python pipeline that interprets a question, retrieves page-preserving passages,
drafts with Groq, and verifies every claim/citation before release. One bounded expansion
loop can retrieve more evidence; otherwise it refuses. The shaping decision was to withhold
an unsupported draft even when that increases latency or rejection rate. Fast wrong answers
were treated as worse than explicit unavailability.

## 2. The real service and my stand-in.

Twelve real `openai/gpt-oss-20b` calibration calls all succeeded: median provider first
content was 483.9 ms and total was 485.8 ms (4,284 input and 324 output tokens, zero
retries). Response headers showed 1,000 RPD and 8,000 TPM. Current official Groq
documentation lists 30 RPM and 200,000 TPD for this model and says a limit returns HTTP
429 with `Retry-After`; I did not force a real 429. The stand-in samples the 12 measured
first-content/tail timings, streams chunks, injects slow/failure/429 behavior, caps RPM/TPM/
RPD/TPD, and adds latency with active load. It is least realistic in reset behavior and
failure correlation: its rolling windows and injections are controlled assumptions, not
Groq's scheduler.

### Table 1. Limits found in the real service

| Limit | Value found | How found | Confidence |
|---|---|---|---|
| Requests/min | 30 | Current Groq model table; not stress-tested | medium |
| Tokens/min | 8,000 | Real response headers and current docs | high |
| Requests/day | 1,000 | Real response headers and current docs | high |
| Tokens/day | 200,000 | Current Groq model table; not exhausted at provider | medium |
| Requests in flight | at least 2; maximum not measured | Three real samples at concurrency 2 succeeded | low |
| Limit response | not measured; docs specify HTTP 429 + `Retry-After` | Official error/rate-limit docs | low |
| Recovery time | not measured | Real limit was not deliberately reached | low |

## 3. Results.

The five formal load runs used the calibrated stand-in and 46 retained request rows.
Percentiles use linear interpolation. A non-obvious result was that a 12-request burst
filled the eight-slot queue but sustained 12 RPM did not queue: protective token/provider
controls rejected work first. Real calibration figures above are separate from end-to-end
RAG load results. Quality has 42 completed responses across 14 fully covered questions;
the fifteenth was attempted but blocked by the honest daily-budget outcome. The quality
percentages below use approved judgments; six capacity failures remain ungraded.

### Table 2a. Latency by load scenario

| Scenario | Source | n | Duration s | Offered/min | First byte p50/p95/p99 ms | Total p50/p95/p99 ms |
|---|---|---:|---:|---:|---|---|
| steady | stand-in | 3 | 162.593 | 0.75 | 2574.6 / 2740.4 / 2755.1 | 2576.0 / 2741.7 / 2756.4 |
| burst | stand-in | 12 | 7.423 | simultaneous | 6046.4 / 7384.5 / 7403.4 | 6048.4 / 7387.0 / 7405.3 |
| sustained overload | stand-in | 24 | 115.663 | 12.0 | 655.7 / 2566.3 / 3036.4 | 657.2 / 2567.8 / 3037.8 |
| minute limit halved | stand-in | 3 | 161.811 | 0.75 | 1799.1 / 1966.4 / 1981.3 | 1800.5 / 1967.7 / 1982.5 |
| daily budget exhausted | stand-in | 4 | 2.092 | simultaneous | 1824.4 / 2084.4 / 2085.3 | 1826.5 / 2085.8 / 2086.7 |

### Table 2b. Outcomes by load scenario

| Scenario | Success % | Limited % | Timeout/gave up % | Retries/request | Peak queue | Tokens/answer | Cost/1,000 answers |
|---|---:|---:|---:|---:|---:|---|---|
| steady | 100.0 | 0.0 | 0.0 | 0.0 | 0 | not measured | not measured |
| burst | 8.3 | 91.7 | 0.0 | 0.0 | 8 | not measured | not measured |
| sustained overload | 8.3 | 91.7 | 0.0 | 0.0 | 0 | not measured | not measured |
| minute limit halved | 0.0 | 100.0 | 0.0 | 0.0 | 0 | not measured | not measured |
| daily budget exhausted | 0.0 | 100.0 | 0.0 | 0.0 | 1 | not measured | not measured |

## 4. Where the time goes.

Burst request `504d72aa52454c32aed7b477fbeb6a00` took 7,409.9 ms. Raw client/server
timestamps split it into 3,078.5 ms before the handler, 3,826.3 ms in the admission
queue, 505.0 ms working (488.3 ms retrieval), and 0 ms retrying. Thus 6,904.9 ms was
waiting. All delay preceded the first response byte (7,408.2 ms); no provider token was
released because minute admission rejected the draft.

## 5. When a limit is hit.

At the minute limit, reservations reject work before an unverified draft escapes; a
retryable provider 429 can wait only within the deadline and available quota. A full
eight-slot queue is dropped immediately with an overload response. At the daily limit,
new draft-plus-verifier work is rejected without retry. Nobody receives a weaker answer:
bounded waiting and explicit rejection are preferred to silently removing verification.

## 6. Retrieval: quality versus cost.

I compared: (A) 180-word lexical, k=4, no rerank; (B) 220-token MiniLM hybrid/RRF,
k=4, no rerank; (C) B plus CrossEncoder rerank. Retrieval-only all-expected-paper
recall@4 was 100.0/93.3/93.3%, median search 2.0/13.1/324.1 ms, and median context
4,377.5/3,571.5/3,807.5 characters. The approved grades make B the preferred setting:
it has the highest correct+cited rate, fewer wrong refusals than A/C, and much lower
latency than C. Near a limit I keep k=4 and skip reranking; I never weaken citation
verification. Tokens/answer charges all known failed-attempt usage to delivered responses.

### Table 3. Retrieval settings

| Setting | Questions asked/completed | Correct+cited % | Wrong % | Correctly refused % | Tokens/answer | First token p50/p95 ms | Total p50/p95 ms |
|---|---:|---|---|---|---|---|---|
| A: 180 words, k4, no rerank | 15 / 14 | 50.0 | 28.6 | 21.4 | 4,648.5 | not measured | 1,481.4 / 23,126.9 |
| B: 220 tokens, hybrid k4, no rerank | 14 / 14 | 57.1 | 21.4 | 21.4 | 4,106.5 | not measured | 1,528.9 / 2,916.9 |
| C: B + rerank | 14 / 14 | 50.0 | 28.6 | 21.4 | 3,753.1 | not measured | 2,407.2 / 13,219.4 |

## 7. How this library will mislead a naive retriever.

1. A cross-paper Moshi/H-Net synthesis returned four H-Net passages and missed Moshi
   under B/C: "How does Moshi's hierarchy compare with dynamic chunking?"
2. Reranking placed a generic page-2 attention passage above the direct page-6 position
   section: "How does the Transformer represent token order?"
3. Plausible text does not imply answerability: Moshi training-cost retrieved a safety
   table, while "What RAG chunk size does H-Net recommend?" retrieved sequence-model
   dynamic chunking. Both require refusal.

## 8. Retries.

I retry only 429, selected 5xx, transport failures, and timeouts; I honor `Retry-After`,
otherwise use bounded exponential delay plus jitter. Auth/validation/daily exhaustion do
not retry. In supplementary stand-in probe `96388c9072b141e4be8f8c5ee71219d1`,
an injected failure caused 628.4 ms of retry wait, then the minute budget blocked the next
attempt. Total became 1,393.5 ms with no recovery: retry planning made the outcome slower.

## 9. What the person sees.

At 3pm with no daily budget, the user sees: "The daily model budget is exhausted. No
unverified answer was shown. Please try again after the budget resets." The UI preserves
their question, labels the failure, and offers retry later; it does not display a partial
draft or fake progress.

## 10. What I'm unsure about, what I left out, what I learned.

I am least certain that my rolling 60-second/24-hour windows match Groq's exact reset
semantics; a mismatch could reject early or retry too soon. I deliberately left out
distributed multi-process admission and public multi-tenant authentication/deployment.
I learned that provider limits are not only requests per minute: token and daily budgets,
queues, and retries interact, so real measurements must stay separate from simulator
assumptions.

## 11. Your feedback on Vaani.

The strongest part is the concrete Teacher AI flow: describe an agent, answer clarifying
questions, watch it build, then approve a prompt diff. Multilingual turn-taking, memories,
live-call access, and customer stories make the product feel operational rather than a
generic voice demo. The phrase "voice AI harness" is less clear for a first-time visitor.
I would add a compact above-the-fold diagram defining the harness as build, test, deploy,
and improve, with one measurable outcome and its methodology beside each stage.

## 12. How I worked with the assistant.

The unedited conversation/prompts are a separate attachment. My important prompts were
the source-of-truth brief, the production UI/architecture request, and the instruction to
conserve API quota while continuing autonomously. I caught an overly centred first answer
layout and asked for ChatGPT-like left-aligned conversation flow. I overruled making true
Black merely optional and made it the default. The ChatGPT-like interaction, three themes,
strict Groq quota conservation, and final human grading were distinctly my choices. At my
request, the assistant also inspected Vaani and drafted the concise feedback above.
