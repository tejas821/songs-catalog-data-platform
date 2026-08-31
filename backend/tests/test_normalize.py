"""Normalization rules -- one test per decision recorded in DECISIONS.md."""

from app import normalize as N


def test_numeric_strings_are_coerced():
    assert N.clean_unit_interval("0.521", "danceability") == (0.521, None)
    assert N.clean_tempo("108.73") == (108.73, None)


def test_out_of_range_value_is_dropped_not_clamped():
    value, flag = N.clean_unit_interval(1.42, "danceability")
    assert value is None and "out_of_range" in flag

    value, flag = N.clean_unit_interval(-0.05, "acousticness")
    assert value is None and "out_of_range" in flag


def test_sentinels_and_nulls_become_missing():
    assert N.clean_unit_interval("N/A", "energy") == (None, "energy:missing")
    assert N.clean_unit_interval(None, "acousticness") == (None, "acousticness:missing")


def test_zero_tempo_is_unknown_not_zero_bpm():
    value, flag = N.clean_tempo(0)
    assert value is None and "implausible" in flag


def test_duration_in_seconds_is_converted_and_flagged():
    assert N.clean_duration_ms(158) == (158_000, "duration_ms:seconds_converted(158s)")
    assert N.clean_duration_ms(225947) == (225947, None)      # already ms, untouched


def test_title_is_trimmed_and_gets_a_search_key():
    display, key, flag = N.clean_title(" 4  walls  ")
    assert (display, key, flag) == ("4 walls", "4 walls", None)


def test_full_pipeline_reconciles_the_two_files():
    songs, report = N.normalize()

    # 16 + 13 rows in, 4 ids present in both files -> 25 distinct songs.
    assert report["songs_out"] == 25
    assert report["overlapping_ids"] == 4
    assert report["rows_dropped"] == []

    # The one real disagreement between the files, resolved in favour of part2.
    assert len(report["conflicts"]) == 1
    conflict = report["conflicts"][0]
    assert (conflict["field"], conflict["kept"], conflict["winner"]) == ("danceability", 0.74, "part2")

    # `valence` exists only in part2: carried through, null for part1-only songs.
    assert any(s["valence"] is not None for s in songs)
    assert any(s["valence"] is None for s in songs)

    # Every id appears exactly once; ids -- not titles -- are the identity.
    assert len({s["id"] for s in songs}) == len(songs)
    assert "Perfect" in report["duplicate_titles"]

    # No value survives outside its declared range.
    for song in songs:
        for field in ("danceability", "energy", "acousticness", "valence"):
            assert song[field] is None or 0.0 <= song[field] <= 1.0
        assert song["duration_ms"] is None or song["duration_ms"] > 10_000
