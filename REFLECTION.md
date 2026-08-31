# REFLECTION.md

## 1. The single weakest part of this submission

**Ratings storage.** It's a JSON file written from a module-level `SongStore` guarded by
a `threading.Lock`. That is correct for one uvicorn worker and wrong for two: each
process holds its own dict and its own last-write-wins view of the file, so under
`--workers 4` a rating written on worker A is invisible on the next request and will be
clobbered by worker B's next save. The lock protects against threads, not processes.

I left it because the honest alternative was a database — a schema, a migration tool, a
connection string and a container — carried for a table of 25 rows and one integer
column. That trade felt like the wrong kind of thoroughness for a 3-hour exercise. But
it is a real defect, not a simplification, and it is written down in DECISIONS.md rather
than hidden. The fix is contained: `SongStore` is the only thing that touches ratings,
so swapping it for SQLite changes one class and no routes.

Runner-up: **the frontend has no end-to-end test**. There are 8 component/unit tests
(page-math, rollback, formatting, CSV quoting), but nothing that boots the API and the
UI together. If the API's response shape changed, the tests would still pass and the
dashboard would be blank.

## 2. Where AI saved time, and where it nearly led me wrong

**Saved the most time:** the mechanical layers. FastAPI routes, Pydantic validation, the
Angular component wiring, PrimeNG table configuration, and — more than any of those —
the *tests*. Writing 29 tests by hand is an hour; reviewing 29 generated tests and
rewriting the four that asserted something trivial is ten minutes. The leverage is
highest where the code is boring and the correctness criterion is obvious.

**Nearly led me wrong, twice, in the same way — by making broken data look fine:**

- Its first normalization pass **clamped** 1.42 to 1.0 and **imputed** missing values
  from the column mean. Both produce a table that looks complete and passes every
  schema check, and both destroy the evidence that the upstream export is broken. This
  is the failure mode I'd warn a teammate about: AI defaults toward output that *looks*
  clean, and "looks clean" is the opposite of what Section 1 is testing.
- Its summary of the data was "some nulls and type inconsistencies" — technically true,
  and it would have carried the unit bug straight through to production. `min 158,
  max 401200` reads as a normal integer column.

**Cost me time:** it wrote PrimeNG v17 APIs while confidently claiming v22 (`p-sortIcon`
vs `p-sort-icon`, a `[text]` input that no longer exists). "Angular 22" is past its
training data and it does not volunteer that. Three compile errors, one build cycle to
find, cheap only because I built early. Had I written four components before the first
`ng build`, it would have been an expensive afternoon.

## 3. What surprised me in the data, and what I chose not to fix

**The surprise:** the unit bug is not the clever one. Three durations of `158`, `270`,
`356` are obvious the moment you look at raw values — one order-of-magnitude glance.
The genuinely nasty item is **two different songs both titled "Perfect"**, because
nothing about it looks wrong. Both rows are well-formed, every value is in range, no
validator fires. It only becomes a bug when someone writes `songs[title]` — which is
exactly what `buggy_api.py` does, and exactly how ratings there land on the wrong song.
The defect that passes every check is worse than the one that fails an obvious one.

Second surprise: the two exports **barely disagree**. I expected a merge full of
conflicts; across four overlapping songs and nine attributes there is exactly one
disagreement (danceability 0.727 vs 0.74, a rounding-scale difference). The reconciliation
problem was much smaller than the within-file quality problem.

**What I chose not to fix:**

- **Title casing.** `" 4 walls  "` is stored as `"4 walls"` — trimmed, not title-cased.
  I can strip whitespace with certainty; I cannot title-case without inventing an
  editorial rule that will mangle deliberately-styled names on the next batch. Search is
  case-insensitive, so nothing downstream suffers.
- **The `danceability` conflict.** I picked part2 and recorded the discarded value
  rather than trying to determine which pipeline is more accurate. With two samples I
  have no basis to prefer one; a rule I can't defend is worse than a rule I can
  document and reverse (`PREFERRED_SOURCE`, one constant).
- **The two `Perfect` rows.** Left as two songs. Merging them would need a human to
  confirm they're the same recording, and the durations differ by 600 ms, which suggests
  they aren't.
- **`tempo = 0` for Blinding Lights.** Nulled, not looked up. The real tempo is public
  knowledge, but enriching from outside the given exports is a different exercise, and
  a value invented by the pipeline is indistinguishable from a measured one.

## 4. If this shipped Monday, what breaks first

**In order:**

1. **Ratings, on the first restart or the first second worker.** Anything above one
   process loses writes silently. This is the one that generates a support ticket in
   week one, and the one hardest to reproduce.
2. **Everything, on the next upstream export.** The pipeline reads two hard-coded file
   paths on disk. There is no ingest, no schema check, no "reject the batch" path. A
   part3 file, a renamed column, or an export where `tempo` arrives as `"128 BPM"` means
   editing `normalize.py`. Worse: a *quietly* changed unit — say durations that switch to
   seconds for **all** rows, not three — sails past my `< 10_000` heuristic because
   264 000 is still a plausible millisecond value. My unit detection is per-value, and a
   wholesale unit change is a per-column problem.
