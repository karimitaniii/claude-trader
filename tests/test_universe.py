import pandas as pd
import pytest
import yaml

from universe import coverage_report, membership_matrix, parse_years, tech_intervals

YEARS = {
    2020: {"tickers_on_Jan_1": ["AAA", "BBB", "FB"], "changes": {"2020-03-02": {"difference": ["BBB"], "union": ["CCC"]}}},
    2021: {"tickers_on_Jan_1": ["AAA", "CCC", "FB"], "changes": {"2021-06-01": {"union": ["BBB"]}}},
}


def test_parse_years_builds_intervals():
    iv = parse_years(YEARS).set_index(["ticker", "start"])["end"]
    assert pd.isna(iv[("AAA", pd.Timestamp("2020-01-01"))])
    assert iv[("BBB", pd.Timestamp("2020-01-01"))] == pd.Timestamp("2020-03-02")
    assert pd.isna(iv[("BBB", pd.Timestamp("2021-06-01"))])  # re-added later: second interval
    assert pd.isna(iv[("CCC", pd.Timestamp("2020-03-02"))])


def test_parse_years_rejects_inconsistent_snapshot():
    bad = {**YEARS, 2021: {**YEARS[2021], "tickers_on_Jan_1": ["AAA", "FB"]}}
    with pytest.raises(ValueError):
        parse_years(bad)


def test_yaml_base_loader_keeps_ticker_on_as_string():
    text = "tickers_on_Jan_1:\n  - ON\n  - NO\n"
    assert yaml.load(text, Loader=yaml.BaseLoader)["tickers_on_Jan_1"] == ["ON", "NO"]


def test_membership_matrix_interval_is_start_inclusive_end_exclusive():
    iv = pd.DataFrame({"ticker": ["X"], "symbol": ["X"], "start": [pd.Timestamp("2020-01-03")], "end": [pd.Timestamp("2020-01-07")]})
    idx = pd.bdate_range("2020-01-01", "2020-01-10")
    m = membership_matrix(iv, idx)["X"]
    assert m[m].index.tolist() == list(pd.to_datetime(["2020-01-03", "2020-01-06"]))


def test_tech_intervals_maps_aliases_and_rejects_unclassified():
    iv = parse_years(YEARS)
    sectors = pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "FB"], "tech_like": [1, 0, 1, 1]})
    out = tech_intervals(iv, sectors)
    assert set(out["ticker"]) == {"AAA", "CCC", "FB"}
    assert out.loc[out["ticker"] == "FB", "symbol"].item() == "META"
    with pytest.raises(ValueError):
        tech_intervals(iv, sectors[sectors["ticker"] != "CCC"])


def test_coverage_report_counts_missing_member_days():
    idx = pd.bdate_range("2020-01-01", periods=4)
    members = pd.DataFrame({"A": [True] * 4, "B": [True, True, False, False]}, index=idx)
    close = pd.DataFrame({"A": [1.0, None, 1.0, 1.0], "B": [None, None, 2.0, 2.0]}, index=idx)
    rep = coverage_report(members, close)
    assert rep.loc["A", "missing_share"] == pytest.approx(0.25)
    assert rep.loc["B", "missing_share"] == pytest.approx(1.0)
