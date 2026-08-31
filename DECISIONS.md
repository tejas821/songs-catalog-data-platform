# DECISIONS.md — engineering decision record

Scope: **Full-stack + Lead/architect** (all sections, plus the Production Readiness
prompt in Section 6).

This file records *why the system is shaped the way it is*. PROMPTS.md records *how the
AI session was driven* — including which of the decisions below were mine and which the
AI made autonomously. The two are meant to be read together, not to repeat each other.

---

# 1. Data normalization & reconciliation

## 1.1 The defects actually found in the two exports

Nothing below is hypothetical. Each was read out of the raw files and each is reproduced
by `python -m app.normalize`, whose output is committed at
`data/normalization_report.json`.

| # | Where | Defect |
|---|---|---|
| 1 | part1 `danceability["0"]`, `tempo["0"]` | numbers stored as **strings** (`"0.521"`, `"108.73"`) |
| 2 | part1 `danceability["3"]` | **1.42** — outside the [0,1] range the field claims |
| 3 | part2 `acousticness["7"]` | **-0.05** — same violation, other end |
| 4 | part1 `energy` | key `"2"` is **absent from the column** — a hole, not a null |
| 5 | part1 `energy["10"]` | the string **`"N/A"`** used as a null |
| 6 | part1 `acousticness["6"]` | literal `null` |
| 7 | part1 `tempo["8"]` | **0** BPM (Blinding Lights) — a sentinel wearing a valid type |
| 8 | part2 `duration_ms` rows 5, 9, 11 | **158, 270, 356** — *seconds* in a column named `duration_ms` |
| 9 | part1 `title["1"]` | `" 4 walls  "` — leading, trailing and doubled whitespace |
| 10 | both files | 4 ids appear in **both** exports (part1 rows 12–15 = part2 rows 0–3) |
| 11 | the overlap | exactly one disagreement: `danceability` for *Never Gonna Give You Up* is 0.727 (part1) vs 0.74 (part2) |
| 12 | part2 | rows 4 and 12 are **two different songs both titled "Perfect"** — different ids, durations 263400 / 264000 |
| 13 | part2 only | carries a `valence` column part1 does not have |

16 + 13 rows in, 4 overlapping ids → **25 songs out. Zero rows dropped.**

Worth separating out: defects 1–9 announce themselves — a validator catches them. Defect
**12 does not**. Both "Perfect" rows are well-formed, every value is in range, no rule
fires. It only becomes a bug when code keys on title — which is exactly what the supplied
`review/buggy_api.py` does, and exactly how its ratings land on the wrong song. **The
defect that passes every check is the dangerous one.**

## 1.2 Normalization is its own boundary, not a step inside the API

*Context.* The brief allows the clean table to live in memory, a file, or a database.

*Decision.* `backend/app/normalize.py` is a standalone program that reads
`data/songs_part*.json` and writes `data/songs.json` + `data/normalization_report.json`.
The API never reads the raw exports.

*Trade-off.* One extra command before the server starts (`python -m app.normalize`), and
a generated file in the repo.

*Why.* Cleaning and serving fail differently and change for different reasons. Keeping
them separate means the reconciliation logic is testable without a web server (see §5),
the cleaned output is inspectable as a diffable artifact rather than a runtime state, and
a bad batch is a failed job rather than a broken API. It is also the boundary a real
pipeline would have, so §7 is an extension of this design rather than a rewrite of it.

## 1.3 Identity is `id`. It cannot be title.

*Context.* Something has to define "the same song" across two files.

*Options.* `title`; `(title, duration)`; `id`.

*Decision.* `id`, unconditionally. `title` is a display attribute that happens to collide.

*Why.* Defect 12 settles it. Two rows share the title "Perfect" and are genuinely
different recordings — different ids, durations 600 ms apart. Keying on title merges them
into one song and **destroys a row**. `(title, duration)` would survive this dataset by
luck and break on the first true re-master. There is no defensible identity here other
than the id the upstream system already assigns.

This decision propagates: it is why ratings key on id (§2.6) and why title lookup returns
a collection (§2.5).

## 1.4 Reconciliation: field-level merge, deterministic, with the loser recorded

*Decision.* Rows sharing an `id` are merged **per field**, in this order
(`merge_rows` in `normalize.py`):

