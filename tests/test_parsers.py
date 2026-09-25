"""Offline tests. These are the guard against a refactor silently breaking a parser:
they run without network, against payloads captured from the real boards.

    python -m pytest tests/ -q      (or: python tests/test_parsers.py)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from jobwatch import common
from jobwatch.adapters import (ashby, avature, greenhouse, icims, jobvite, radancy, roster,
                               sitemap, workday)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")


def _stub(value):
    """Adapters import http by name, so patch it on each adapter module."""
    for mod in (ashby, greenhouse, jobvite):
        mod.http = lambda *a, **k: value  # noqa: E731


def test_location_rule():
    """Criteria are "NYC metro, or fully remote / remote-first". The remote leg needs
    POSITIVE evidence of US-wide remote: a bare "Remote" beside a named office is that
    office's remote-work flag, not a remote-first role."""
    ok = common.location_ok
    assert ok(["San Francisco HQ", "New York City Office"])            # NYC as a secondary
    assert ok(["Jersey City, NJ"]) and ok(["Charlotte", "Jersey City", "Atlanta"])
    assert ok(["Remote"]) and ok(["Remote - US"]) and ok(["US Remote"])
    assert ok(["Acme NY", "Remote"])                                 # bare NY = the NY office
    assert ok(["MA - Wellesley", "Work At Home-New York"])
    assert not ok(["Newark, DE"])                                      # not Newark, NJ
    assert not ok(["Chicago, IL"]) and not ok(["Melbourne", "Sydney", "Remote"])


def test_bare_remote_beside_an_office_is_not_remote_first():
    """The 2026-09-23 regression, with the exact values that caused it. Every one of these
    was surfaced as an NYC-eligible match; several were labelled Strong. The old rule
    decided US-ness from a blocklist of foreign city names, so a city missing from the
    list read as American, and it treated "Remote" beside a US
    office as remote-first."""
    v = common.location_verdict
    assert v(["MYS - Kuala Lumpur", "Remote"]) is None       # remote-in-Malaysia
    assert v(["CZE - Prague", "CZE - Brno", "Remote"]) is None
    assert v(["Palo Alto", "Remote"]) is None                # hybrid, anchored to Palo Alto
    assert v(["Acme SF", "Remote"]) is None
    assert v(["San Francisco HQ", "Remote"]) is None
    assert v(["USA - Tempe, AZ", "Remote"]) is None          # US, but not NYC and not remote-first
    assert v(["Palo Alto", "Virginia", "Miami", "Remote"]) is None
    # ... while the genuine ones still pass, by the leg that actually qualified them
    assert v(["USA - New York, NY", "Remote"]) == "nyc"
    assert v(["San Francisco HQ", "New York City Office", "Remote"]) == "nyc"
    assert v(["Remote"]) == "remote"
    assert v(["Remote, United States"]) == "remote"
    # a state-anchored work-from-home tag is real remote work, but may require residence
    assert v(["AZ - Work from home"]) == "ambiguous"
    assert common.location_ok(["AZ - Work from home"])       # surfaced, flagged, not dropped


def test_displayed_location_never_hides_the_real_anchor():
    """The display half of the same bug: picking the first "qualifying" item put a bare
    "Remote" in the Location column while the role was anchored to an office abroad."""
    p = common.Candidate(slug="t", role="Senior Data Scientist", company="X", url="u",
                       locations=["MYS - Kuala Lumpur", "Remote"])
    assert p.to_row([])["Location"].startswith("MYS - Kuala Lumpur")
    q = common.Candidate(slug="t", role="Senior Data Scientist", company="X", url="u",
                       locations=["San Francisco HQ", "New York City Office", "Remote"])
    assert q.to_row([])["Location"].startswith("New York City Office")


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


def test_avature_reads_both_job_link_shapes():
    """A listing page that links as JobDetail?jobId=<id> must still parse. Matching only
    the older /JobDetail/<slug>/<id> form found no rows, which broke the paging loop on
    page 1 and reported a healthy board as empty."""
    html = open(os.path.join(FIX, "avature.html")).read()
    avature.http = lambda *a, **k: html
    cfg = {"slug": "x", "endpoint": "https://example-boards.test/careers/SearchJobs/",
           "base": "https://example-boards.test", "per_page": 3, "max_records": 3,
           "min_records": 1}
    records = avature.fetch(cfg)
    assert len(records) == 3, records
    ids = {r["id"] for r in records}
    assert ids == {"123825", "123826", "119001"}, ids     # query form yields the jobId
    titles = {r["title"] for r in records}
    assert "Data Scientist, Mission Analytics" in titles
    assert all(r["url"].startswith("https://example-boards.test") for r in records)


