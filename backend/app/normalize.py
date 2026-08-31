"""
Normalize & reconcile the two column-oriented song exports into one clean,
row-oriented table.

Design in one paragraph:
  Each source file is first turned into rows.  Every field is then run through a
  small "cleaner" function that returns (value, flag).  A value that cannot be
  trusted becomes None and picks up a flag instead of being silently guessed --
  a downstream consumer can therefore trust every non-null value in the output.
  Rows from the two files are merged on `id` (titles are NOT unique), field by
  field: a trusted value always beats an untrusted one, and when both files are
  trusted but disagree, part2 wins and the disagreement is recorded.

Run:  python -m app.normalize
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SOURCES = {"part1": DATA_DIR / "songs_part1.json", "part2": DATA_DIR / "songs_part2.json"}
OUT_FILE = DATA_DIR / "songs.json"
REPORT_FILE = DATA_DIR / "normalization_report.json"

# part2 is the newer pipeline (it carries `valence`, which part1 lacks), so it
# wins ties.  See DECISIONS.md.
PREFERRED_SOURCE = "part2"

# Anything shorter than this is not a song length in milliseconds; it is a song
# length in seconds that was written into a column named `duration_ms`.
SECONDS_THRESHOLD_MS = 10_000

# Values upstream uses to mean "we don't have this".
NULL_TOKENS = {"", "n/a", "na", "null", "none", "-", "?"}


# --------------------------------------------------------------------------- #
# Field cleaners.  Each returns (clean_value, flag_or_None).
# --------------------------------------------------------------------------- #

def _to_float(raw):
    """Accept 0.5 and "0.5" alike; reject sentinels and junk."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        if raw.strip().lower() in NULL_TOKENS:
            return None
        try:
            return float(raw.strip())
        except ValueError:
            return None
    return None


def clean_unit_interval(raw, field):
    """danceability / energy / acousticness / valence -- must land in [0, 1]."""
    value = _to_float(raw)
    if value is None:
        return None, f"{field}:missing"
    if not 0.0 <= value <= 1.0:
        # Dropping the value (not the row) keeps the other 8 good attributes of
        # this song usable.  Clamping would invent data that looks legitimate.
        return None, f"{field}:out_of_range({value})"
    return round(value, 6), None


def clean_tempo(raw):
    """BPM. 0 is the upstream's way of saying 'unknown', not a real tempo."""
    value = _to_float(raw)
    if value is None:
        return None, "tempo:missing"
    if not 20.0 <= value <= 300.0:
        return None, f"tempo:implausible({value})"
    return round(value, 3), None


def clean_duration_ms(raw):
    """
    The unit bug.  A handful of rows in part2 (158, 270, 356) are seconds sitting
    in a column named duration_ms.  Detect by magnitude -- no real track is under
    10 seconds -- convert to milliseconds, and flag the row so the fix is visible.
    """
    value = _to_float(raw)
    if value is None or value <= 0:
        return None, "duration_ms:missing"
    if value < SECONDS_THRESHOLD_MS:
        return int(value * 1000), f"duration_ms:seconds_converted({int(value)}s)"
    return int(value), None


def clean_int(raw, field, low=1, high=100_000):
    value = _to_float(raw)
    if value is None or not low <= value <= high:
        return None, f"{field}:missing"
    return int(value), None


def clean_mood(raw):
    """A 0/1 flag in both files. Anything else is not a mood we can interpret."""
    value = _to_float(raw)
    if value in (0.0, 1.0):
        return int(value), None
    return None, "mood:missing"


