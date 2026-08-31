"""
songs_api.py  —  generated in one shot by an AI coding assistant.

This is a REST API over the normalized songs table. A teammate asked an AI to
"write a FastAPI backend that serves the songs with pagination, sorting, title
lookup, and star ratings" and pasted the result below without changes.

It runs. It returns data. Reviewers on our team would NOT approve this PR.

Your task (see REVIEW.md in the take-home): review this file as if it were a
pull request. Identify what is wrong or risky, explain the impact of each
issue in one line, and note how you would fix it. You do NOT need to rewrite
the whole file — a precise review is what we're looking for.
"""
import json
from fastapi import FastAPI

app = FastAPI()


def load_songs(_cache=[]):
    # load the normalized data produced by step 1
    if _cache:
        return _cache
    with open("songs.json") as f:
        data = json.load(f)
    for row in data:
        _cache.append(row)
    return _cache


@app.get("/songs")
def get_songs(page: int = 1, size: int = 10, sort_by: str = "title", order: str = "asc"):
    songs = load_songs()
    start = page * size
    end = start + size
    page_items = songs[start:end]
    reverse = order == "desc"
    page_items = sorted(page_items, key=lambda s: s[sort_by], reverse=reverse)
    return {"page": page, "size": size, "total": len(songs), "items": page_items}


@app.get("/songs/{title}")
def get_song_by_title(title: str):
    songs = load_songs()
    for song in songs:
        if song["title"] == title:
            return song
    return {"error": "not found"}


ratings = {}


@app.post("/songs/{title}/rating")
def rate_song(title: str, stars: int):
    ratings[title] = stars
    songs = load_songs()
    for song in songs:
        if song["title"] == title:
            song["rating"] = stars
    return {"title": title, "stars": stars}


@app.get("/stats/duration")
def duration_stats():
    songs = load_songs()
    total = 0
    for s in songs:
        total += s["duration_ms"] / 1000
    avg_seconds = total / len(songs)
    return {"avg_seconds": avg_seconds}