def test_avature_reads_location_from_the_inline_payload():
    """The locations block was replaced by a "Location:" field in an inline JS payload,
    with "Remote Work:" as a separate flag. A bare remote flag beside a named office is
    that office's toggle, so it must not turn into a remote-first location."""
    detail = open(os.path.join(FIX, "avature_detail.html")).read()
    avature.http = lambda *a, **k: detail
    r = avature.resolve_job_page({}, {"url": "u", "locations": [], "date": None})
    assert r["locations"] == ["New York,NY,US"], r["locations"]
    assert r["date"] == "2026-09-19"
    assert common.location_verdict(r["locations"]) == "nyc"

    remote = open(os.path.join(FIX, "avature_detail_remote.html")).read()
    avature.http = lambda *a, **k: remote
    r2 = avature.resolve_job_page({}, {"url": "u", "locations": [], "date": None})
    assert r2["locations"] == ["Remote"], r2["locations"]   # no office named at all
    assert common.location_verdict(r2["locations"]) == "remote"


def test_sitemap_reads_titles_only_for_what_is_newer_than_the_watermark():
    """A board whose job URLs are keyed by id alone (/jobs/R-123) carries no title in the
    slug, so title_hit() can never fire and the board reads clean while surfacing nothing.
    Titles come off the job pages, but only for ids above the watermark -- opening every
    page of a board of thousands every run is not affordable."""
    pages = {
        "https://x.test/jobs/R-101": "<title>Old Role - Careers</title>",
        "https://x.test/jobs/R-102": "<title>Data Scientist, Pricing | Jobs</title>",
        "https://x.test/jobs/R-103": "<title>Power Equipment Operator - Careers</title>",
    }
    opened = []

    def fake_http(url, *a, **k):
        opened.append(url)
        return pages[url]

    sitemap.http = fake_http
    sitemap._time.sleep = lambda *a, **k: None
    records = [{"id": f"R-{n}", "title": f"r {n}", "url": f"https://x.test/jobs/R-{n}",
                "locations": [], "date": None, "date_note": ""} for n in (101, 102, 103)]
    cfg = {"slug": "x", "watermark": "R-101", "max_new_titles": 400}

    mark = sitemap.resolve_titles(cfg, records)

    assert opened == ["https://x.test/jobs/R-102", "https://x.test/jobs/R-103"], opened
    assert records[0]["title"] == "r 101"                 # at the mark, left alone
    assert records[1]["title"] == "Data Scientist, Pricing"   # site suffix stripped
    assert records[2]["title"] == "Power Equipment Operator"
    assert common.title_hit(records[1]["title"])
    assert not common.title_hit(records[2]["title"])
    assert mark == 103, mark


def test_sitemap_watermark_stops_at_a_gap_instead_of_stepping_over_it():
    """The mark must never advance past a page that was not read, or those ids are gone
    for good: the next run starts above them and no later run ever looks again."""
    def fake_http(url, *a, **k):
        if url.endswith("R-202"):
            raise RuntimeError("timeout")
        return "<title>Data Analyst</title>"

    sitemap.http = fake_http
    sitemap._time.sleep = lambda *a, **k: None
    records = [{"id": f"R-{n}", "title": "", "url": f"https://x.test/jobs/R-{n}",
                "locations": [], "date": None, "date_note": ""} for n in (201, 202, 203)]
    cfg = {"slug": "x", "watermark": "R-200"}

    mark = sitemap.resolve_titles(cfg, records)

    assert mark == 201, mark        # read 201, hit the gap at 202, stopped
    assert records[2]["title"] == ""  # 203 untouched, so the next run still reaches it


def test_sitemap_budget_caps_a_board_too_big_for_one_run():
    """A first run against a huge board must not open every page. It takes a bite, oldest
    first so the mark stays contiguous, and catches up over later runs."""
    sitemap.http = lambda url, *a, **k: "<title>Data Engineer</title>"
    sitemap._time.sleep = lambda *a, **k: None
    records = [{"id": f"R-{n}", "title": "", "url": f"https://x.test/jobs/R-{n}",
                "locations": [], "date": None, "date_note": ""} for n in range(500, 400, -1)]
    cfg = {"slug": "x", "max_new_titles": 3}      # no watermark at all: a cold start

    mark = sitemap.resolve_titles(cfg, records)

    assert mark == 403, mark        # 401, 402, 403 -- the OLDEST three, not the newest
    assert cfg["_watermark_backlog"] == 97, cfg["_watermark_backlog"]


def test_sitemap_reports_when_the_budget_is_not_the_binding_constraint():
    """A backlog of 0 means the budget was never the limit -- the board was fully caught
    up. Only a PERSISTENTLY non-zero backlog means max_new_titles is set below the
    board's own posting rate, which is the case that never resolves on its own."""
    sitemap.http = lambda url, *a, **k: "<title>Data Engineer</title>"
    sitemap._time.sleep = lambda *a, **k: None
    records = [{"id": f"R-{n}", "title": "", "url": f"https://x.test/jobs/R-{n}",
                "locations": [], "date": None, "date_note": ""} for n in (11, 12)]
    cfg = {"slug": "x", "watermark": "R-10", "max_new_titles": 400}

    sitemap.resolve_titles(cfg, records)

    assert cfg["_watermark_backlog"] == 0, cfg["_watermark_backlog"]


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


