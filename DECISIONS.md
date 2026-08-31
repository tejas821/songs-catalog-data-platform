# DECISIONS.md

## Part 1 — What's actually wrong with the data

Before deciding anything I diffed the two files field by field. Everything below is
something I found in the data, not a hypothetical:

| # | Where | What |
|---|---|---|
| 1 | part1 `danceability["0"]`, `tempo["0"]` | numbers stored as **strings** (`"0.521"`, `"108.73"`) |
| 2 | part1 `danceability["3"]` | **1.42** — outside the [0,1] range the field claims |
| 3 | part2 `acousticness["7"]` | **-0.05** — same problem, other end |
| 4 | part1 `energy` | key `"2"` is simply **absent** — a hole in a column, not a null |
| 5 | part1 `energy["10"]` | the string **`"N/A"`** used as a null |
| 6 | part1 `acousticness["6"]` | literal `null` |
| 7 | part1 `tempo["8"]` | **0** BPM (Blinding Lights) — a sentinel wearing a plausible type |
| 8 | part2 `duration_ms` rows 5, 9, 11 | **158, 270, 356** — these are *seconds* in a column named `duration_ms` |
| 9 | part1 `title["1"]` | `" 4 walls  "` — leading/trailing/double whitespace and lowercased |
| 10 | both files | 4 ids appear in **both** exports (indices 12–15 of part1 = 0–3 of part2) |
| 11 | the overlap | one real disagreement: `danceability` for *Never Gonna Give You Up* is 0.727 in part1, 0.74 in part2 |
| 12 | part2 | rows 4 and 12 are **two different songs both titled "Perfect"** (different ids, different durations) |
| 13 | part2 only | carries a `valence` column that part1 doesn't have |

16 + 13 rows in → **25 distinct songs** out.

---

## The rules I chose, and why

### Identity: songs are keyed by `id`, never by title
Item 12 settles this. Two rows share the title "Perfect" and are genuinely different
recordings (263 400 ms vs 264 000 ms, different ids). Any pipeline keyed on title
would merge them into one song and destroy a row. So: `id` is the primary key, titles
are a *display* attribute that happens to collide.

### Conflicts: a trusted value beats an untrusted one; then part2 wins
Field-level merge, in this order:
1. If one file has a value we trust and the other doesn't, the trusted one wins —
   regardless of which file it came from. This is why merging is done per-field and not
   per-row: it recovers good values from the "losing" source.
2. If both are trusted and equal, nothing to decide.
3. If both are trusted and *differ* (item 11 — the only real case), **part2 wins**, and
   the discarded value is written into `normalization_report.json`.

Why part2: it carries a column part1 doesn't (`valence`), which is what a schema looks
like after it has been extended — so it is the later pipeline. That is an inference,
not a fact, which is exactly why the losing value is recorded rather than dropped. If
someone tells me part1 is actually newer, one constant (`PREFERRED_SOURCE`) changes.

**Trade-off accepted:** the two danceability values differ by 0.013. Picking either is
defensible; what isn't defensible is picking one *silently*. The song carries a
`danceability:conflict` flag and the discarded value is in the report.

### Bad values: drop the **value**, keep the **row**
Items 2–7. Every one of these becomes `null` plus a flag such as
`danceability:out_of_range(1.42)`.

- **Not clamp.** Clamping 1.42 to 1.0 produces a number that is indistinguishable from
  a measured 1.0 — it launders a data-quality problem into a fact. The upstream bug
  also stops being visible, so it never gets fixed.
- **Not impute.** With 25 rows, a column mean is noise, and an imputed value is a lie
  that survives into every downstream average.
- **Not drop the row.** A song with a broken `danceability` still has eight other good
  attributes. Dropping it loses more information than it saves.

So: **the output contains only values a consumer can trust, and everything else is
explicitly `null` with a reason attached.** That's the "internally consistent" bar from
the brief. The dashboard renders nulls as `—` and shows the reason as a tag, so the
gaps are visible in the product rather than buried in a log.

`tempo = 0` (item 7) is treated as unknown rather than as a tempo, because 0 BPM is not
a thing. The rule is a plausibility band (20–300 BPM), not a special case for zero — the
next export will invent a different sentinel.

### The unit bug: detected by magnitude, converted, and flagged
Item 8. Three rows in part2 hold 158, 270 and 356 in `duration_ms`. Read as
milliseconds those are quarter-second songs; read as seconds they are 2:38, 4:30 and
5:56 — ordinary track lengths, and consistent with the `num_segments` on those rows
(560, 1010, 1490 — mid-sized tracks, not quarter-second ones).

**Detection rule:** `0 < duration_ms < 10_000` → the value is seconds → multiply by
1000 and attach `duration_ms:seconds_converted(158s)`. A 10-second threshold is far
below any real track and far above any track length expressed in seconds, so the band
between them is empty and the rule has no false positives on plausible data.

I chose to **convert rather than null** — unlike every other bad value above — because
here I can recover the true value with confidence, and because the flag keeps the
correction auditable. Nulling three durations would have made "average song length"
quietly unrepresentative instead of quietly wrong.

Storage: **always milliseconds**, matching the column name. The frontend formats to
`m:ss`; the API never returns two different units.

### The extra column: keep it, null-filled
Item 13. `valence` is kept as a first-class column, `null` for the 21 songs that only
appear in part1. Dropping it would throw away real data because one pipeline is older;
back-filling it would be invention. `null` here means "this export didn't measure it",
which is the same thing `null` means everywhere else in the table — one meaning, one
representation.

