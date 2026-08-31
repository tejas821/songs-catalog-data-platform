# REVIEW.md — code review of `review/buggy_api.py`

Reviewed as a PR. It runs, it returns JSON, and a manual click-through looks fine —
which is exactly why the two worst bugs would ship.

**Verdict: request changes.** Blocking on #1–#5.

---

## Blockers

### 1. Sorting is applied *after* pagination, so it only sorts the visible page
```python
page_items = songs[start:end]
page_items = sorted(page_items, key=lambda s: s[sort_by], reverse=reverse)
```
**What's wrong:** the slice happens first. `sorted` then reorders the ten rows that
were already selected.
**Impact:** `?sort_by=tempo&order=desc` does not return the fastest songs — it returns
an arbitrary ten songs, neatly ordered among themselves. Every page looks correct in
isolation, so this survives manual testing and QA; it only shows up when someone
compares page 1 against the real maximum. Any UI built on this ("top rated", "longest
tracks") is silently wrong.
**Fix:** sort the full list, then slice. One line moved:
```python
songs = sorted(load_songs(), key=..., reverse=reverse)[start:end]
```
*This is the bug I'd single out. It is the one a blind paste-and-ship misses.*

### 2. Off-by-one: page 1 skips the first page of data
```python
start = page * size      # page=1, size=10  ->  start=10
```
**Impact:** with the documented default `page=1`, the first ten songs are unreachable
through the API. To see them a client has to ask for page 0. Nobody notices until a
user asks where a song went.
**Fix:** `start = (page - 1) * size`.

### 3. Title lookup can only ever return one song, and reports failure as success
```python
@app.get("/songs/{title}")
...
    if song["title"] == title: return song
return {"error": "not found"}
```
**Three problems in five lines.**
- Exact string equality: `"perfect"`, `" Perfect "` and `"PERFECT"` all miss. Real
  users type all three; our own data contains a title stored as `" 4 walls  "`.
- Returns the **first** match. Our dataset has two *different* songs both titled
  "Perfect" (ids `0tgVpDi06Fy…` and `7dNsHhGeGU5…`). One of them is permanently
  invisible through this endpoint.
- A miss returns HTTP **200** with an `error` key. Any client that checks status
  codes — every HTTP library's `raise_for_status`, every retry policy, every
  monitoring rule — treats "not found" as success.

**Fix:** identify single songs by `id` (`GET /songs/{id}`, 404 on miss); make title a
*search* that normalizes case/whitespace and returns a **list**, so "two matches" is a
representable answer rather than a silent truncation.

### 4. Ratings are keyed by title, and they mutate the cached dataset
```python
ratings[title] = stars
for song in songs:
    if song["title"] == title: song["rating"] = stars
```
**Impact:** rating one "Perfect" rates both — a user's 1-star lands on someone else's
song. The write also mutates the objects inside `_cache`, so the API's idea of the
source data now differs from `songs.json` for the rest of the process's life; a later
bug fix that reloads the file will "lose" ratings that were never persisted anyway.
And `ratings` is written but never read, so it does nothing at all.
**Fix:** key ratings on `id`, keep them in their own store, and merge them onto the
song at read time instead of writing into the cache.

### 5. `stars` is an unvalidated query parameter on a POST
```python
def rate_song(title: str, stars: int):
```
**Impact:** a bare scalar on a POST becomes a **query** parameter, so the documented
"rate a song" call is `POST /songs/X/rating?stars=-999` — and `-999` is accepted, as
are `0`, `6` and `100000`. The stated requirement is 1–5. There is also no existence
check: rating a song that doesn't exist returns `200 {"title": "asdf", "stars": 3}`.
**Fix:** a Pydantic body model with `Field(ge=1, le=5)`, and 404 when the id is unknown.

---

## Should fix before merge

### 6. `sort_by` is an unvalidated dictionary key
`s[sort_by]` raises `KeyError` on anything that isn't a column — FastAPI turns that
into a **500**, not a 400, so client mistakes page the on-call engineer. Worse on real
data: `sorted` raises `TypeError` the moment one row's value is `None` (our cleaned
data has nulls by design) or the column mixes strings and numbers. **Fix:** an
allow-list of sortable columns, `400` for anything else, and an explicit rule for
where unknown values sort.