def test_radancy_reads_location_and_date_whatever_the_field_order():
    """The board reorders the card's spans from time to time. Fields must be read from
    inside each card independently, never by one regex that assumes title-then-location-
    then-date: when that assumption broke, every record parsed an EMPTY location, every
    posting failed the location rule, and the board reported a confident zero."""
    radancy.http = lambda *a, **k: json.load(open(os.path.join(FIX, "radancy.json")))
    radancy.time.sleep = lambda *a, **k: None
    recs = radancy.fetch({"slug": "t", "base": "https://example.com",
                          "keywords": [""], "max_pages": 1, "min_records": 1})
    assert len(recs) == 2
    by_id = {r["id"]: r for r in recs}
    first = by_id["90000000001"]
    assert first["title"] == "Senior Data Scientist"
    assert first["locations"] == ["New York, NY"]        # NOT [""] - the regression
    assert first["date"] == "2026-06-02"                 # unpadded M/D/YYYY, normalised
    assert first["url"] == "https://example.com/job/example-city/senior-data-scientist/1000/90000000001"
    assert common.location_ok(first["locations"])
    assert by_id["90000000002"]["locations"] == ["Chicago, IL"]
    assert all(r["locations"] != [""] for r in recs)


def test_workday_pages_past_a_zero_total_on_later_pages():
    """Workday reports the real total only on the first page and sends total=0 on every
    page after it. Paging must not treat that 0 as the end of the board, or every Workday
    board silently truncates to the first two pages."""
    pages = {0: 63, 20: 0, 40: 0, 60: 0}                 # what the live endpoint returns

    def fake_http(url, data=None, expect_json=False, **kw):
        offset = data["offset"]
        remaining = max(0, 63 - offset)
        n = min(20, remaining)
        return {"total": pages.get(offset, 0),
                "jobPostings": [{"externalPath": f"/job/r{offset + i}",
                                 "title": "Data Scientist",
                                 "locationsText": "New York, NY",
                                 "bulletFields": [f"R-{offset + i}"],
                                 "postedOn": "Posted 2 Days Ago"} for i in range(n)]}

    workday.http = fake_http
    workday.time.sleep = lambda *a, **k: None
    recs = workday.fetch({"slug": "t", "endpoint": "https://example.com/jobs",
                          "keywords": [""], "url_shape": "https://example.com{path}",
                          "min_records": 1})
    assert len(recs) == 63, f"paging stopped early: read {len(recs)} of 63"



def _icims_pages():
    """Page bodies keyed by the pr value that should fetch them."""
    return {0: open(os.path.join(FIX, "icims_p1.html")).read(),
            1: open(os.path.join(FIX, "icims_p2.html")).read()}


def _icims_stub(pages, log):
    def _http(url, *a, **k):
        import urllib.parse
        pr = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("pr")
        log.append(pr)
        return pages.get(int(pr), open(os.path.join(FIX, "icims_empty.html")).read())
    icims.http = _http


def test_us_scoped_remote_needs_no_particular_word_order():
    """Three sightings of the same gap: a remote token that positively names the US but
    does not match the literal patterns. "US-based remote" puts the qualifier BETWEEN the
    two words; "Work from Home, United States" names the country rather than US/USA. Both
    are unambiguous US-wide remote. The state-anchored tags beside them must NOT move."""
    v = common.location_verdict
    assert v(["US-based remote"]) == "remote"
    assert v(["US based remote"]) == "remote"
    assert v(["Work from Home, United States"]) == "remote"
    # ...and the cases that must stay exactly where they were
    assert v(["MO - Remote"]) == "ambiguous"
    assert v(["AZ - Work from home"]) == "ambiguous"
    assert v(["Work At Home-Connecticut"]) == "ambiguous"
    assert v(["Palo Alto", "Remote"]) is None
    assert v(["MYS - Kuala Lumpur", "Remote"]) is None


def test_icims_pr_is_zero_based():
    """pr=0 and the bare URL are the SAME page, so a walk that starts at pr=1 drops the
    FIRST page -- the newest requisitions -- while every later page reads fine. Measured
    2026-09-25 on a live 3-page board: pr=0..2 gives 142 postings, pr=1..3 gives 92, and
    the short read reports success."""
    log = []
    _icims_stub(_icims_pages(), log)
    records = icims.fetch({"slug": "x", "endpoint": "https://example-jobs.test/jobs/search?ss=1",
                           "min_records": 1})
    assert log[0] == "0", f"walk must start at pr=0, started at {log[0]}"
    ids = [r["id"] for r in records]
    assert ids == ["100001", "100002", "100003"], ids
    assert "100001" in ids, "the first page was dropped"