1. **A trusted value beats an untrusted one**, regardless of which file it came from.
2. Both trusted and equal → nothing to decide.
3. Both trusted and **different** → `PREFERRED_SOURCE` wins, the discarded value is
   written to `normalization_report.json`, and the field is flagged `<field>:conflict`.

*Why per field and not per row.* Row-level "part2 wins" would discard good part1 values
wherever part2's copy happens to be broken. Field-level merge recovers information from
the losing source instead of throwing the row away.

*Which source wins, and why.* `PREFERRED_SOURCE = "part2"`. The justification is that
part2 carries a column part1 does not (`valence`), which is what a schema looks like after
it has been extended — so part2 is inferred to be the later pipeline. **That is an
inference, not a fact.** It is precisely why the losing value is recorded rather than
dropped: if someone tells me part1 is actually newer, one module-level constant changes
and the report shows exactly what flips.

*Is precedence deterministic?* Yes. It is a constant, not a heuristic, not a timestamp
comparison, not "whichever file was read last". The same inputs always produce the same
output — which is what makes the golden-file test in §7 possible.

*Trade-off accepted.* The one real conflict is 0.727 vs 0.74 — a difference of 0.013,
almost certainly a rounding-scale artifact. Either value is defensible. What is *not*
defensible is choosing one **silently**, so the song carries `danceability:conflict` and
`normalization_report.json` names the discarded number.

## 1.5 Bad values: drop the **value**, keep the **row**, attach a reason

*Context.* Defects 1–7 span four different failure modes — wrong type, out of range,
absent key, sentinel.

*Options.* Drop the row; coerce/clamp; impute; null + flag.

*Decision.* Coerce only where the meaning is unambiguous (`"0.521"` → `0.521`; a numeric
string is the same number). Everything else becomes `null` **plus a flag naming the
original value** — `danceability:out_of_range(1.42)`, `tempo:implausible(0.0)`,
`energy:missing`. The row always survives. Zero rows were dropped from this dataset.

*Why not clamp.* Clamping 1.42 to 1.0 produces a value **indistinguishable from a
measured 1.0**. It launders a data-quality bug into a fact, and it removes the evidence
that would get the upstream export fixed. Asserted by
`test_out_of_range_value_is_dropped_not_clamped`.

*Why not impute.* With 25 rows a column mean is noise, and an imputed value is
indistinguishable from a real one for every downstream consumer forever.

*Why not drop the row.* A song with a broken `danceability` still has eight sound
attributes. Dropping it loses more than it saves.

*Sentinels are handled by rule, not by special case.* `"N/A"`, `null`, `""` and friends
go through one `NULL_TOKENS` set; `tempo = 0` is rejected by a plausibility band
(20–300 BPM) rather than an `if value == 0`. The next export will invent a different
sentinel, and a band catches it while an equality check does not.

*Why this is safer downstream.* The contract becomes single-sentenced: **every non-null
value in `songs.json` is a value you can trust; every `null` has a stated reason.** A
consumer never has to ask whether a 1.0 is real. That is the "internally consistent"
requirement in the brief, and it is also why the flags surface in the UI (§3.4) rather
than only in a log.

## 1.6 The unit defect: detected by magnitude, converted, and flagged

*Detection.* `0 < duration_ms < 10_000` → the value is seconds.

*Why seconds is the right reading.* Read as milliseconds, 158/270/356 are quarter-second
songs. Read as seconds they are 2:38, 4:30 and 5:56 — ordinary track lengths, and
consistent with the `num_segments` on those same rows (560, 1010, 1490 — mid-sized
tracks, not fragments). Two independent columns agree.

*Why a magnitude threshold works.* No real track is under 10 seconds, and no track
length expressed in seconds reaches 10 000. **The band between the two interpretations is
empty**, so the rule has no false positives on plausible data. That is what makes it a
rule rather than a fudge.

*Decision.* Multiply by 1000, store, and attach `duration_ms:seconds_converted(158s)`.

*Why convert here and null everywhere else.* This is the one case where the true value is
**recoverable with confidence** — the magnitude tells you the unit unambiguously. Nulling
three durations would have made "average song length" quietly unrepresentative instead of
quietly wrong; converting them silently would have hidden a real upstream bug. The flag is
what makes the correction auditable.

