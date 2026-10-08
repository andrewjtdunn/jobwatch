"""Radancy careers sites read through their server-rendered LOCATION pages, for boards whose
robots.txt disallows /search-jobs/ (which the plain `radancy` adapter uses).

cfg supplies "base" (the site root) and "pages": listing paths such as
"/location/<name>-jobs/<org>/<geo-ids>/<level>". Each page is walked by appending "/N"
(a "?p=N" query is silently ignored and re-serves page 1), up to its own
data-total-pages. Records are unioned by job path.

Cards carry only a title and one location string, often "Multiple Locations", and no
date. So for rows that pass title_hit() -- and only those -- the job page is opened and
its JSON-LD JobPosting supplies every location and datePosted.

Remote is read conservatively. jobLocationType TELECOMMUTE becomes "Remote - United
States" only when the posting names a US applicant requirement AND lists no office;
beside a named office it stays a bare "Remote", which the location rule treats as that
office's flag rather than as remote-first.
"""
import json
import re
import time
from html import unescape

from ..common import assert_records, http, iso_date, title_hit

LI_RX = re.compile(r'<li[^>]*>\s*<a[^>]+href="/job/.*?</li>', re.S)
HREF_RX = re.compile(r'href="(/job/[^"]+)"')
H2_RX = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
LOC_RX = re.compile(r'class="job-location"[^>]*>\s*(.*?)\s*</span>', re.S)
PAGES_RX = re.compile(r'data-total-pages="(\d+)"')
LD_RX = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
TAG_RX = re.compile(r"<[^>]+>")
US_NAMES = {"us", "usa", "united states", "united states of america"}


def _text(s):
    return unescape(TAG_RX.sub("", s or "")).strip()


def parse_listing(html):
    """-> (records keyed by job path, total pages)."""
    out = {}
    for li in LI_RX.findall(html):
        href = HREF_RX.search(li)
        if not href:
            continue
        path = href.group(1)
        title, loc = H2_RX.search(li), LOC_RX.search(li)
        out[path] = {"title": _text(title.group(1)) if title else "",
                     "location": _text(loc.group(1)) if loc else ""}
    pages = PAGES_RX.search(html)
    return out, int(pages.group(1)) if pages else 1


def parse_job_page(html):
    """-> (locations, iso date) from the page's JSON-LD JobPosting, or ([], None)."""
    for block in LD_RX.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if "JobPosting" not in str(data.get("@type")):
            continue
        offices = []
        for place in data.get("jobLocation") or []:
            addr = (place or {}).get("address") or {}
            parts = [addr.get("addressLocality"), addr.get("addressRegion")]
            label = ", ".join(p for p in parts if p)
            if label:
                offices.append(label)
        locs = list(offices)
        if str(data.get("jobLocationType") or "").upper() == "TELECOMMUTE":
            req = data.get("applicantLocationRequirements") or {}
            reqs = req if isinstance(req, list) else [req]
            us = any(str((r or {}).get("name", "")).strip().lower() in US_NAMES for r in reqs)
            locs.append("Remote - United States" if us and not offices else "Remote")
        return locs, iso_date(data.get("datePosted"))
    return [], None


def fetch(cfg):
    base = cfg["base"].rstrip("/")
    seen = {}
    for listing in cfg["pages"]:
        listing = listing.rstrip("/")
        html = http(base + listing)
        rows, total = parse_listing(html)
        for page in range(2, min(total, cfg.get("max_pages", 30)) + 1):
            time.sleep(0.8)
            more, _ = parse_listing(http(f"{base}{listing}/{page}"))
            rows.update(more)
        for path, row in rows.items():
            rec = seen.setdefault(path, {
                "id": path.rstrip("/").split("/")[-1],
                "title": row["title"],
                "locations": [],
                "url": base + path,
                "date": None,
                "date_note": "",
            })
            if row["location"] and row["location"] not in rec["locations"]:
                rec["locations"].append(row["location"])
        time.sleep(0.8)
    records = list(seen.values())
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    for rec in records:
        if not title_hit(rec["title"]):
            continue
        try:
            locs, date = parse_job_page(http(rec["url"]))
        except Exception:  # one detail miss must not fail the board
            continue
        if locs:
            rec["locations"] = locs
        rec["date"] = date
        time.sleep(0.5)
    return records