def clean_title(raw):
    """
    Titles arrive with stray padding and inconsistent casing (" 4 walls  ").
    Store the tidied display title, and a separate search key so lookup does not
    have to care about case, padding or double spaces.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, None, "title:missing"
    display = re.sub(r"\s+", " ", raw).strip()
    return display, display.casefold(), None


# --------------------------------------------------------------------------- #
# Read + clean one source file
# --------------------------------------------------------------------------- #

CLEANERS = {
    "danceability": lambda v: clean_unit_interval(v, "danceability"),
    "energy": lambda v: clean_unit_interval(v, "energy"),
    "acousticness": lambda v: clean_unit_interval(v, "acousticness"),
    "valence": lambda v: clean_unit_interval(v, "valence"),
    "tempo": clean_tempo,
    "duration_ms": clean_duration_ms,
    "mood": clean_mood,
    "num_sections": lambda v: clean_int(v, "num_sections"),
    "num_segments": lambda v: clean_int(v, "num_segments"),
}

FIELDS = ["danceability", "energy", "mood", "acousticness", "tempo",
          "valence", "duration_ms", "num_sections", "num_segments"]


def clean_source(payload, source_name):
    """Column-oriented dict -> list of cleaned row dicts."""
    row_keys = sorted(payload.get("id", {}), key=int)
    rows, dropped = [], []

    for key in row_keys:
        song_id = payload["id"].get(key)
        title, title_key, title_flag = clean_title(payload.get("title", {}).get(key))

        if not isinstance(song_id, str) or not song_id.strip() or title_flag:
            dropped.append({"source": source_name, "row": key,
                            "reason": "missing id or title"})
            continue

        row = {"id": song_id.strip(), "title": title, "title_key": title_key,
               "flags": [], "sources": [source_name]}
        for field in FIELDS:
            if field not in payload:          # e.g. `valence` is absent in part1
                row[field] = None
                continue
            value, flag = CLEANERS[field](payload[field].get(key))
            row[field] = value
            if flag:
                row["flags"].append(flag)
        rows.append(row)

    return rows, dropped


# --------------------------------------------------------------------------- #
# Merge the two sources on `id`
# --------------------------------------------------------------------------- #

def merge_rows(base, incoming, conflicts):
    """
    Field-level merge.  Rules, in order:
      1. A value we trust beats a value we don't (whichever file it came from).
      2. Both trusted and equal -> nothing to decide.
      3. Both trusted and different -> PREFERRED_SOURCE wins, and we record it.
    """
    winner = incoming if incoming["sources"][0] == PREFERRED_SOURCE else base
    base["title"], base["title_key"] = winner["title"], winner["title_key"]

    for field in FIELDS:
        mine, theirs = base[field], incoming[field]
        if theirs is None:
            continue
        if mine is None:
            base[field] = theirs
        elif mine != theirs:
            prefer_incoming = incoming["sources"][0] == PREFERRED_SOURCE
            conflicts.append({
                "id": base["id"], "title": base["title"], "field": field,
                "kept": theirs if prefer_incoming else mine,
                "discarded": mine if prefer_incoming else theirs,
                "winner": PREFERRED_SOURCE,
            })
            if prefer_incoming:
                base[field] = theirs
            base["flags"].append(f"{field}:conflict")

    # Keep only the flags that still describe the merged value.
    base["flags"] = [f for f in dict.fromkeys(base["flags"] + incoming["flags"])
                     if f.endswith(":conflict")
                     or "seconds_converted" in f
                     or base[f.split(":")[0]] is None]
    base["sources"] = sorted(set(base["sources"] + incoming["sources"]))
    return base


def normalize():
    by_id, dropped, conflicts = {}, [], []

    for name, path in SOURCES.items():
        rows, drops = clean_source(json.loads(path.read_text(encoding="utf-8")), name)
        dropped.extend(drops)
        for row in rows:
            if row["id"] in by_id:
                merge_rows(by_id[row["id"]], row, conflicts)
            else:
                by_id[row["id"]] = row

    songs = sorted(by_id.values(), key=lambda s: s["title_key"])
    for index, song in enumerate(songs):
        song["index"] = index

    duplicate_titles = sorted({s["title"] for s in songs
                               if sum(1 for o in songs if o["title_key"] == s["title_key"]) > 1})

    report = {
        "songs_in": {n: len(json.loads(p.read_text(encoding='utf-8'))["id"])
                     for n, p in SOURCES.items()},
        "songs_out": len(songs),
        "overlapping_ids": sum(1 for s in songs if len(s["sources"]) > 1),
        "rows_dropped": dropped,
        "conflicts": conflicts,
        "duplicate_titles": duplicate_titles,
        "flagged_values": sorted(f for s in songs for f in s["flags"]),
    }
    return songs, report


def main():
    songs, report = normalize()
    OUT_FILE.write_text(json.dumps(songs, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(songs)} songs -> {OUT_FILE}")
    print(json.dumps({k: v for k, v in report.items() if k != "flagged_values"},
                     indent=2, ensure_ascii=False))
    print("flagged values:", *report["flagged_values"], sep="\n  ")


if __name__ == "__main__":
    main()