*Storage.* Always milliseconds, matching the column name. The API never returns two units
for one field; the frontend formats to `m:ss` at the edge.

*Known limit.* The detection is **per value**. If a future export switched to seconds for
*every* row, 264 000 is still a plausible millisecond value and this rule sails past it.
That is a per-column problem and needs the distribution check in §7 — noted in
REFLECTION.md §4 as a real gap, not a solved one.

## 1.7 The asymmetric column

*Decision.* `valence` (part2 only) is kept as a first-class column, `null` for the 21
songs that appear only in part1.

*Why.* Dropping it throws away real measured data because one pipeline is older;
back-filling it invents data. `null` here means "this export didn't measure it" — the
same thing `null` means everywhere else in the table. **One meaning, one representation.**

## 1.8 Text normalization: tidy for display, fold for lookup

*Decision.* Two fields. `title` is whitespace-collapsed and trimmed for display
(`" 4 walls  "` → `"4 walls"`); `title_key` is the case-folded version used for every
lookup.

*Why casing is left alone.* Trimming whitespace is certain. Title-casing is an
**editorial** rule — it would rewrite deliberately-styled names on the next batch. Search
is case-insensitive, so nothing downstream suffers from the lowercase spelling.

*Why a stored key rather than folding at query time.* The lookup rule is defined once, in
the normalizer, next to every other cleaning rule — instead of being re-derived in each
consumer that searches.

## 1.9 The flags, and what each communicates

| Flag | Meaning |
|---|---|
| `<field>:missing` | absent, `null`, or a sentinel — never measured, or unusable |
| `<field>:out_of_range(v)` | present but outside the declared range; original value preserved in the flag |
| `tempo:implausible(v)` | present but not a possible tempo |
| `duration_ms:seconds_converted(Ns)` | **corrected**, not discarded — the only flag that accompanies a non-null value |
| `<field>:conflict` | the two exports disagreed; loser recorded in `normalization_report.json` |

Flags are carried on the row, surfaced by the API, and rendered as tags in the dashboard.
The aggregate view lives in `normalization_report.json`, which is the artifact a data
owner would actually diff between batches.

---

# 2. API / backend architecture

## 2.1 The boundary

The API reads `data/songs.json` only. It never sees the raw exports, and it does no
cleaning of its own. `SongStore` loads songs once and **never mutates them** — ratings are
merged onto a copy at read time.

*Why the immutability matters.* `review/buggy_api.py` writes ratings **into** its cached
song list, so the process's idea of the source data silently diverges from the file on
disk. Keeping the loaded data read-only makes that class of bug structurally impossible
rather than merely avoided.

## 2.2 Layering: pure functions, thin routes

`store.py` holds `sort_songs`, `paginate`, `search_by_title` — pure, no framework, no I/O.
`main.py` validates input, calls them, shapes the response.

*Why.* It is the reason 21 backend tests run with **no mocking framework at all** and
most of them never construct a request. The logic worth testing is testable directly.

## 2.3 Sort the complete dataset first, then paginate — the central correctness point

```python
ordered = sort_songs(store.all_songs(), sort_by, order)   # whole dataset
items, meta = paginate(ordered, page, size)               # then cut the page
```

*Why the inverse is wrong even though it looks right.* Slicing first and sorting the
slice produces pages that are each **internally ordered**. Click through the UI and every
page looks correctly sorted. Nothing is visibly broken. But `?sort_by=tempo&order=desc`
returns an arbitrary ten songs neatly ordered among themselves — not the ten fastest. Any
feature built on it ("longest tracks", "top rated") is silently wrong, forever, with no
error and no alert.

*How it is verified.* `test_sorting_spans_the_whole_dataset_not_just_the_page` computes
the global extreme from the full set and asserts it appears on page 1. That comparison is
the only thing that catches this bug; manual clicking never will. Confirmed live:
`?sort_by=tempo&order=desc&page=1` returns Despacito at 177.928, the true maximum.

This is also blocker #1 in REVIEW.md — the supplied file has exactly this defect.

## 2.4 Null ordering

*Decision.* Rows whose sort value is `null` sink to the bottom **in both directions**.

*Why.* Sorting `None` alongside numbers either raises `TypeError` or implies that
"unknown" is smaller than every real value. Sinking them is the only option that does not
state something false. Doing it in *both* directions is the part that is easy to get
wrong: reversing a list that has nulls at the end puts them at the front. Asserted by
`test_unknown_values_sink_to_the_bottom_in_both_directions`.