### 7. `/stats/duration` is fragile *and* wrong on this dataset
```python
avg_seconds = total / len(songs)
```
Empty dataset → `ZeroDivisionError` → 500. Any row missing `duration_ms` → `TypeError`.
And even on a full read it reports a number that is simply false: three rows in
`songs_part2.json` carry **seconds** in a column named `duration_ms` (158, 270, 356),
so this averages 158 ms alongside 264 000 ms and pulls the mean down. **Fix:** compute
over rows with a known duration, guard the empty case, return the count you averaged
over — and fix the units upstream in normalization, not here.

### 8. "Persists across requests" isn't actually persistence
`ratings = {}` is module-level state. It survives requests within one process and
nothing else: a restart wipes it, and under more than one uvicorn worker each process
has its own copy, so a rating written on worker A is invisible on the next request if
it lands on worker B. That reads as a random data-loss bug in production. **Fix:** a
file or table write; at minimum, say out loud that it's in-memory only.

### 9. `size` is unbounded
`?size=1000000` builds one enormous response. Cheap way to exhaust memory.
**Fix:** cap it (`Query(10, ge=1, le=200)`).

### 10. No CORS configuration
The stated goal is a browser dashboard on another origin. Every fetch from it fails
in the browser while `curl` works — a confusing hour for whoever builds the frontend.

---

## Nits

### 11. Mutable default argument used as a cache
`def load_songs(_cache=[])` works by accident of Python semantics. It's process-global
hidden state with no way to invalidate it and no way to point it at a fixture, which
is a real reason the file has no tests. **Fix:** a small store object injected with
`Depends`, overridable in tests.

### 12. `open("songs.json")` is relative to the current working directory
Works when launched from the repo root, 500s under systemd, Docker or a different
`cd`. **Fix:** resolve from `__file__`.

### 13. The file is read on the *first request*, not at startup
A missing or malformed data file becomes a 500 for whichever user arrives first,
instead of a container that refuses to start. Fail fast.

### 14. No response models, no explicit status codes, no tests
Every endpoint returns "whatever keys are in the dict", so the OpenAPI schema is
empty and the contract is undocumented. And the module docstring still calls the file
`songs_api.py`.

---

## Ranking

| Priority | Issues | Why |
|---|---|---|
| **Block** | 1, 2, 3, 4, 5 | Silent wrong answers and data corruption. Every one returns a `200` while doing the wrong thing, so no alert fires. |
| **Before merge** | 6, 7, 8, 9, 10 | 500s from ordinary client input, a statistic that is numerically false, and "persistence" that isn't. |
| **Nit** | 11, 12, 13, 14 | Real, but they cost maintainability rather than correctness. |

If I could only get one thing changed: **#1**. #2 is more embarrassing but someone will
notice missing songs within a day. #1 produces answers that look right forever.

---

## Note on using AI for this review

I ran the file past an AI reviewer as a second pass. Worth recording honestly:

- **It cried wolf on the nits.** The mutable default argument was its headline finding,
  written up with more urgency than it deserves — it's a real smell, but here it works,
  and shipping it costs testability, not correctness. Ranked as a blocker it would have
  buried the actual blockers.
- **It missed #1 on the first pass.** The code contains a `sorted()` call with a `key`
  and a `reverse`, so it reads as "sorting is handled". The bug is the *order of two
  statements*, not a missing one, and the AI graded it as correct. I found it by asking
  "what would `?sort_by=tempo&order=desc&page=1` actually return on 25 rows" rather
  than by reading the function.
- **It was genuinely good at #3 and #5** — the HTTP-semantics problems (200 on error,
  scalar-becomes-query-param) are pattern matching, which is what it's best at.

The lesson I took: AI review is strong on "this line is wrong" and weak on "these two
correct lines are in the wrong order". The second kind is where the money is.
