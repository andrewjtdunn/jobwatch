"""Sitemap-driven boards. The URL slug USUALLY carries the title, and sometimes the
location. lastmod is a sitemap timestamp, NOT a posting date, and must never be used as
one."""
import re
from html import unescape

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
    # The floor guards the WHOLE board, before any watermark narrowing below.
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    if cfg.get("title_from") == "page":
        cfg["_new_watermark"] = resolve_titles(cfg, records)
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


TITLE_TAG_RX = re.compile(r"<title>([^<]*)</title>", re.I)
TITLE_SUFFIX_RX = re.compile(r"\s*[-|]\s*[^-|]{0,40}(careers?|jobs?)\s*$", re.I)
ID_SEQ_RX = re.compile(r"(\d+)\s*$")


def _seq(value):
    """The trailing integer of an id, for ordering. None when there is not one."""
    m = ID_SEQ_RX.search(str(value or "").strip())
    return int(m.group(1)) if m else None


def resolve_titles(cfg, records):
    """Read titles off the job pages, for boards whose job URLs are keyed by id alone.

    Some sitemaps emit /jobs/R-1075582 and nothing else: the slug carries no title, so
    title_hit() can never fire and the board reads clean while surfacing nothing. The
    title is on the job page, but a board of thousands cannot be opened in full every run.

    So open only what is newer than cfg['watermark'] -- the highest id already read --
    OLDEST FIRST, and advance the mark over what was read. A board too large for one run
    catches up across several and never skips a gap: a failed fetch stops the walk rather
    than stepping over it, so the mark never moves past a page that was not read.

    Returns the new watermark. NOTHING HERE PERSISTS IT: the caller has to write it back
    into the board's config, or the next run re-reads the same pages.

    Also sets cfg["_watermark_backlog"]: how many fresh records the budget did NOT reach.
    A backlog that is non-zero every run means max_new_titles is below the board's own
    posting rate, and the board is permanently behind -- it never catches up, and it only
    ever reads stale ids. Without this number that condition is invisible, because the
    board reports a clean read either way.
    """
    mark = _seq(cfg.get("watermark"))
    fresh = [r for r in records if _seq(r["id"]) is not None]
    if mark is not None:
        fresh = [r for r in fresh if _seq(r["id"]) > mark]
    fresh.sort(key=lambda r: _seq(r["id"]))
    budget = cfg.get("max_new_titles", 400)
    cfg["_watermark_backlog"] = max(0, len(fresh) - budget)
    highest = mark
    for r in fresh[:budget]:
        try:
            html = http(r["url"])
        except Exception:
            break                      # stop at the gap; do not advance the mark past it
        found = TITLE_TAG_RX.search(html)
        if found:
            title = TITLE_SUFFIX_RX.sub("", unescape(found.group(1))).strip()
            if title:
                r["title"] = title
        highest = _seq(r["id"])
        _time.sleep(0.4)
    return highest
