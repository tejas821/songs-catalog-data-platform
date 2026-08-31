# PROMPTS.md — AI collaboration log

Tool: **Claude (Opus) in agent mode**, driving a shell and the filesystem directly.
Below is the real sequence, in order, with the turning points annotated. It is short on
purpose — the brief asks for high-signal steering, and I got more out of a few prompts
that set constraints up front than I would have from forty corrections afterwards.

---

## 1. Framing prompt (before any code)

> read the files from folder, follow the TAKE_HOME pdf, start performing the assignment.
> use tokens smartly. code must be readable, no complex dependencies, no complex flow,
> keep it as straight and simple as you can.

**Why this and not "build me a songs API":** the constraint that mattered was *simple
and readable*, and stating it once at the top is worth more than rejecting
over-engineered output later. Without it the default output for "normalize two JSON
files" is pandas, and the default for "build an API" is SQLAlchemy + Alembic + a
Docker compose file. For 25 rows all three are ceremony.

**Result:** the whole normalizer is standard library. No pandas anywhere in the repo.

## 2. Stack decision — I overruled the AI here

The AI proposed a single-file React page loaded from a CDN, arguing it needed no build
step and would run on a clean machine with one command.

> tech stack are python fast api and angular 22 latest version with primeng for
> better and faster ui

**This is the one I'd point to.** The AI's suggestion was *reasonable for the constraint
I had given it* — I had asked for "simple", and it optimised for that literally. But
"simple to run" and "simple to review" are not the same axis, and a CDN React page with
Babel-in-the-browser reads as avoiding the work. I took the extra `npm install` in
exchange for a real component structure, real typing, and a real test runner. Recorded
here because it's the clearest case of the AI being locally right and globally wrong.

## 3. "Read the data before you write any code"

I made the AI dump **every column of both files** as raw JSON and diff them before
proposing any schema, rather than letting it skim and start writing.

**Turning point — this is where the exercise is actually won.** On a quick look the AI's
summary was "some nulls and some type inconsistencies, I'll coerce and move on." The
full dump is what surfaced the things a skim misses:

- `duration_ms` values of **158, 270, 356** in part2 — the unit bug. A summariser
  reports "duration_ms: integers, min 158, max 401200" and nothing looks wrong.
- **two different songs both titled "Perfect"** — invisible unless you actually look at
  the id column next to the title column.
- `energy` in part1 is missing the key `"2"` entirely — a *hole in a column*, which is
  a different failure from a `null` and needs the row-index walk to catch.

**Lesson I'd repeat:** the AI is good at answering "what's in this file" and bad at
volunteering "what's wrong with this file". Ask the second question explicitly, and
make it show you the raw values rather than a summary of them.

## 4. Pushing back on the first normalization design

The AI's first proposal **clamped** out-of-range values (1.42 → 1.0) and **imputed**
missing ones from the column mean.

> don't clamp and don't impute. drop the value, keep the row, and attach a flag saying
> why. a consumer should be able to trust every non-null value or see it marked.

**Why I overruled it:** clamping 1.42 to 1.0 produces a number indistinguishable from a
measured 1.0 — it launders a data bug into a fact and guarantees nobody upstream ever
fixes it. Imputing from a 25-row column mean is noise dressed as data. The AI's
instinct was to make the table *look* complete; the brief asks for it to *be*
trustworthy. Those are opposite goals and the AI picked the wrong one by default.

This single decision is what produced the `flags` column, the `normalization_report.json`,
and the second chart in the dashboard.

## 5. The code review — asking the right question

For Section 4 I read `buggy_api.py` myself first, then asked the AI for a second pass.
Both halves are recorded honestly in REVIEW.md; the short version:

- The AI's **headline finding was the mutable default argument** (`_cache=[]`). Real, but
  it works, and shipping it costs testability rather than correctness. Led with as a
  blocker, it would have buried the actual blockers. **It cried wolf.**
- **It missed the sort-after-slice bug on the first pass.** The function contains a
  `sorted()` with a `key` and a `reverse`, so it *reads* as correct. The defect is the
  order of two statements, not a missing statement, and pattern matching doesn't see it.
- I found it by not reading the code at all — I asked **"on 25 rows, what does
  `?sort_by=tempo&order=desc&page=1` actually return?"** and traced the values. Reframing
  from "review this function" to "execute this request by hand" is what surfaced it.
- The AI *was* strong on the HTTP-semantics problems (`200` on a not-found, a bare
  `int` parameter silently becoming a query param on a POST). That's exactly the
  pattern-matching it's best at.

**Takeaway:** use AI for the "this line is wrong" class of bug, and do the "these two
correct lines are in the wrong order" class yourself.

## 6. Where the AI was simply right, first try

Worth recording so this log isn't only complaints:

- The **atomic write-then-rename** for `ratings.json` was volunteered, not asked for.
- `PUT` rather than `POST` for a rating, with the reasoning ("rating twice sets one
  rating, it doesn't add two") — correct and better-argued than my prompt.
- Sinking `None` values to the bottom of a sort **in both directions** — I'd have written
  the ascending case and left the descending one as a latent bug.
- The pure-functions-in-`store.py` split that made the tests need no mocking.

## 7. Where it cost me time

Two real losses, both the same shape — **the AI writing from memory of an older library
version**:

- The first Angular build failed with three errors at once: `p-sortIcon` (renamed to
  `p-sort-icon` in PrimeNG v22), `p-message [text]` (that input was removed in favour of
  content projection), and a chart-data typing error. All three were confidently written
  as if from v17 docs. The fix took one build cycle because I ran `ng build` immediately
  instead of writing more components on top of unverified assumptions — but the general
  hazard is real: **"Angular 22 latest" is past the model's training data, and it will
  not tell you that.** I now grep `node_modules` for the actual selector rather than
  trusting recalled API shapes.
- Backgrounded `npm install` silently died twice because the shell tore down the process
  group on exit. I burned two round trips before running it in the foreground. Not the
  AI's fault, but it's where the wall-clock went.

## 8. Verification prompts (the ones I'd add to any future session)

> now actually run it: start uvicorn, curl every endpoint including the bad inputs,
> and show me the last page of a tempo-descending sort.

This is the prompt that turns "the code looks right" into evidence. It's how I confirmed
the null-sinking rule (Blinding Lights, tempo unknown, lands on the final page in *both*
directions), that a bad `sort_by` is a `400` and not a `500`, that `stars: 9` is a `422`,
and that `"  4 WALLS "` finds `"4 walls"`. Every one of those is a line in the test suite
now.

---

## Honest note on volume

This was a short session by design: **eight prompts, three of which were overrules.** The
build itself took a fraction of the time; most of the effort went into reading the two
JSON files properly, arguing with the normalization defaults, and the review. That
allocation was deliberate — the brief says so explicitly, and I agree with it.
