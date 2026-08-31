"""
REST API over the normalized songs table.

The routes are thin: they validate input, call a pure function from store.py,
and shape the response.  All the logic worth testing lives in store.py.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .store import MAX_PAGE_SIZE, SORTABLE_FIELDS, SongStore, paginate, search_by_title, sort_songs

app = FastAPI(
    title="Songs API",
    version="1.0.0",
    description="Normalized song catalog: paging, whole-dataset sorting, title lookup, ratings.",
)

# The Angular dev server runs on a different origin.  Locked to localhost rather
# than "*" so this file isn't the thing that has to change before deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_store: SongStore | None = None


def get_store() -> SongStore:
    """Built once, lazily, and overridable in tests via dependency_overrides."""
    global _store
    if _store is None:
        _store = SongStore()
    return _store


class RatingIn(BaseModel):
    # Pydantic rejects 0, 6, 4.5 and "four" before the handler ever runs.
    stars: int = Field(..., ge=1, le=5, description="Whole stars, 1 to 5.")


@app.get("/api/health")
def health(store: SongStore = Depends(get_store)):
    return {"status": "ok", "songs": len(store.all_songs())}


@app.get("/api/songs")
def list_songs(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
    sort_by: str = Query("title"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    store: SongStore = Depends(get_store),
):
    """Sort the entire dataset first, then cut the requested page out of it."""
    try:
        ordered = sort_songs(store.all_songs(), sort_by, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    items, meta = paginate(ordered, page, size)
    return {**meta, "sort_by": sort_by, "order": order, "items": items}


@app.get("/api/songs/search")
def search_songs(
    title: str = Query(..., min_length=1),
    store: SongStore = Depends(get_store),
):
    """
    Title lookup. Zero matches is a legitimate answer to a search, not a server
    error, so this is a 200 with count 0 -- and `match_type` tells the caller
    whether it got an exact hit, a fuzzy fallback, or nothing.
    """
    matches, match_type = search_by_title(store.all_songs(), title)
    return {"query": title, "match_type": match_type, "count": len(matches), "matches": matches}


@app.get("/api/songs/{song_id}")
def get_song(song_id: str, store: SongStore = Depends(get_store)):
    """By id, because a title can belong to more than one song."""
    song = store.get(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail=f"no song with id {song_id!r}")
    return song


@app.put("/api/songs/{song_id}/rating")
def rate_song(song_id: str, payload: RatingIn, store: SongStore = Depends(get_store)):
    """PUT, not POST: rating the same song twice sets one rating, it doesn't add two."""
    song = store.set_rating(song_id, payload.stars)
    if song is None:
        raise HTTPException(status_code=404, detail=f"no song with id {song_id!r}")
    return song


@app.delete("/api/songs/{song_id}/rating")
def unrate_song(song_id: str, store: SongStore = Depends(get_store)):
    song = store.clear_rating(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail=f"no song with id {song_id!r}")
    return song


@app.get("/api/meta")
def meta():
    """What the frontend needs to build its column headers."""
    return {"sortable_fields": list(SORTABLE_FIELDS), "max_page_size": MAX_PAGE_SIZE}