3. **The frontend's `size=200` call.** The charts and "export all" fetch the entire
   dataset in one request. Fine at 25 rows; at 25 000 it's a multi-megabyte payload that
   blocks page load, and at 250 000 it hits the server-side cap and silently charts a
   subset while looking complete.
4. **`CORS allow_origins=["http://localhost:4200"]`.** Correct for development and
   exactly wrong in production — the deployed frontend gets blocked by the browser while
   `curl` works fine, which is a confusing first hour for whoever deploys it.
5. **Sorting, under load.** Every request sorts all 25 rows from scratch. Irrelevant now,
   O(n log n) per request forever, and the first thing to hurt when the table grows.

---

## 5. Production readiness (lead / architect)

Where I'd draw the v1 line: **make the data trustworthy and the failures visible.
Everything else waits.**

### Data pipeline
The hard-coded two-file read is the weakest structural thing here, more than the storage
choice. v1:

- **Ingest is a job, not an import.** Land raw exports immutably (object storage, keyed
  by source + timestamp), then transform. Never mutate the raw copy — every rerun must
  be reproducible from what actually arrived, including the broken batches.
- **Contract-check at the boundary, per column, before merging.** Not "is it parseable"
  but "is this column shaped the way it was last time": null rate, min/max, dtype,
  cardinality. The wholesale-unit-change failure in §4.2 is invisible per-value and
  obvious per-column — the median duration halving between batches is the signal.
  Great Expectations or a hundred lines of assertions; the tool matters less than the
  fact that a batch can be *rejected* rather than merged.
- **Idempotent, versioned output.** Rerunning on the same inputs produces byte-identical
  output. `normalization_report.json` becomes a first-class artifact, diffed batch over
  batch — a jump in `flagged_values` is the early warning that upstream changed.
- **Postgres as the serving store**, with the raw JSON kept alongside. Ratings get a real
  table with a unique constraint on (song_id, user_id), which also kills the
  multi-worker bug for free.
- **Explicit conflict policy as data, not code.** `PREFERRED_SOURCE` should be a
  per-source precedence row with an effective date, so "part3 supersedes part2 from
  March" is a config change, not a deploy.

### Testing
- Keep the pure-function core (`store.py`, `normalize.py`) — it's why the current tests
  need no mocks, and that property is worth protecting as the code grows.
- Add **property-based tests** (Hypothesis) over the cleaners. My unit tests assert the
  defects I found; property tests assert the invariant — *no output value is ever
  outside its declared range, whatever garbage goes in* — which covers the defects I
  haven't seen yet. Given that the whole exercise is about unknown-unknowns in upstream
  data, this is the highest-value addition on this list.
- **Golden-file test** on the normalizer: fixed inputs, committed expected output, diffed
  in CI. Makes every change to a cleaning rule show its blast radius in the PR.
- **One end-to-end test** (Playwright): boot API + UI, sort a column, assert the top row
  matches the API's answer. Cheap insurance against the contract drift in §1.
- Contract tests from the OpenAPI schema so the frontend's types can't silently diverge.

### Observability
- **Structured JSON logs** with a request id propagated to the frontend, so a user's "it
  showed me nothing" is one grep.
- **Metrics that describe the data, not just the process.** Request rate/latency/error
  rate is table stakes; the ones that would actually catch the failures in §4 are
  `rows_ingested`, `rows_rejected`, `values_flagged{field,reason}`, and
  `merge_conflicts`. Alert on *change* in those, not on absolute values — a flag rate
  going from 10 to 400 is the incident, and no HTTP metric shows it.
- **Alert on the silent failures specifically:** a batch that ingests zero rows, a flag
  rate outside its trailing band, a column whose null rate jumps. The 500s page
  themselves; the wrong-but-200 answers are what need instrumentation.
- Sentry for exceptions, `/api/health` extended to a readiness probe that asserts the
  data actually loaded.

### Deployment
- One container per service, non-root, pinned base images; `uvicorn` behind gunicorn
  workers *once ratings are in Postgres and not before*.
- CI: lint → typecheck (mypy + `strict` TS) → tests → build → deploy. Migrations run as
  a separate gated step, never on app start.
- Config from environment (CORS origins, database URL, page-size cap). The hard-coded
  `localhost:4200` is exactly the class of thing that must not be in a deployed image.
- Frontend as static assets on a CDN; the API behind a gateway doing TLS, rate limiting
  and auth.

### Where I'd draw the v1 line

**In:** Postgres + migrations, ingest as a scheduled job with column-level contract
checks and a reject path, structured logging, the data-quality metrics and their
change-alerts, CI with the golden-file and property tests, config from environment,
health/readiness probes.

**Out of v1, deliberately:** Airflow or any orchestrator (a cron'd job is honest until
there's a second dependency), Kubernetes (one container on a managed runtime), caching
(nothing is slow yet), auth beyond a gateway token (no users), search infrastructure
(25k rows is a `LIKE` and an index), and per-user ratings (no user model to hang them
on).

The reasoning behind that line: **at this size the risk is bad data served confidently,
not scale.** Every item I kept makes a wrong number visible or a bad batch rejectable.
Every item I cut is infrastructure that would make the system harder to change while the
requirements are still moving — and none of it would have caught a single one of the
thirteen defects in these two files.
