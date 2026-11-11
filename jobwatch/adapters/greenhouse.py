"""Greenhouse job board API. Use the BARE endpoint: content=false has returned 404s."""
import re
import time
from html import unescape

from ..common import assert_records, http, iso_date, location_ok

NOTE = "Date is Greenhouse updated_at (last-updated, approximate)"


def fetch(cfg):
    data = http(cfg["endpoint"], expect_json=True)
    jobs = data.get("jobs", [])
    assert_records(cfg["slug"], jobs, minimum=cfg.get("min_records", 1))
    total = (data.get("meta") or {}).get("total")
    if total is not None and len(jobs) != total:
        from ..common import BoardError
        raise BoardError(f"{cfg['slug']}: got {len(jobs)} of meta.total {total} — truncated read")
    out = []
    for j in jobs:
        name = ((j.get("location") or {}).get("name")) or ""
        locs = [p.strip() for p in name.replace("/", ";").split(";") if p.strip()]
        # first_published is the real publish date. updated_at moves on every edit, so it
        # is only the fallback, and says so.
        published = iso_date(j.get("first_published"))
        out.append({
            "id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "locations": locs,
            "url": j.get("absolute_url", ""),
            "date": published or iso_date(j.get("updated_at")),
            "date_note": "" if published else NOTE,
        })
    return out


_TAG_RX = re.compile(r"<[^>]+>")
_WS_RX = re.compile(r"\s+")


def _plain(html):
    return _WS_RX.sub(" ", unescape(_TAG_RX.sub(" ", unescape(html or "")))).strip()


def resolve_details(cfg, records):
    """Second pass, for title hits whose location field FAILS the location rule.

    The list endpoint carries one free-text location field and nothing else. Employers
    leave it blank or put filler in it (one board's Data Scientist role said "Template"
    while its office was "Remote US"), and such a role then fails the location rule with
    no warning. The detail endpoint adds the structured office list and the description,
    so classify() can judge it on what the posting actually says. Rows that already pass
    are not opened, so a board costs one request per failing title hit.
    """
    limit = int(cfg.get("max_detail_pages", 80))
    opened = 0
    for r in records:
        if location_ok(r["locations"]) or opened >= limit:
            continue
        try:
            data = http(f"{cfg['endpoint'].rstrip('/')}/{r['id']}", expect_json=True)
        except Exception:  # a single detail miss must not fail the board
            continue
        opened += 1
        offices = [o.get("name", "").strip() for o in (data.get("offices") or [])]
        r["locations"] = list(dict.fromkeys(r["locations"] + [o for o in offices if o]))
        desc = _plain(data.get("content"))
        if desc:
            r["description"] = desc
        time.sleep(float(cfg.get("detail_delay", 0.3)))
