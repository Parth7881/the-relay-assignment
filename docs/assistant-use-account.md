# The Relay - assistant-use account

Status: final, 13 November 2026.

The complete Codex chat is the canonical, unedited conversation history. This file is a
compact submission index of the authentic user prompts and decisions that materially
changed the work; it is not presented as a replacement for a full chat export.

## Important user prompts and decisions

1. Source-of-truth and scope: the user supplied the original assignment PDF and required
   the exact three arXiv versions, a four-step-plus pipeline, real Groq measurements, a
   calibrated stand-in, five traffic scenarios, three retrieval settings, at least 15
   questions, `results.csv`, raw evidence, and a maximum-two-page write-up.

2. Frontend architecture decision: `Python backend + React UI (recommended)`.

3. Implementation authorization: `Native approved, implement`.

4. Visual direction: `UI esa rakhna hai. referance esa polished and best rakho.` The user
   later rejected the overly centred answer layout and requested a ChatGPT-like question
   and answer flow across Ask, Library and Runs, with Black as the primary theme plus Dark
   and Light choices.

5. Quota policy: `ok start kro but zyada test mat krna because we have limited api key.
   jarurat ho to hee kro.` This caused the implementation to reuse the retained 12-call
   calibration instead of making unnecessary new Groq requests.

6. Autonomy: `ask only big decision question , dont ask me normal question so work start`.
   Engineering continued across parts without routine approval pauses.

7. Human grading approval: `all clear , next ?` The request-ID-bound grade overlay records
   the previously presented proposals: 22 correct, 9 refused correctly, 11 refused
   wrongly, and 6 operational attempts left ungraded.

8. Vaani delegation: `apne hisaaab se kuch best krdo. and next start kro`. The assistant
   inspected the current Vaani website and drafted the concise feedback in Section 11;
   the write-up explicitly discloses this assistant contribution.

## Error caught and overrule

- The user caught that the first answer experience was too centred and required a
  left-aligned conversational hierarchy.
- The user overruled treating true Black as merely an optional theme and made it the
  primary default.
- The user chose strict quota conservation over additional real-provider load calls.

## Distinctly user-owned choices

- React over a Python-only UI.
- ChatGPT-like answer interaction and visible citations.
- Black, Dark and Light themes with true Black as the default.
- Minimal real-provider usage and no deliberate real overload.
- Final human control over answer grading.

## Assistant contribution

The assistant inspected the repository and source PDF, researched current official Groq
documentation, implemented and tested the system, proposed the grading rubric, generated
the stand-in experiments and tables, performed security/review passes, inspected Vaani at
the user's request, and produced the final write-up. Measurements, tests and grades are
linked to retained artifacts; no missing personal disagreement or learning was invented.

## Submission note

If the assessor requires the complete conversation rather than a prompt index, export or
attach the original Codex chat alongside this file. Do not recreate or paraphrase it as a
full transcript.
