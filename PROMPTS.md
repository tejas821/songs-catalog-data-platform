# PROMPTS.md — AI collaboration log

**Tool:** Claude (Opus) in agent mode — direct shell and filesystem access, so one
instruction from me could produce many autonomous steps (read files, write code, run
tests, read the failures, fix them) before control came back to me.

**What that means for this log.** This was not a chat session with a prompt per change.
It was delegation with constraints set up front, which produces a *short* prompt history
and long stretches of autonomous AI work in between. Rather than dress that up as
turn-by-turn steering, this log states which parts were mine and which were the AI's.

### Labelling convention

| Label | Meaning |
|---|---|
| **Verbatim** | The exact text I typed, character-for-character, typos included. |
| **Session summary** | Something that happened in the session but was not phrased by me as a prompt — an autonomous AI decision, or a build/test failure and its fix. Reconstructed from the session; verifiable against the repo, build output or `git log`. Not presented as a quote. |
| **Evident from implementation** | A decision I did not instruct and did not observe being debated. Inferred from the code that exists. |

**Four verbatim prompts exist.** Everything else carries one of the other two labels.

---

## 1. Framing the exercise

**A. Prompt — Verbatim**

> read the files from folder follow the home pdf start performing the assignment also make
> sure use token wise and smartly do it very nice way making sure that all thing should be
> done properly at least tokens also code must be readable no complex dependencies complex
> flow keep it as straight and simple as u can

**B. Intent** — Set the non-negotiable constraints before any code existed: read the
brief first, minimal dependencies, readable control flow. I deliberately specified no
design. In a timeboxed exercise where the AI does the typing, the constraint envelope is
the highest-leverage thing to control.

**C. AI outcome** — Correct, and the constraint held throughout.
`backend/requirements.txt` is five lines — `fastapi`, `uvicorn`, `pydantic`, plus
`pytest` and `httpx` for tests. The normalizer is standard library only: no pandas, no
numpy. No database, no ORM, no migration tool, no Docker, no task queue.

**D. Developer intervention** — None needed; accepted as written.

**E. Why it mattered** — Left unconstrained, the default output for "normalize two JSON
files" is pandas and for "build an API" is SQLAlchemy + Alembic. For 25 rows both are
ceremony a reviewer then has to read past. This constraint is why `normalize.py` is
readable `if`/`return` logic rather than a chain of dataframe operations.

---

## 2. Scope and stack — the one clear overrule in this session

**A. Prompt — Verbatim** (two messages, in sequence)

