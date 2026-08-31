"""API contract tests against a temporary store, so real ratings.json is untouched."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_store
from app.store import SongStore

SONG_ID = "0tgVpDi06FyKpA1z0VMD4v"      # one of the two songs titled "Perfect"


@pytest.fixture
def client(tmp_path):
    from app.normalize import normalize
    songs, _ = normalize()
    songs_file = tmp_path / "songs.json"
    songs_file.write_text(json.dumps(songs), encoding="utf-8")

    store = SongStore(songs_file=songs_file, ratings_file=tmp_path / "ratings.json")
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_is_paged(client):
    body = client.get("/api/songs?page=1&size=10").json()
    assert body["total"] == 25 and len(body["items"]) == 10 and body["total_pages"] == 3


def test_sorting_spans_the_whole_dataset_not_just_the_page(client):
    """The slowest song overall must appear on page 1 when sorting by tempo desc."""
    everything = client.get("/api/songs?size=200").json()["items"]
    slowest = min(s["tempo"] for s in everything if s["tempo"] is not None)
    page_one = client.get("/api/songs?page=1&size=5&sort_by=tempo&order=asc").json()["items"]
    assert page_one[0]["tempo"] == slowest


def test_bad_sort_field_is_a_400(client):
    assert client.get("/api/songs?sort_by=drop_table").status_code == 400


def test_search_handles_none_one_and_many(client):
    assert client.get("/api/songs/search?title=zzz").json()["count"] == 0
    assert client.get("/api/songs/search?title=%20bohemian%20RHAPSODY%20").json()["count"] == 1
    many = client.get("/api/songs/search?title=perfect").json()
    assert many["count"] == 2 and len({s["id"] for s in many["matches"]}) == 2


def test_rating_persists_and_is_scoped_to_one_song(client):
    assert client.put(f"/api/songs/{SONG_ID}/rating", json={"stars": 4}).json()["rating"] == 4
    assert client.get(f"/api/songs/{SONG_ID}").json()["rating"] == 4

    # The *other* "Perfect" must stay unrated -- ratings key on id, not title.
    others = [s for s in client.get("/api/songs/search?title=perfect").json()["matches"]
              if s["id"] != SONG_ID]
    assert others[0]["rating"] is None


def test_rating_rejects_invalid_input(client):
    for bad in ({"stars": 0}, {"stars": 6}, {"stars": 4.5}, {"stars": "five"}, {}):
        assert client.put(f"/api/songs/{SONG_ID}/rating", json=bad).status_code == 422
    assert client.put("/api/songs/nope/rating", json={"stars": 3}).status_code == 404
