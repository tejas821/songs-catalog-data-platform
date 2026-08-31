# Songs — take-home

Two messy JSON exports of the same catalog, reconciled into one table you can trust,
served by a FastAPI backend and browsed through an Angular 22 + PrimeNG dashboard.

**The tour:** `normalize.py` merges the two column-oriented exports on `id` (never on
title — two different songs here are both called "Perfect"), cleans every field against
its declared range, and writes `data/songs.json`. Values it can't trust become `null`
with a flag saying why, rather than being clamped or imputed — so every non-null value
in the table is a value a consumer can rely on, and every gap is explained. The API sorts
the **whole** dataset before paginating, looks titles up case- and whitespace-insensitively
returning *all* matches, and persists 1–5 star ratings keyed by id. The dashboard shows
the flags next to the data, so the normalizer's judgement calls are visible in the
product and not just in a log file. 29 tests cover the cleaning rules, the sort/page/search
logic, the API contract, and the frontend's page math and CSV quoting.

The reasoning lives in **[DECISIONS.md](DECISIONS.md)**, the PR review of the supplied
`buggy_api.py` in **[REVIEW.md](REVIEW.md)**, the AI log in **[PROMPTS.md](PROMPTS.md)**,
and the answers to Section 6 in **[REFLECTION.md](REFLECTION.md)**.

---

## Run it

Prerequisites: **Python 3.10+** and **Node 20+**. Nothing else — no database, no Docker.
Verified on CPython 3.10, 3.11, 3.13 and 3.14 (`requirements.txt` uses version floors so
pip resolves a prebuilt wheel on each — an exact pin of pydantic would try to compile
pydantic-core from Rust on 3.14 and fail).

### 1. Backend (port 8000)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m app.normalize        # reads data/songs_part*.json -> data/songs.json
uvicorn app.main:app --reload  # http://localhost:8000
```

`python -m app.normalize` prints exactly what it did — how many rows came in, how many
songs came out, which values it rejected and why. Full detail lands in
`data/normalization_report.json`. Interactive API docs: <http://localhost:8000/docs>.

### 2. Frontend (port 4200)

In a second terminal, with the backend running:

```bash
cd frontend
npm install
npm start                      # http://localhost:4200
```

### 3. Tests

```bash
cd backend  && python -m pytest -q      # 21 tests
cd frontend && npm test                 # 8 tests (vitest)
```

---

## API

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/songs?page=1&size=10&sort_by=title&order=asc` | Sorts the **entire** dataset, then cuts the page. Unknown values sort last in both directions. Bad `sort_by` → `400`; `size` capped at 200. |
| `GET` | `/api/songs/search?title=perfect` | Case- and whitespace-insensitive. Always returns a list. `match_type` is `exact`, `partial` or `none`; zero matches is a `200`, not a `404`. |
| `GET` | `/api/songs/{id}` | The single-song route. `404` when the id is unknown. |
| `PUT` | `/api/songs/{id}/rating` | Body `{"stars": 1..5}`. Anything else → `422`; unknown id → `404`. Persisted to `data/ratings.json`. |
| `DELETE` | `/api/songs/{id}/rating` | Clears a rating. |
| `GET` | `/api/health`, `/api/meta` | Row count; sortable field list. |

Try the interesting ones:

```bash
curl "localhost:8000/api/songs?page=1&size=3&sort_by=tempo&order=desc"
curl --get --data-urlencode "title=  4 WALLS " localhost:8000/api/songs/search   # finds "4 walls"
curl "localhost:8000/api/songs/search?title=perfect"                             # two different songs
curl -X PUT localhost:8000/api/songs/0tgVpDi06FyKpA1z0VMD4v/rating \
     -H 'content-type: application/json' -d '{"stars":9}'                        # 422
```

## Dashboard

Table with server-driven paging (10/page) and sortable columns, a title search that
handles no-match and multi-match honestly, star ratings that write back to the API,
CSV export of the current page or of all rows, and two charts: danceability vs energy
(stating how many songs it could **not** plot) and a count of the values the normalizer
refused to trust, per attribute.

## Layout

```
backend/
  app/normalize.py     merge + clean the two exports        -> data/songs.json
  app/store.py         sort / paginate / search + ratings   (pure functions)
  app/main.py          FastAPI routes (thin)
  tests/               21 tests, no mocking framework
frontend/src/app/
  models.ts            Song + column definitions
  songs.service.ts     HTTP client
  csv.ts               CSV export with RFC-4180 quoting
  app.ts / app.html    the dashboard
data/                  the two source exports + generated songs.json, ratings.json, report
review/buggy_api.py     the file reviewed in REVIEW.md (unmodified)
```

## Known limits

Ratings are a JSON file behind a thread lock: correct for one uvicorn worker, lossy
under several. Deliberate at 25 rows, and the first thing I'd change — reasoning and the
fix in [REFLECTION.md](REFLECTION.md).