### Titles: tidy for display, normalize for lookup
Item 9. Stored twice: `title` is whitespace-collapsed and trimmed for display (casing
preserved — `" 4 walls  "` → `"4 walls"`, not title-cased, because I don't know that
the lowercase spelling is wrong), and `title_key` is the case-folded version used for
every lookup. Search therefore ignores case, padding and double spaces without doing
string gymnastics at query time.

---

## API decisions

**`GET /api/songs?page&size&sort_by&order`** — sorting is applied to the *entire*
dataset server-side and the page is cut afterwards. This is deliberate and tested
(`test_sorting_spans_the_whole_dataset_not_just_the_page`); it is the bug in
`buggy_api.py` and it is the one the frontend cannot compensate for. `sort_by` is
checked against an allow-list → `400`, never a 500. `size` is capped at 200.

**Unknown values sort last, in both directions.** Sorting `None` alongside numbers
either crashes or implies unknown < everything. Sinking them to the bottom is the only
option that doesn't state something false — ascending *and* descending.

**Title lookup is `GET /api/songs/search?title=…`, not `GET /api/songs/{title}`.**
Titles aren't unique (item 12), so a path that looks like it identifies one song but
can match two is a lie in the URL shape. Search returns `{count, match_type, matches[]}`
— a list, always. `/api/songs/{id}` is the route that returns exactly one song, and
404s honestly.

**Zero matches is `200` with `count: 0`, not `404`.** A search that found nothing
succeeded; it answered the question. `404` is reserved for `/api/songs/{id}` where the
*resource* genuinely doesn't exist. `match_type` (`exact` / `partial` / `none`) tells
the UI which of the three happened, so it can say "no exact match, showing 2 songs
containing 'perf'" instead of pretending a fuzzy hit was an exact one.

**Ratings: `PUT /api/songs/{id}/rating` with a JSON body.** PUT because rating the same
song twice sets one rating rather than adding two. Keyed on `id` so rating one
"Perfect" doesn't rate the other. Validated by Pydantic (`ge=1, le=5`), so `0`, `6`,
`4.5` and `"five"` are rejected with a `422` before any handler code runs, and an
unknown id is a `404`. Persisted to `data/ratings.json` via atomic write-then-rename,
so a crash mid-write can't leave a truncated file.

**Storage is JSON files, not a database.** 25 rows, read-mostly, single process. A
database here would be ceremony: a schema, a migration, a connection string and a
container, all to hold a table that fits in a tweet. The store is one class
(`SongStore`) behind which a real database would go with no route changes. Trade-off
accepted: **ratings are not safe under multiple uvicorn workers** — two processes would
each hold their own copy and overwrite each other's file. Documented rather than
hidden; the fix is one class, in REFLECTION.md.

**Sorting/paging/searching are pure functions in `store.py`.** The route handlers only
validate and shape. That is what lets the tests exercise the real logic without a web
server, and it's why there are 21 backend tests and no mocking framework.

---

## Frontend decisions

**Angular 22 + PrimeNG, table in `lazy` mode.** The table never sorts or pages
client-side; every header click and page change is a request. That's the only way the
"sort the whole dataset" requirement can be honest with 25 rows on 3 pages — a
client-side sort of 10 visible rows is precisely the bug from Section 4.

**Nulls render as `—` and carry a tag explaining why.** The data-quality column is the
part of this UI I'd defend hardest: the normalizer's judgement calls are visible in the
product, not just in a log file. A user looking at Blinding Lights sees "tempo:
implausible", not a blank cell they'll assume is a rendering bug.

**Ratings are optimistic with rollback** — the star fills immediately and reverts if
the API rejects it. Cheap, and it keeps the UI honest when the backend disagrees.

**Two charts, both unflattering.** A danceability-vs-energy scatter that states how
many songs it *couldn't* plot, and a bar chart counting the values the normalizer
refused to trust per attribute. The brief asked for a chart that reveals something
honest; a chart of the good rows only would have hidden the whole point of Section 1.

**CSV: "this page" and "all rows".** Written by hand rather than using PrimeNG's
built-in export, so quoting and the UTF-8 BOM are explicit — `Café del Mar` and
`Naïve` open correctly in Excel, and a title containing a comma can't shift a column.

---

## What I deliberately left out

- **No database, no ORM, no migrations.** 25 rows. See the trade-off above.
- **No auth, no rate limiting.** Not asked for; would be the first thing added.
- **No `/stats` endpoint.** The frontend computes its two charts from one `size=200`
  call. At 25 rows this is cheaper than a round trip; at 25 000 rows it's the wrong
  call and the charts move server-side.
- **No debounced type-ahead search.** Search fires on click or Enter. Debouncing is
  five lines but it invites a "search as you type" UX I'd want to design properly.
- **Title casing is not "corrected".** `"4 walls"` stays lowercase. I can trim
  whitespace with confidence; I can't title-case without inventing an editorial rule
  that will mangle `"iPhone"`-style names on the next batch.
- **Ratings have no user identity.** One global rating per song, because the brief
  says "a user" and there are no users. Per-user ratings change the storage shape.
- **The two `Perfect` rows are left as two rows.** They are different recordings. I'd
  only merge them if a human confirmed it, and even then by id, not by title.