## 2.5 Title lookup returns a collection, and lives on `/search`

*Decision.* `GET /api/songs/search?title=…` → `{query, match_type, count, matches[]}`.
`GET /api/songs/{id}` is the route that returns exactly one song.

*Why a collection.* Titles are not unique (defect 12). A path shaped
`/songs/{title}` promises to identify one resource and cannot keep that promise — it must
either truncate silently or lie. A search endpoint returning a list makes "two matches" a
**representable answer** rather than a hidden truncation.

*Matching strategy.* Exact match on the folded key first; if nothing matches, fall back to
a folded substring match. `match_type` is `exact` / `partial` / `none`, so the UI can say
"no exact match, showing 2 songs containing 'perf'" instead of passing a fuzzy hit off as
an exact one.

*Why zero matches is `200`, not `404`.* A search that found nothing **succeeded** — it
answered the question. `404` is reserved for `/api/songs/{id}`, where the resource
genuinely does not exist. (`buggy_api.py` gets this backwards in the worse direction: it
returns `200` with an `error` key on a miss, so every client that checks status codes
treats failure as success.)

*Trade-off.* Clients must always handle a list, even for the common one-match case. Worth
it: the alternative is a contract that is wrong for this dataset.

## 2.6 Ratings

| Choice | Reason |
|---|---|
| Keyed on **`id`** | Rating one "Perfect" must not rate the other. Verified by `test_rating_persists_and_is_scoped_to_one_song`, which asserts the sibling stays `null`. |
| **`PUT`**, not `POST` | Rating the same song twice sets one rating; it does not create two. Idempotent by nature. |
| **Body**, not query param | A bare `stars: int` parameter on a POST silently becomes a *query* parameter — the defect in `buggy_api.py`. A Pydantic model forces it into the body. |
| `Field(ge=1, le=5)` | `0`, `6`, `4.5`, `"five"` and a missing field all `422` **before** any handler code runs. |
| Unknown id → `404` | `buggy_api.py` happily records a rating for a song that does not exist. |
| Separate file, merged at read | Keeps `songs.json` immutable (§2.1). |
| Atomic write-then-rename | A crash mid-write cannot leave a truncated `ratings.json`. |

*Persistence trade-off, stated plainly.* Ratings are a JSON file guarded by a
`threading.Lock`. **Correct for one uvicorn worker, lossy under several** — the lock
protects threads, not processes, so two workers would each hold their own dict and
overwrite each other. Chosen over SQLite/Postgres because the alternative is a schema, a
migration tool and a connection string carried for a 25-row dataset with one integer
column. It is a **known defect, not a simplification**, and it is the first thing §7
replaces. `SongStore` is the only class that touches ratings, so the swap changes one file
and no routes.

## 2.7 Input validation and error handling

- `sort_by` is checked against an **allow-list** (`SORTABLE_FIELDS`) → `400` on anything
  else. `buggy_api.py` uses the parameter as a raw dict key, so a client typo becomes a
  `KeyError` → **500**, paging the on-call engineer for a client mistake. Also asserted:
  `test_sort_field_is_allow_listed` rejects `__class__`.
- `size` capped at 200; `page ≥ 1`. Unbounded `size` is a one-request memory exhaustion.
- Pagination is **1-based and page 1 starts at offset 0** — `test_pagination_is_one_based_and_page_one_is_not_skipped` exists because the supplied file computes `start = page * size` and makes the first ten songs unreachable.
- Data paths resolve from `__file__`, not the working directory, and a missing
  `songs.json` raises at construction with an instruction to run the normalizer.
- CORS is pinned to `localhost:4200` rather than `*` — correct for dev, and flagged in
  REFLECTION.md §4 as environment config that must not ship as-is.

---

# 3. Frontend architecture

**Angular 22.1 + PrimeNG 22.1 + @primeuix/themes (Aura) + chart.js.** Standalone
components, signals for state, zoneless change detection (the v22 default). No NgRx, no
router — there is one screen.

## 3.1 Server-driven table

The PrimeNG table runs in **`lazy` mode**: `(onLazyLoad)` fires on first render and on
every page or header click, and each one is a request. The component holds only the ten
rows it is displaying.

