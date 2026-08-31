"""Sorting, paging and title lookup -- the pure logic, no web server involved."""

import pytest

from app.store import paginate, search_by_title, sort_songs

SONGS = [
    {"id": "a", "title": "banana", "title_key": "banana", "tempo": 120.0},
    {"id": "b", "title": "Apple",  "title_key": "apple",  "tempo": None},   # unknown tempo
    {"id": "c", "title": "cherry", "title_key": "cherry", "tempo": 90.0},
    {"id": "d", "title": "Apple",  "title_key": "apple",  "tempo": 150.0},  # duplicate title
]


def test_sort_is_case_insensitive_for_text():
    assert [s["id"] for s in sort_songs(SONGS, "title", "asc")] == ["b", "d", "a", "c"]


def test_unknown_values_sink_to_the_bottom_in_both_directions():
    assert [s["id"] for s in sort_songs(SONGS, "tempo", "asc")] == ["c", "a", "d", "b"]
    assert [s["id"] for s in sort_songs(SONGS, "tempo", "desc")] == ["d", "a", "c", "b"]


def test_sort_field_is_allow_listed():
    with pytest.raises(ValueError):
        sort_songs(SONGS, "__class__", "asc")
    with pytest.raises(ValueError):
        sort_songs(SONGS, "title", "sideways")


def test_pagination_is_one_based_and_page_one_is_not_skipped():
    items, meta = paginate(SONGS, page=1, size=2)
    assert [s["id"] for s in items] == ["a", "b"]
    assert (meta["total"], meta["total_pages"]) == (4, 2)


def test_last_page_is_short_and_past_the_end_is_empty():
    assert len(paginate(SONGS, page=2, size=3)[0]) == 1
    assert paginate(SONGS, page=99, size=10)[0] == []


def test_pagination_rejects_nonsense():
    with pytest.raises(ValueError):
        paginate(SONGS, page=0, size=10)
    with pytest.raises(ValueError):
        paginate(SONGS, page=1, size=10_000)


def test_search_ignores_case_and_padding_and_returns_all_matches():
    matches, kind = search_by_title(SONGS, "  APPLE ")
    assert kind == "exact" and {s["id"] for s in matches} == {"b", "d"}


def test_search_falls_back_to_substring_then_reports_nothing():
    matches, kind = search_by_title(SONGS, "err")
    assert kind == "partial" and [s["id"] for s in matches] == ["c"]
    assert search_by_title(SONGS, "nope") == ([], "none")
