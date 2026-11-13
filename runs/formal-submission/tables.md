# The Relay measured tables

Percentiles use linear interpolation over observed request values.
Efficiency charges all known consumed work, including failures, to delivered answers.

## Real service limits

| limit | value_found | how_found | confidence |
| --- | --- | --- | --- |
| requests/min | 30 | official documentation; not stress-tested | medium |
| tokens/min | 8000 | real response headers and official documentation | high |
| requests/day | 1000 | real response headers and official documentation | high |
| tokens/day | 200000 | official documentation; not exhausted at provider | medium |
| requests in flight | at least 2; maximum not measured | successful real calibration concurrency | low |
| limit response | not measured; documentation specifies HTTP 429 + Retry-After | observed HTTP statuses [200]; documentation | low |
| recovery time | not measured | real limit was not deliberately reached | low |

## Real calibration

| attempts | successful_attempts | median_first_token_ms | median_total_ms | tokens_total | retries | observed_http_statuses |
| --- | --- | --- | --- | --- | --- | --- |
| 12 | 12 | 483.9 | 485.8 | 4608 | 0 | [200] |

## Scenario runs

| run_id | scenario | source | count | duration_s | offered_rate_per_min | ttft_p50_ms | ttft_p95_ms | ttft_p99_ms | total_p50_ms | total_p95_ms | total_p99_ms | success_pct | rate_limited_pct | timeout_or_given_up_pct | retries_per_request | peak_queue_length | delivered_answers | tokens_per_answer | token_usage_coverage_pct | cost_per_1000_answers_usd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 36dd7fe7e18b4b8185f90475bff06d26 | daily_budget_exhausted | stand-in | 4 | 2.092 | 30.0 | 1824.4 | 2084.4 | 2085.3 | 1826.5 | 2085.8 | 2086.7 | 0.0 | 100.0 | 0.0 | 0.0 | 1 | 0 | — | 50.0 | — |
| 7c3d64d72cda49308a28d41c206b34e1 | steady | stand-in | 3 | 162.593 | 0.75 | 2574.6 | 2740.4 | 2755.1 | 2576.0 | 2741.7 | 2756.4 | 100.0 | 0.0 | 0.0 | 0.0 | 0 | 0 | — | 100.0 | — |
| 94cc1b31966a48f399df49e9511a8f95 | minute_limit_halved | stand-in | 3 | 161.811 | 0.75 | 1799.1 | 1966.4 | 1981.3 | 1800.5 | 1967.7 | 1982.5 | 0.0 | 100.0 | 0.0 | 0.0 | 0 | 0 | — | 100.0 | — |
| fd25f2674dd0409b80e2154d0c068e18 | sustained_overload | stand-in | 24 | 115.663 | 12.0 | 655.7 | 2566.3 | 3036.4 | 657.2 | 2567.8 | 3037.8 | 8.3 | 91.7 | 0.0 | 0.0 | 0 | 0 | — | 100.0 | — |
| ff2e702330d14df7aea3035fd9e24221 | burst | stand-in | 12 | 7.423 | 30.0 | 6046.4 | 7384.5 | 7403.4 | 6048.4 | 7387.0 | 7405.3 | 8.3 | 91.7 | 0.0 | 0.0 | 8 | 0 | — | 100.0 | — |

## Retrieval quality

| retrieval_setting | questions | correct_and_cited_pct | wrong_pct | correctly_refused_pct | wrong_refusal_count | tokens_per_answer | token_usage_coverage_pct | ttft_p50_ms | ttft_p95_ms | total_p50_ms | total_p95_ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid-minilm220-rrf-k4-v1 | 14 | 57.1 | 21.4 | 21.4 | 3 | 4106.5 | 100.0 | — | — | 1528.9 | 2916.9 |
| hybrid-minilm220-rrf-rerank-k4-v1 | 14 | 50.0 | 28.6 | 21.4 | 4 | 3753.1 | 100.0 | — | — | 2407.2 | 13219.4 |
| lexical-word180-k4-v1 | 14 | 50.0 | 28.6 | 21.4 | 4 | 4648.5 | 100.0 | — | — | 1481.4 | 23126.9 |