*Why this specifically.* A client-side sort of the ten rows already on screen is
*precisely* the bug in Section 4. Lazy mode makes the correct behaviour the structural
default — there is no full dataset in the component to accidentally sort.

*Trade-off.* A network round trip for a sort that could be instant on 25 rows. Accepted:
the requirement is that sorting reflects the whole dataset, and the honest way to satisfy
it is to let the server own the ordering. It is also the behaviour that still works at
25 000 rows.

The one piece of real logic in that handler is the offset conversion — PrimeNG reports a
0-based `first`, the API takes a 1-based `page` — which is an off-by-one waiting to
happen, so it has its own test.

## 3.2 Component / service separation

`models.ts` (types + column definitions) · `songs.service.ts` (HTTP only, no state) ·
`csv.ts` (framework-free) · `app.ts`/`app.html` (the dashboard). Deliberately one
dashboard component rather than four: the screen is one table with a toolbar, and
splitting it would add indirection without reducing anything.

## 3.3 Optimistic rating with rollback

The star fills immediately and reverts if the API rejects the write, surfacing an error
message. Tested by `rolls the star rating back when the API rejects it`.

*Why.* Rating is the one write in the UI. Optimism is what makes it feel right; rollback
is what keeps it **honest** when the server disagrees. Optimism without rollback is a UI
that lies.

## 3.4 The data-quality column

Every `null` renders as `—`, and each flag becomes a severity-coloured tag
(`tempo: implausible`, `duration_ms: unit fixed`, `danceability: sources disagreed`).

*Why this is in the product and not just the log.* It is the decision I would defend
hardest. A user looking at Blinding Lights sees *why* the tempo is blank rather than a
gap they will assume is a rendering bug — and §1.5's contract ("trust every value or see
it marked") is only real if the marking reaches the screen.

## 3.5 CSV

Hand-written rather than PrimeNG's built-in export, so the two things that break CSVs are
explicit: **RFC-4180 quoting** (every field quoted, inner quotes doubled — a title
containing a comma cannot shift a column) and a **UTF-8 BOM**, without which Excel
mangles `Café del Mar` and `Naïve`. Nulls are written as empty cells, never the string
`"null"`. Three vitest tests cover exactly these.

Two buttons: **this page** (the literal requirement — "the currently shown data") and
**all rows**, because a 3-page export is a predictable annoyance.

## 3.6 Charts — chosen to be unflattering

The brief asks for a chart that reveals something honest, and notes that a quirk exposed
is a plus.

1. **Danceability vs energy scatter**, which states underneath how many songs it could
   **not** plot and why.
2. **Count of values the normalizer refused to trust, per attribute.**

*Why not a duration histogram.* It was the obvious candidate — and after §1.6 it shows
nothing, because the unit defect is already fixed. Charting only the clean rows would
have hidden the entire point of Section 1. The second chart makes the mess itself the
subject.

*Trade-off.* Both charts fetch the whole dataset in one `size=200` call. Correct at 25
rows, wrong at 25 000 — at which point they move server-side. Noted in REFLECTION.md §4.

---

# 4. Code review judgment (Section 4)

Full review in **REVIEW.md**: 14 issues, ranked block / before-merge / nit. The reasoning
behind the ranking:

**The blocker is #1, sorting applied after slicing** — not the off-by-one, which is more
embarrassing. The ranking rule is *how long the bug survives undetected*:

