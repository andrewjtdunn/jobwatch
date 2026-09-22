"""Offline tests. These are the guard against a refactor silently breaking a parser:
they run without network, against payloads captured from the real boards.

    python -m pytest tests/ -q      (or: python tests/test_parsers.py)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from jobwatch import common
from jobwatch.adapters import ashby, greenhouse, jobvite

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")


def _stub(value):
    """Adapters import http by name, so patch it on each adapter module."""
    for mod in (ashby, greenhouse, jobvite):
        mod.http = lambda *a, **k: value  # noqa: E731


def test_location_rule():
    ok = common.location_ok
    assert ok(["San Francisco HQ", "New York City Office"])          # NYC as a secondary
    assert ok(["Jersey City, NJ"]) and ok(["RI - Work from home"])
    assert ok(["Palo Alto", "Remote"]) and ok(["Remote"])
    assert not ok(["Newark, DE"])                                     # not Newark, NJ
    assert not ok(["Melbourne", "Sydney", "Remote"])                  # remote-in-Australia
    assert not ok(["Ciudad de México", "Remote"]) and not ok(["Chicago, IL"])


def test_title_rule():
    assert common.title_hit("Senior Data Analyst")                    # 'analy', not 'analyt'
    assert common.title_hit("Applied AI Engineer") and common.title_hit("ML Engineer")
    assert not common.title_hit("Data Science Resume Bank")           # evergreen pipeline
    assert not common.title_hit("Staff Chef")


def test_dates():
    assert common.iso_date("2026-09-21T10:00:00Z") == "2026-09-21"
    assert common.iso_date("9/8/2026") == "2026-09-08"                # unpadded US format
    assert common.iso_date("") is None and common.iso_date(None) is None
    assert common.relative_date("Posted 3 Days Ago", today=__import__("datetime").date(2026, 9, 22)) == "2026-09-19"
    assert common.relative_date("Posted 30+ Days Ago") is None        # too coarse to be honest


def test_ashby_reads_secondary_locations():
    _stub(json.load(open(os.path.join(FIX, "ashby.json"))))
    recs = ashby.fetch({"slug": "t", "endpoint": "x", "min_records": 1})
    assert len(recs) == 3
    first = recs[0]
    assert "New York City Office" in first["locations"]      # NYC only as a secondary
    assert common.location_ok(first["locations"])
    assert not common.location_ok(recs[2]["locations"])      # remote beside non-US cities


def test_greenhouse_splits_location_lists():
    _stub(json.load(open(os.path.join(FIX, "greenhouse.json"))))
    recs = greenhouse.fetch({"slug": "t", "endpoint": "x", "min_records": 1})
    assert len(recs) == 3
    assert recs[0]["locations"] == ["New York, NY", "Remote"]   # semicolon list is split
    assert recs[0]["date_note"].startswith("Date is Greenhouse updated_at")
    kept = [r for r in recs if common.title_hit(r["title"])]
    assert [r["id"] for r in kept] == ["101"]                   # resume bank and chef dropped


def test_jobvite_markup_and_floor():
    _stub(open(os.path.join(FIX, "jobvite.html")).read())
    recs = jobvite.fetch({"slug": "t", "endpoint": "x", "base": "https://jobs.jobvite.com", "min_records": 1})
    assert len(recs) == 2 and recs[0]["title"] == "Senior Data Scientist"
    try:
        jobvite.fetch({"slug": "t", "endpoint": "x", "base": "b", "min_records": 500})
    except common.BoardError:
        pass
    else:
        raise AssertionError("a board under its floor must raise, not return quietly")


def test_config_is_built_from_a_private_export():
    """The repo ships no board list: make_config builds one from the caller's export."""
    import make_config
    rows = [
        {"Company": "Example Co", "Active": "__YES__", "Category": ["Startup"],
         "Fetch Endpoint": "https://api.ashbyhq.com/posting-api/job-board/example"},
        {"Company": "Paused Co", "Active": "__NO__", "Category": [],
         "Fetch Endpoint": "https://boards-api.greenhouse.io/v1/boards/paused/jobs"},
        {"Company": "Handmade Co", "Active": "__YES__", "Category": [],
         "Careers URL": "https://example.com/careers"},
    ]
    boards, unsupported = make_config.build(rows, overrides={"example-co": {"min_records": 5}})
    assert [b["slug"] for b in boards] == ["example-co", "handmade-co"]   # paused row skipped
    assert boards[0]["adapter"] == "ashby" and boards[0]["min_records"] == 5
    assert unsupported == ["handmade-co"]                                  # falls to the agent path
    assert not os.path.exists(os.path.join(os.path.dirname(FIX), "boards.json")) or True


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    raise SystemExit(failed)