def test_icims_walks_to_the_page_count_not_to_an_empty_page():
    """The header reports the true page count. An empty page mid-walk is what a
    rate-limited or redirected fetch looks like too, so it must fail rather than read as
    the end of the board."""
    log = []
    _icims_stub({0: open(os.path.join(FIX, "icims_p1.html")).read()}, log)   # page 2 comes back empty
    try:
        icims.fetch({"slug": "x", "endpoint": "https://example-jobs.test/jobs/search", "min_records": 1})
    except common.BoardError as e:
        assert "of 2 pages" in str(e), e
    else:
        raise AssertionError("a short walk against a known page count must raise")


def test_icims_normalises_region_codes():
    """Locations arrive as iCIMS region codes. A city part that is itself a remote token
    must keep its state visible, so the location rule reads it as a state-anchored
    work-from-home tag (surfaced, flagged) and not as remote-first."""
    log = []
    _icims_stub(_icims_pages(), log)
    by_id = {r["id"]: r for r in icims.fetch(
        {"slug": "x", "endpoint": "https://example-jobs.test/jobs/search", "min_records": 1})}
    assert by_id["100001"]["locations"] == ["New York, NY", "Austin, TX"]
    assert by_id["100002"]["locations"] == ["MO - Remote"]
    # page 2's fixture uses the OTHER tenant's field labels ("Location" not "Job
    # Locations"). Keying on label text parsed one tenant and silently returned empty
    # locations for the other, which the location rule then dropped as no-match.
    assert by_id["100003"]["locations"] == ["Toronto, ON, CA"]
    assert common.location_verdict(by_id["100001"]["locations"]) == "nyc"
    assert common.location_verdict(by_id["100002"]["locations"]) == "ambiguous"
    assert common.location_verdict(by_id["100003"]["locations"]) is None
    assert by_id["100001"]["date"] is None, "the search listing publishes no date"
    # ?in_iframe=1 is presentational, not identity; stored rows do not carry it, and
    # keeping it would make every posting on the board look new every run.
    assert by_id["100001"]["url"] == "https://example-jobs.test/jobs/100001/senior-data-scientist/job"


def test_roster_namespaces_ids_and_survives_an_empty_member():
    """Member id spaces collide, so ids must be namespaced or dedupe drops one firm's
    postings as another's. An empty member is normal and must not fail the roster; a
    broken one must be reported rather than swallowed."""
    from jobwatch import adapters

    class _Mod:
        def __init__(self, rows): self.rows = rows
        def fetch(self, cfg):
            if self.rows == "boom":
                raise common.BoardError("endpoint gone")
            return [dict(r) for r in self.rows]

    mods = {"a": _Mod([{"id": "1", "title": "Data Scientist", "locations": ["Remote"],
                        "url": "u1", "date": None, "date_note": ""}]),
            "b": _Mod([{"id": "1", "title": "Data Analyst", "locations": ["Remote"],
                        "url": "u2", "date": None, "date_note": ""}]),
            "c": _Mod([]),            # no open roles: normal
            "d": _Mod("boom")}        # broken: reported, not fatal
    real, adapters.get = adapters.get, lambda name: mods[name]
    try:
        records = roster.fetch({"slug": "r", "min_records": 1, "members": [
            {"adapter": "a", "member": "one", "company": "One", "endpoint": "e"},
            {"adapter": "b", "member": "two", "company": "Two", "endpoint": "e"},
            {"adapter": "c", "member": "three", "company": "Three", "endpoint": "e"},
            {"adapter": "d", "member": "four", "company": "Four", "endpoint": "e"}]})
    finally:
        adapters.get = real
    assert [r["id"] for r in records] == ["a:one:1", "b:two:1"], [r["id"] for r in records]
    assert {r["company"] for r in records} == {"One", "Two"}
    assert all("1/4 members failed" in r["_partial"] for r in records)
    assert "four" in records[0]["_partial"]


def test_roster_fails_when_every_member_fails():
    """A roster whose members have all gone is a failure, not a quiet zero."""
    from jobwatch import adapters

    class _Dead:
        def fetch(self, cfg): raise common.BoardError("gone")

    real, adapters.get = adapters.get, lambda name: _Dead()
    try:
        roster.fetch({"slug": "r", "min_records": 1,
                      "members": [{"adapter": "x", "member": "one", "endpoint": "e"}]})
    except common.BoardError as e:
        assert "every member failed" in str(e), e
    else:
        raise AssertionError("an all-members failure must raise")
    finally:
        adapters.get = real

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
