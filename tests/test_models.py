import pytest

from fda.models import RejectedRow, parse_row, parse_states
from tests.conftest import SAMPLE_API_TIME, raw_row


def test_parse_real_sample(sample_body):
    vectors, rejected = parse_states(sample_body["states"], sample_body["time"])
    assert rejected == []
    assert len(vectors) == len(sample_body["states"]) == 33

    first = vectors[0]
    assert first.icao24 == "adda1e"
    assert first.callsign == "AAL2641"  # trailing padding stripped
    assert first.baro_altitude_m == pytest.approx(2994.66)
    assert first.on_ground is False
    assert first.squawk == "4145"
    assert first.category == 1


def test_on_ground_rows_have_null_altitude(sample_body):
    vectors, _ = parse_states(sample_body["states"], sample_body["time"])
    ground = [v for v in vectors if v.on_ground]
    assert ground, "sample should include aircraft on the ground at PHL"
    assert all(v.baro_altitude_m is None for v in ground)


def test_row_without_category_parses(make_sv):
    row = raw_row(make_sv())[:17]
    assert parse_row(row, SAMPLE_API_TIME).category is None


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda r: r.__setitem__(0, "ZZZZZZ"), "invalid icao24"),
        (lambda r: r.__setitem__(0, "abc"), "invalid icao24"),
        (lambda r: r.__setitem__(0, None), "invalid icao24"),
        (lambda r: r.__setitem__(4, None), "missing last_contact"),
        (lambda r: r.__setitem__(6, "39.4"), "expected number"),
        (lambda r: r.__setitem__(3, 1.5), "expected integer"),
    ],
)
def test_bad_rows_rejected(make_sv, mutate, reason):
    row = raw_row(make_sv())
    mutate(row)
    with pytest.raises(RejectedRow, match=reason):
        parse_row(row, SAMPLE_API_TIME)


def test_short_row_rejected():
    with pytest.raises(RejectedRow):
        parse_row(["a1b2c3", "X"], SAMPLE_API_TIME)


def test_uppercase_icao24_normalized(make_sv):
    row = raw_row(make_sv())
    row[0] = "A1B2C3"
    assert parse_row(row, SAMPLE_API_TIME).icao24 == "a1b2c3"


def test_parse_states_counts_rejections_and_duplicates(make_sv):
    good = raw_row(make_sv())
    bad = raw_row(make_sv(icao24="nothex"))
    vectors, rejected = parse_states([good, bad, list(good), "garbage"], SAMPLE_API_TIME)
    assert len(vectors) == 1
    assert len(rejected) == 3
    assert any("duplicate" in r for r in rejected)
