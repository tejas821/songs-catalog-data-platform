"""
The data layer: load the normalized songs, hold the ratings, and provide the
three pure operations the API needs (sort / paginate / search).

Everything below is deliberately plain data + plain functions.  They are pure,
so the unit tests exercise the real logic without spinning up a web server.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SONGS_FILE = DATA_DIR / "songs.json"
RATINGS_FILE = DATA_DIR / "ratings.json"

# Only these may be used as `sort_by`.  An allow-list, not `getattr`, so a
# caller cannot sort by (or probe for) something that isn't a real column.
SORTABLE_FIELDS = ("index", "id", "title", "danceability", "energy", "mood",
                   "acousticness", "tempo", "valence", "duration_ms",
                   "num_sections", "num_segments", "rating")
TEXT_FIELDS = ("id", "title")

MAX_PAGE_SIZE = 200


def normalize_title(text: str) -> str:
    """The same key the normalizer builds: case-, padding- and spacing-insensitive."""
    return re.sub(r"\s+", " ", text or "").strip().casefold()


# --------------------------------------------------------------------------- #
# Pure operations
# --------------------------------------------------------------------------- #

def sort_songs(songs, sort_by="title", order="asc"):
    """
    Sort the WHOLE list (the caller paginates afterwards, never before).

    Rows whose value is unknown (None -- a value we refused to trust during
    normalization) always sink to the bottom, in both directions.  Mixing them
    into the ordering would either crash on None comparison or quietly imply
    that "unknown" is smaller than every real value.
    """
    if sort_by not in SORTABLE_FIELDS:
        raise ValueError(f"cannot sort by {sort_by!r}; allowed: {', '.join(SORTABLE_FIELDS)}")
    if order not in ("asc", "desc"):
        raise ValueError("order must be 'asc' or 'desc'")

    known = [s for s in songs if s.get(sort_by) is not None]
    unknown = [s for s in songs if s.get(sort_by) is None]
    key = (lambda s: s[sort_by].casefold()) if sort_by in TEXT_FIELDS else (lambda s: s[sort_by])
    known.sort(key=key, reverse=(order == "desc"))
    return known + unknown


def paginate(items, page=1, size=10):
    """1-based paging. Returns (page_items, meta)."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise ValueError(f"size must be between 1 and {MAX_PAGE_SIZE}")

    total = len(items)
    total_pages = max(1, -(-total // size))          # ceil division
    start = (page - 1) * size                        # page 1 starts at 0
    return items[start:start + size], {
        "page": page, "size": size, "total": total, "total_pages": total_pages,
    }


def search_by_title(songs, query):
    """
    Titles are not unique and users don't type exact casing or spacing, so:
      1. try an exact match on the normalized title -- may return SEVERAL songs;
      2. if nothing matched, fall back to a normalized substring match.
    The response says which of the two happened, so the UI can be honest about it.
    """
    needle = normalize_title(query)
    if not needle:
        return [], "empty_query"

    exact = [s for s in songs if s["title_key"] == needle]
    if exact:
        return exact, "exact"

    partial = [s for s in songs if needle in s["title_key"]]
    return partial, "partial" if partial else "none"


# --------------------------------------------------------------------------- #
# Store: songs (read-only) + ratings (read/write, persisted)
# --------------------------------------------------------------------------- #

class SongStore:
    """
    Songs are loaded once and never mutated.  Ratings live in their own file and
    are keyed by song id -- NOT by title, because two different songs here share
    the title "Perfect" and rating one must not rate the other.
    """

    def __init__(self, songs_file=SONGS_FILE, ratings_file=RATINGS_FILE):
        self.songs_file = Path(songs_file)
        self.ratings_file = Path(ratings_file)
        self._lock = Lock()
        if not self.songs_file.exists():
            raise FileNotFoundError(
                f"{self.songs_file} not found -- run `python -m app.normalize` first.")
        self._songs = json.loads(self.songs_file.read_text(encoding="utf-8"))
        self._ratings = (json.loads(self.ratings_file.read_text(encoding="utf-8"))
                         if self.ratings_file.exists() else {})

    def all_songs(self):
        """Songs with their current rating attached (None when never rated)."""
        return [{**song, "rating": self._ratings.get(song["id"])} for song in self._songs]

    def get(self, song_id):
        return next((s for s in self.all_songs() if s["id"] == song_id), None)

    def set_rating(self, song_id, stars):
        """Validated by the caller; persisted immediately so it survives a restart."""
        with self._lock:
            if not any(s["id"] == song_id for s in self._songs):
                return None
            self._ratings[song_id] = stars
            self._save()
        return self.get(song_id)

    def clear_rating(self, song_id):
        with self._lock:
            self._ratings.pop(song_id, None)
            self._save()
        return self.get(song_id)

    def _save(self):
        tmp = self.ratings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._ratings, indent=2), encoding="utf-8")
        tmp.replace(self.ratings_file)          # atomic: never a half-written file