Answering a clarifying question about role scope and frontend approach, where the AI's
**recommended** option was a single-file React page loaded from a CDN ("no npm, no
node_modules, no build step, runs with one command"):

> for frontend use angular 22 with primeng

Then, immediately after, unprompted:

> tech stack are python fast api and angular 22 latest version with primeng for better and
> fastr ui

Scope chosen in the same exchange: **Full-stack + Lead/architect**.

**B. Intent** — Reject the zero-build-step frontend and take a real framework.

**C. AI outcome** — The recommendation was *locally* reasonable and *globally* wrong. I
had asked for "simple" and it optimised for that literally: a CDN React page genuinely is
simpler to run. But "simple to run" and "simple to review" are different axes, and
Babel-in-the-browser reads as avoiding the work on a submission graded by engineers.

**D. Developer intervention** — Overruled outright, twice, without softening it. I took
the cost — a real `npm install`, a build step, a second process — for typed models,
component/service separation and a real test runner.

**E. Why it mattered** — The one decision in this session that was unambiguously mine and
that changed the shape of the deliverable. It also directly caused turning point #5:
choosing a framework version newer than the model's training data.

---

## 3. Reading the data before designing anything

**A. Session summary** — Before any schema was written, both JSON files were dumped in
full — every column, raw values, not a summary — and diffed against each other.

**B. Intent** — The brief says the data is deliberately messy and refuses to list the
problems. That makes "what is wrong with this file" the actual first task.

**C. AI outcome** — Correct, and this is where the exercise is won or lost. Thirteen
distinct defects were found and are documented in DECISIONS.md §1.1. Three are invisible
to a summary-level read:

- `duration_ms` values of **158, 270, 356** in part2. A column summary reports "integers,
  min 158, max 401200" and nothing looks wrong.
- **Two different songs both titled "Perfect"** (ids `0tgVpDi06Fy…` / `7dNsHhGeGU5…`,
  durations 263400 / 264000). Every value is well-formed. No validator fires. It is only a
  bug when code keys on title.
- part1's `energy` column is missing the key `"2"` **entirely** — a hole in a column, not
  a null. Catching it requires walking the row index rather than iterating the column.

**D. Developer intervention** — None. This was the AI's own first step, not something I
prompted. The output is checkable rather than taken on trust: the arithmetic reconciles
in `data/normalization_report.json` (16 + 13 rows in, 4 overlapping ids, **25 songs out,
zero dropped**), and each defect is asserted by a named test in
`backend/tests/test_normalize.py`.

**E. Why it mattered** — Every normalization rule in the repo traces to a specific
observed defect. None are speculative hardening.

---

## 4. Normalization policy: null + flag, never clamp, never impute

**A. Session summary / Evident from implementation** — **The AI originated this.** I did
not instruct it, and there was no correction or debate in the session to record. It is
implemented in `normalize.py` and pinned by a test named
`test_out_of_range_value_is_dropped_not_clamped`.

**C. AI outcome** — Correct, and better than the obvious alternative. Out-of-range values
(`danceability` 1.42, `acousticness` -0.05) and sentinels (`"N/A"`, `null`, `tempo` 0)
become `null` plus a flag naming the original value — `danceability:out_of_range(1.42)`.
The row survives; only the untrustworthy value is removed. Zero rows were dropped.

**D. Developer intervention — none, and I am not going to claim one.** I did not catch
the AI doing something worse here and correct it. I reviewed the rule afterwards and kept
it, because the alternatives are worse: clamping 1.42 to 1.0 produces a value
indistinguishable from a measured 1.0, which launders a data bug into a fact and removes
the evidence that would get the upstream export fixed; imputing from a 25-row column mean
is noise that is indistinguishable from a real measurement forever after. The full
argument is in DECISIONS.md §1.5. **I can defend the rule. I did not originate it.**

**E. Why it mattered** — It is the decision the rest of the system rests on. It produced
the `flags` column, `normalization_report.json`, the `—`-with-a-tag rendering in the
table, and the second chart.

---

## 5. Correctness traps verified by execution, not by reading

**A. Session summary** — After the backend was written, the AI booted uvicorn and ran the
API against real requests, including deliberately adversarial ones, rather than declaring
it done at "it imports".

**C. AI outcome** — Correct first try; nothing needed fixing at this step. What the run
demonstrated:

| Check | Result |
|---|---|
| `?sort_by=tempo&order=desc&page=1` | Despacito 177.928 — the true global maximum, not a page-local one |
| Final page of that sort | Blinding Lights, `tempo: null`, flagged `implausible(0.0)` — unknowns sink last |
| `?title=%20%204%20WALLS%20` | finds `"4 walls"` |
| `?title=perfect` | `count: 2`, two distinct ids |
| `PUT …/rating {"stars": 9}` | `422` |
| `?sort_by=evil` | `400`, not a 500 |
| `data/ratings.json` after the call | written to disk |

**D. Developer intervention** — None at the time; this was the AI's own verification
loop. What makes it durable rather than a one-off terminal session is that each line
above became a named test — `test_sorting_spans_the_whole_dataset_not_just_the_page`,
`test_unknown_values_sink_to_the_bottom_in_both_directions`,
`test_rating_rejects_invalid_input` — so the checks are repeatable by anyone who clones
the repo.

**E. Why it mattered** — Sort-then-paginate is the one trap in this assignment that looks
correct from the UI. Each page is internally ordered, so manual clicking never exposes
it. Only comparing page 1 against the global extreme catches it — which is exactly the
first row of that table, and exactly the bug in the supplied `review/buggy_api.py`.

---

## 6. The AI's real mistake: writing a library version it does not know

**A. Session summary** — The first Angular build failed with three errors at once.

**C. AI outcome — incorrect, and confidently so.** All three were PrimeNG APIs written
from memory of an older major version while the project was pinned to v22:

- `<p-sortIcon>` — renamed to `p-sort-icon` in v22
- `<p-message [text]="…">` — that input no longer exists; v22 uses content projection
- chart data typed `signal<unknown>` — not assignable to PrimeNG's `ChartData` input

None were flagged as uncertain. **"Angular 22 latest" is past the model's training
cutoff, and it does not volunteer that it is guessing.**

**D. Developer intervention** — None at the time. The AI caught and fixed this itself,
and two properties of *how* it did so are worth recording because they are the reusable
part: `ng build` was run immediately after the first component rather than after four, so
the blast radius was one build cycle instead of an afternoon of rework layered on bad
assumptions; and the fix came from `grep`-ing the real selectors out of
`node_modules/primeng/fesm2022/primeng-table.mjs` rather than re-asking the model, which
tends to produce a second confident guess.

**E. Why it mattered** — This is the concrete cost of my stack decision in #2, and the
generalisable lesson I take from the session: **AI output is least reliable exactly where
the ecosystem moved most recently, and it signals no lower confidence there.** Verify
against the installed package, not against the model.

Two smaller instances of the same class, both caught by running things rather than
trusting them:

- The scaffolded `app.spec.ts` was left in place and made a **live HTTP call to
  `localhost:8000`** during `npm test`, failing the run with `ECONNREFUSED`. Replaced with
  a real `HttpTestingController` test that asserts something worth asserting — the
  table's 0-based offset → 1-based API page conversion, and the rating rollback.
- The production build failed Angular's default 1 MB bundle budget at 1.28 MB. PrimeNG +
  chart.js is genuinely that size; the budget was raised to 2 MB warn / 3 MB error as a
  recorded acceptance rather than silenced.

---

## 7. The code review — a single pass

**A. Session summary** — `review/buggy_api.py` was reviewed in **one pass** and written
up in REVIEW.md. There was no separate second-opinion round and no comparison between two
reviewers, so this log has nothing to report about AI false positives or misses on that
task. Fourteen issues, ranked block / before-merge / nit.

**C. AI outcome** — The ranking argument is the part worth defending in a live session:
sort-after-slice blocks the PR ahead of the off-by-one, because the off-by-one gets
noticed within a day when someone reports a missing song, while sort-after-slice produces
answers that look right forever — every page is internally ordered, so the UI, QA and
manual testing all pass and nothing ever alerts. Severity ranked by *how long the bug
survives undetected*, not by how uncomfortable the code looks. That is also why the
mutable-default-argument smell is ranked last: it works, and it costs testability rather
than correctness.

**D. Developer intervention** — None during the review itself. My intervention on this
section came later, in #8.

**E. Why it mattered** — Section 4 is a judgment test, and the ranking is the judgment.
Finding fourteen issues is the easy half.

---

## 8. The integrity pass

**A. Prompt — Verbatim** (abridged; the instruction is long)

> Be completely honest. Do NOT invent prompts, decisions, mistakes, or conversations that
> did not happen. Do NOT write fake AI collaboration history merely to improve the score.
> […] Do not claim that I personally made a decision if the evidence only shows that the
> AI made it. […] If the exact original prompt is unavailable, explicitly label it as
> "Session summary" or "Reconstructed from session" rather than pretending it was verbatim.
> […] remove any submission-facing statement that is known to be factually false.

**B. Intent** — Force the graded write-ups to match the session that actually happened
and strip the flattering fiction out of the earlier drafts.

**C. AI outcome** — This file and DECISIONS.md, rewritten against the repository rather
than against a narrative.

**D. Developer intervention** — This prompt *is* the intervention, and it is the second
of the two things in this log that were unambiguously mine. The earlier draft of
PROMPTS.md credited me with four decisions the AI had made on its own — the raw-data
inspection (#3), the no-clamp/no-impute rule (#4), the review approach (#7) and the
verification run (#5) — and described a second AI review round that never took place.
Those attributions are corrected above and the invented round is gone.

**E. Why it mattered** — The brief warns that a polished app with a hollow PROMPTS.md
scores below a rougher one with an honest log, and says the shortlist stage is a
screen-shared session on my own code. A fabricated log is a liability in both.

---

## High-Signal Turning Points

1. **The stack overrule (#2)** — the AI recommended a CDN-loaded single-file React page
   because I had said "simple". I rejected it twice and took Angular 22 + PrimeNG,
   accepting a build step in exchange for reviewability. *Mine.*

2. **The integrity pass (#8)** — demanding that the write-ups be de-fabricated: four
   decisions re-attributed from me to the AI, and an invented AI-review round removed.
   *Mine.*

3. **Reading the raw data before designing (#3)** — surfaced three defects a
   summary-level read cannot see: seconds-in-a-milliseconds-column (158/270/356), two
   distinct songs sharing the title "Perfect", and a missing *key* in part1's `energy`
   column. Everything downstream traces to this. *AI-originated.*

4. **Verification by execution (#5)** — sort-then-paginate is invisible from the UI
   because every page is internally ordered. Comparing page 1 against the global extreme
   is the only check that catches it, and it is now a named test. *AI-originated.*

5. **Library-version drift (#6)** — three PrimeNG v22 APIs written confidently from an
   older major version, plus a scaffolded spec making a live HTTP call in the test run.
   Caught by building and testing early; fixed by reading `node_modules` rather than
   re-asking the model. *AI mistake, AI-corrected.*

6. **A conscious architectural trade-off** — ratings persist to a JSON file behind a
   `threading.Lock`: correct for one uvicorn worker, lossy under several. Chosen over a
   database for a 25-row dataset, then documented as a **known defect with a migration
   path** rather than presented as sufficient (DECISIONS.md §2.6, REFLECTION.md §1).
   *AI-originated, reviewed and accepted.*

---

## What This Collaboration Shows

The AI did nearly all the typing and was genuinely fast at it: the normalizer ran
correctly on first execution and found all thirteen defects, twenty-one backend tests
passed on their first run, and details like the atomic write-then-rename for
`ratings.json`, `PUT` over `POST` for a rating, and sinking `null`s to the bottom of a
sort *in both directions* were volunteered rather than requested.

What was actually mine is narrower than the volume of output suggests, and I would rather
state it precisely than inflate it: I set the constraint envelope before any code
existed, I overruled the stack recommendation when "simple to run" and "simple to review"
pulled apart, and I audited the resulting write-ups and removed the parts that were not
true. Everything else in this repo was AI-originated and then reviewed, kept or corrected
by me. The pattern is delegation with verification — the accountability for what ships
does not move, and neither does the obligation to describe it accurately.

---

## Submission Integrity

The brief asks for the actual prompt history — *"raw session exports are perfect […] if
you paste them in by hand, keep them honest and in sequence."*

This session ran in an agent-mode tool that does not emit a `.specstory`-style
transcript, so a raw export is not available to attach. What **is** available, and
reproduced verbatim above, is the complete set of instructions I typed: **four prompts**
(#1, #2 — two messages, and #8), plus one clarification request not worth its own
section.

Everything else is labelled **Session summary** or **Evident from implementation**, and
each such claim is checkable against the repository: the build errors against the PrimeNG
package in `node_modules`, the data defects against `data/normalization_report.json`, the
correctness checks against the named tests in `backend/tests/`, and the file history
against `git log`.

An earlier draft of this file was more impressive and less true. It credited me with the
raw-data inspection, the no-clamp/no-impute rule, the review approach and the
verification run — all AI-originated — and it described an AI second-opinion review round
that did not happen. Those claims are gone.

I would rather hand over a short, verifiable log than a rich, invented one.