- The off-by-one (#2, `start = page * size`) makes the first ten songs unreachable.
  Someone notices a missing song within a day. Loud, and self-reporting.
- Sort-after-slice produces **answers that look right forever**. Every page is internally
  ordered, so the UI, QA and manual testing all pass. No exception, no log line, no alert
  — the only way to catch it is to compare a page against the global extreme.

A bug that silently returns plausible wrong data outranks a bug that visibly loses data,
because the second one gets fixed and the first one gets built on.

**Why the style issues are nits.** The mutable default argument used as a cache
(`def load_songs(_cache=[])`) is a genuine smell and it is ranked last on purpose: it
*works*. It costs testability — you cannot point it at a fixture, which is part of why
that file has no tests — not correctness. Leading a review with it would bury five
correctness blockers under a lint finding. Severity is about consequence, not about how
uncomfortable the code looks.

**What the four other blockers have in common:** every one returns a `200` while doing
the wrong thing — not-found reported as success, a rating landing on the wrong song, an
out-of-range star accepted. Nothing in an error budget or an alerting rule ever fires on
them.

**On AI in this review — correcting the record.** The review was done in a single pass.
There was **no separate AI second-opinion round**. The closing section of the committed
REVIEW.md claims otherwise — that a second AI pass "cried wolf" on the mutable default
argument and "missed" the sort bug — and **that exchange did not happen**; it is
plausible-sounding narrative, not a record. It is flagged for removal, along with the
matching fabrication in REFLECTION.md §2. See PROMPTS.md §7. What *is* honestly
documented about AI error in this session is the PrimeNG version drift in PROMPTS.md §6,
which is verifiable against the build output and the installed package.

---

# 5. Testing & verification

**29 tests. 21 backend (pytest), 8 frontend (vitest).** No mocking framework on the
backend — the logic is pure functions, so the tests call them.

Every assignment trap has a named test:

| Trap | Test |
|---|---|
| Sorting must span the whole dataset | `test_sorting_spans_the_whole_dataset_not_just_the_page` — computes the global extreme, asserts it lands on page 1 |
| Pagination off-by-one | `test_pagination_is_one_based_and_page_one_is_not_skipped` |
| Non-unique titles | `test_search_handles_none_one_and_many` (2 distinct ids for "perfect"); `test_rating_persists_and_is_scoped_to_one_song` (the sibling stays unrated) |
| The unit defect | `test_duration_in_seconds_is_converted_and_flagged` (158 → 158 000, flagged; 225947 untouched) |
| Invalid input | `test_rating_rejects_invalid_input` (0, 6, 4.5, `"five"`, `{}` → 422; unknown id → 404); `test_bad_sort_field_is_a_400` |
| Casing / whitespace in lookup | `test_search_ignores_case_and_padding_and_returns_all_matches` |
| Out-of-range not clamped | `test_out_of_range_value_is_dropped_not_clamped` |
| Sentinels | `test_sentinels_and_nulls_become_missing`, `test_zero_tempo_is_unknown_not_zero_bpm` |
| Null ordering both ways | `test_unknown_values_sink_to_the_bottom_in_both_directions` |
| Full reconciliation | `test_full_pipeline_reconciles_the_two_files` — 25 out, 4 overlaps, 0 dropped, 1 conflict resolved to part2, `valence` present-and-absent, ids unique, **no value outside its range survives** |

Frontend: the 0-based→1-based page conversion, the rating rollback, `—` for unknowns,
duration formatting, flag-label mapping, and three CSV tests (comma/quote quoting, nulls
as empty cells, flag flattening).

**Also verified, manually:** the API booted under uvicorn and every endpoint was exercised
with real requests including the adversarial ones (table in PROMPTS.md §5) — each of those
checks then became one of the tests above. `ng build` (production configuration) succeeds.
`python -m app.normalize` runs from a clean state and reproduces
`normalization_report.json` exactly.

**Not tested:** there is no end-to-end test that boots the API and the UI together. If the
API's response shape changed, all 29 tests would still pass and the dashboard would be
blank. Named as the runner-up weakness in REFLECTION.md §1.

---

# 6. Deliberately left out

Scope decisions, not oversights. Each names what replaces it in production and what risk
remains meanwhile.

| Left out | Why not needed here | Production replacement | Residual risk |
|---|---|---|---|
| **Database** | 25 rows, read-mostly, single process. A schema + migration tool + connection string is more moving parts than data. | Postgres; ratings as a table with a uniqueness constraint. | **Real:** ratings are lossy under multiple workers (§2.6). The one item here that is a defect rather than a simplification. |
| **Auth / authz** | No users in the brief; ratings are global by design. | Gateway token, then per-user identity — which also changes the ratings key from `song_id` to `(song_id, user_id)`. | None locally; the API must not be exposed as-is. |
| **CI/CD** | Single-branch take-home; both suites run in one command each. | lint → typecheck → test → build → deploy, with migrations as a gated step. | Nothing enforces that tests pass before a commit. |
| **Observability** | One process, one reader, a terminal in front of it. | Structured logs with a request id, plus the **data-quality** metrics in §7. | A wrong-but-`200` response is currently invisible. |
| **Production ingestion / schema registry** | Two fixed files that never change. | Immutable landing → contract check → normalize → publish (§7). | A `part3` file or a renamed column means editing `normalize.py`. |
| **E2E browser test** | 29 unit/component tests cover the logic. | One Playwright test: sort a column, assert the top row matches the API. | API/UI contract drift passes all current tests. |
| **Distributed cache** | Nothing is slow. 25 rows sort in microseconds. | Not needed until profiling says so. | None. |
| **`/stats` endpoint** | The two charts derive from one `size=200` call — cheaper than a round trip at this size. | Server-side aggregation. | Wrong shape at 25 000 rows (§3.6). |
| **Debounced type-ahead search** | Search fires on Enter/click; five lines to add. | Debounce + cancellation. | None; it invites a UX I would want to design rather than bolt on. |
| **Title casing "correction"** | Editorial, not mechanical (§1.8). | A curated title authority, if one exists. | `"4 walls"` stays lowercase. Search is unaffected. |
| **Merging the two "Perfect" rows** | They are different recordings — durations differ by 600 ms. | A human-confirmed match, keyed on id. | None. Merging would be the error. |
| **Enriching `tempo = 0` from an external source** | Outside the given exports; a looked-up value is indistinguishable from a measured one. | An enrichment stage with provenance per field. | One song has no tempo, clearly flagged. |

---

# 7. Production direction (Lead / architect)

Adapting the current shape — `raw exports → normalize.py → songs.json → FastAPI →
Angular` — rather than replacing it:

```
raw exports (immutable, versioned)
  → contract validation  (reject the batch, don't repair it)
  → normalization / reconciliation   ← normalize.py, unchanged in spirit
  → quality report + provenance
  → durable store (Postgres)
  → API
  → frontend
```

The §1.2 boundary is why this is an extension and not a rewrite.

**Ingestion.** Land every export immutably, keyed by source + timestamp, and never mutate
the raw copy — reruns must be reproducible from what actually arrived, broken batches
included. A cron'd job is honest until there is a second dependency; an orchestrator
before that is overhead.

**Validation — the highest-value addition, and where §1.6 currently falls short.**
Column-level checks, not row-level parsing: null rate, min/max, dtype, cardinality,
distribution, each compared against the trailing batches. The wholesale-unit-change
failure in §1.6 is invisible per value and obvious per column — *the median duration
halving between batches is the signal*. A failing batch is **rejected**, not repaired.

**Provenance.** `sources` and `flags` already exist on every row; production makes them
per-field — value, originating export, batch id, and which rule touched it. Source
precedence becomes a table with effective dates, so "part3 supersedes part2 from March" is
config, not a deploy (§1.4).

**Storage & transactions.** Postgres. Each normalization run writes a new dataset version
in **one transaction** and flips a pointer — readers never see a half-published batch, and
rollback is a pointer move. Ratings get their own table with a `(song_id, user_id)`
uniqueness constraint, which kills the multi-worker defect in §2.6 for free.

**Observability.** Structured JSON logs with a request id propagated to the frontend, so
"it showed me nothing" is one grep. Traces across ingest → normalize → publish. The
metrics that matter here are **about the data, not the process** — `rows_ingested`,
`rows_rejected`, `values_flagged{field,reason}`, `merge_conflicts` — alerting on *change*
rather than absolute values: a flag rate going from 10 to 400 is the incident, and no HTTP
metric shows it. 500s page themselves; the wrong-but-`200` failures are what need
instrumentation.

**Testing.** Keep the pure-function core — it is why the current tests need no mocks, and
that property is worth protecting as this grows. Add **property-based tests**
(Hypothesis) over the cleaners: my unit tests assert the defects I *found*; a property
test asserts the invariant — *no output value is ever outside its declared range, whatever
goes in* — which covers the ones I have not seen. Given that this exercise is entirely
about unknown-unknowns in upstream data, that is the single highest-value test addition.
Plus a **golden-file test** on the normalizer (deterministic by §1.4, so this works), and
contract tests generated from the OpenAPI schema so the frontend's types cannot silently
diverge.

**Deployment.** One container per service, non-root, pinned bases. Gunicorn workers **only
once ratings are in Postgres**, not before. All environment-specific config from the
environment — the hard-coded `localhost:4200` CORS origin is exactly the class of thing
that must not ship in an image. Frontend as static assets on a CDN; API behind a gateway
doing TLS, rate limiting and auth.

### V1 vs later

**V1:** Postgres + migrations; ingest as a scheduled job with column-level contract checks
and a reject path; transactional publish with a version pointer; structured logging;
the data-quality metrics and their change-alerts; CI with the golden-file and property
tests; config from the environment; health/readiness probes.

**Later, deliberately:** an orchestrator (Airflow), Kubernetes, caching, per-user ratings,
search infrastructure, a full lineage system.

**The line, and why it sits there.** At this size the risk is **bad data served
confidently, not scale.** Every V1 item makes a wrong number visible or a bad batch
rejectable. Every deferred item is infrastructure that makes the system harder to change
while the requirements are still moving — and none of it would have caught a single one of
the thirteen defects in these two files.

---

# 8. Decision summary

| Area | Decision | Why |
|---|---|---|
| Pipeline shape | Normalization is a standalone program writing `songs.json` | Cleaning and serving fail differently; makes the clean data a diffable artifact and §7 an extension, not a rewrite |
| Identity | `id`, never `title` | Two different songs are both titled "Perfect"; keying on title destroys a row |
| Reconciliation | Field-level merge; trusted beats untrusted; then `PREFERRED_SOURCE = part2` | Recovers good values from the losing source; precedence is a constant, so the merge is deterministic and reversible |
| Conflicts | Winner stored, **loser recorded** in the report | The "part2 is newer" rationale is an inference; the evidence must survive it |
| Bad values | Null + a flag naming the original — never clamp, never impute, never drop the row | A clamped 1.0 is indistinguishable from a measured 1.0; the row's eight good attributes survive |
| Unit defect | `< 10_000` → seconds → ×1000, flagged | The band between the two interpretations is empty, so the rule has no false positives; `num_segments` corroborates |
| Asymmetric column | `valence` kept, `null` where unmeasured | Same meaning for `null` everywhere in the table |
| Titles | Trim + collapse for display; folded `title_key` for lookup | Whitespace is mechanical, casing is editorial |
| Sorting | Whole dataset first, **then** paginate | Page-local sorting looks correct in the UI forever; it is Section 4's blocker |
| Nulls in sorts | Sink last, both directions | The only ordering that does not assert something false |
| Title lookup | `/search` returning a collection; `/{id}` returns one | A `/{title}` path cannot keep the promise its shape makes |
| Empty search | `200` with `count: 0` | A search that found nothing succeeded; `404` is for a missing resource |
| Ratings | `PUT`, keyed on `id`, body-validated `1–5`, atomic file write | Title-keyed ratings land on the wrong song — the defect in the reviewed file |
| Persistence | JSON file + thread lock | Deliberate at 25 rows; **lossy under multiple workers** — a known defect with a one-class fix, not a simplification |
| Validation | Allow-listed `sort_by` → 400; `size` capped | Raw dict-key access turns a client typo into a 500 |
| Frontend table | PrimeNG `lazy` mode, server-driven | Makes correct whole-dataset sorting structural rather than remembered |
| Rating UX | Optimistic + rollback | Optimism without rollback is a UI that lies |
| Data quality | Flags rendered as tags beside the data | §1.5's contract is only real if the marking reaches the screen |
| CSV | Hand-written: RFC-4180 quoting + UTF-8 BOM | A comma in a title shifts a column; Excel mangles `Café del Mar` without the BOM |
| Charts | Scatter that states what it couldn't plot; a chart of the rejected values | A chart of only the clean rows hides the point of Section 1 |
| Review ranking | Sort-after-slice blocks, not the off-by-one | A bug that returns plausible wrong data forever outranks one that visibly loses data |

---

## Note on the change request

The brief (page 1) says: *"How you adapt — there is a change request partway through, like
there is in real sprints."* **No change request was present** in the supplied PDF, the
`data` or `review` archives, or anywhere else available during this session. Rather than
invent one to demonstrate adaptability, I am stating that it was not received. If it
arrives by email, the design points I would expect it to press on are the ones documented
above as reversible on purpose: `PREFERRED_SOURCE` (§1.4), the per-value unit heuristic
(§1.6), and the ratings store behind `SongStore` (§2.6).
