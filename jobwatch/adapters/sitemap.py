"""Sitemap-driven boards. The URL slug carries the title, and sometimes the location.
lastmod is a sitemap timestamp, NOT a posting date, and must never be used as one."""
import re

from ..common import assert_closes_with, assert_records, http

LOC_RX = re.compile(r"<loc>([^<]+)</loc>")


def fetch(cfg):
    urls = []
    for sm in cfg["sitemaps"]:
        xml = http(sm)
        assert_closes_with(cfg["slug"], xml, "</urlset>")
        urls.extend(LOC_RX.findall(xml))
    urls = [u for u in dict.fromkeys(urls) if re.search(cfg.get("job_url_rx", r"/job/"), u)]
    records = [{
        "id": u.rstrip("/").split("/")[-1],
        "title": _title_from(u, cfg),
        "locations": [],           # resolved on the job page for title hits only
        "url": u,
        "date": None,
        "date_note": "Sitemap lastmod is not a posting date",
    } for u in urls]
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    return records


def _title_from(url, cfg):
    tail = url.rstrip("/").split("/")[-1].split("?")[0]
    tail = re.sub(r"^\d+[-_]", "", tail)      # some boards prefix the req id
    return tail.replace("-", " ").replace("_", " ").strip()


import time as _time

MULTI_LOC_RX = re.compile(r'"multi_location"\s*:\s*\[(.*?)\]', re.S)
ADDRESS_RX = re.compile(r'"address"\s*:\s*"([^"]+)"')
ADDRESS_LOCALITY_RX = re.compile(r'"addressLocality"\s*:\s*"([^"]+)"')
JSONLD_DATE_RX = re.compile(r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def resolve(cfg, records):
    """Fill in locations for title hits only. Two modes, set by cfg['location_mode']:

    slug  — the sitemap slug carries the location; no extra request.
    page  — open the job page. One board's JSON-LD addressLocality went empty in Sept
            2026, so multi_location[].address is read first and addressLocality is only
            a fallback.
    """
    mode = cfg.get("location_mode", "page")
    if mode == "slug":
        rx = re.compile(cfg["slug_location_rx"])
        for r in records:
            m = rx.search(r["url"])
            if m:
                r["locations"] = [m.group(1).replace("-", " ").strip()]
        return records
    for r in records[: cfg.get("max_detail_pages", 60)]:
        try:
            html = http(r["url"])
        except Exception:  # one page failing must not fail the board
            continue
        block = MULTI_LOC_RX.search(html)
        locs = ADDRESS_RX.findall(block.group(1)) if block else []
        if not locs:
            locs = [x for x in ADDRESS_LOCALITY_RX.findall(html) if x.strip()]
        r["locations"] = locs
        d = JSONLD_DATE_RX.search(html)
        if d and cfg.get("trust_page_date", True):
            r["date"] = d.group(1)
            r["date_note"] = ""
        _time.sleep(0.6)
    return records
