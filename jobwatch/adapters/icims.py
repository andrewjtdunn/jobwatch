"""iCIMS hosted search. Two traps here, and both lose postings without failing.

**pr IS ZERO-BASED.** `?pr=0` and the bare URL are the SAME page. Starting the walk at
pr=1 silently drops the FIRST page -- the newest requisitions -- while every later page
reads fine, so the board reports a clean read and is simply missing its top. Measured
2026-09-25 on a 3-page board: pr=0..2 gives 142 postings, pr=1..3 gives 92.

**Walk to the page count, not to an empty page.** The header carries the true total
("Search Results Page 1 of 3"). An empty page is also what a rate-limited, redirected or
truncated fetch looks like, so stopping at the first empty one cannot tell a finished
board from a broken read. Read the count, walk exactly that far, and fail if the walk
ends short.

**Field labels are tenant-configurable.** One board labels the cell "Job Locations", the
next calls it "Location"; titles are "Job Posting Title" or "Title". Keying the parser on
the label TEXT reads one tenant correctly and returns empty locations for the other --
and an empty location list is dropped by the location rule, so the board reports a clean
read with title hits and surfaces nothing. So: collect every label/value pair in the card,
match the label loosely, and fall back to the value that LOOKS like a region code. The
coverage assert at the end is the backstop, because this class of failure is invisible.

Locations arrive as iCIMS region codes, `US-IL-Chicago`, pipe-separated. They are
normalised to the `City, ST` form the location rule expects. A city part that is itself a
remote token becomes `ST - Remote`, which the rule then reads as a state-anchored
work-from-home tag (surfaced, flagged) rather than as remote-first.

The job URL is emitted WITHOUT its query string. `?in_iframe=1` is a presentational
flag, not identity, and the stored rows do not carry it -- keeping it would make every
posting on the board look new, every run.

The search listing carries no posting date. Never invent one.
"""
import re
import urllib.parse
from html import unescape

from ..common import BoardError, assert_field_coverage, assert_records, http

CARD_RX = re.compile(r'<li[^>]*class="[^"]*iCIMS_JobCardItem[^"]*"[^>]*>(.*?)</li>', re.S | re.I)
LINK_RX = re.compile(r'href="(?P<url>[^"]*?/jobs/(?P<id>\d+)/[^"]*?/job[^"]*)"', re.I)
H3_RX = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S | re.I)
TITLE_ATTR_RX = re.compile(r'title="\s*\d+\s*-\s*([^"]+)"')
FIELD_RX = re.compile(
    r'<span[^>]*class="[^"]*field-label[^"]*"[^>]*>(?P<label>.*?)</span>\s*'
    r'<span[^>]*>(?P<value>.*?)</span>', re.S | re.I)
PAGE_RX = re.compile(r"Search\s+Results\s+Page\s+(\d+)\s+of\s+(\d+)", re.I)
TAG_RX = re.compile(r"<[^>]+>")
REGION_RX = re.compile(r"^([A-Z]{2})-([A-Z0-9]{2,3})-(.+)$")
REMOTE_WORDS = {"remote", "work from home", "workfromhome", "virtual", "telecommute"}


def _text(fragment):
    return re.sub(r"\s+", " ", unescape(TAG_RX.sub(" ", fragment or ""))).strip()


def _location(token):
    """`US-IL-Chicago` -> `Chicago, IL`; `US-MO-Remote` -> `MO - Remote`."""
    token = token.strip()
    found = REGION_RX.match(token)
    if not found:
        return token
    country, region, city = found.group(1), found.group(2), found.group(3).strip()
    if city.lower().replace(" ", "") in REMOTE_WORDS:
        # State-anchored work-from-home: real remote work, but the req may require
        # residence in that state. Keep the state visible so the rule can flag it.
        return f"{region} - Remote" if country == "US" else f"{region}, {country} - Remote"
    return f"{city}, {region}" if country == "US" else f"{city}, {region}, {country}"


def _page_url(endpoint, pr):
    parts = urllib.parse.urlsplit(endpoint)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "pr"]
    query.append(("pr", str(pr)))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _parse(card):
    link = LINK_RX.search(card)
    if not link:
        return None
    title = ""
    anchor = H3_RX.search(card)
    if anchor:
        title = _text(anchor.group(1))
    if not title:
        attr = TITLE_ATTR_RX.search(card)
        title = _text(attr.group(1)) if attr else ""
    fields = {_text(m.group("label")).lower().strip(": "): _text(m.group("value"))
              for m in FIELD_RX.finditer(card)}
    raw = next((v for k, v in fields.items() if "location" in k), None)
    if raw is None:                      # label renamed: fall back to the value's shape
        raw = next((v for v in fields.values()
                    if REGION_RX.match(v.split("|")[0].strip())), None)
    locs = [_location(p) for p in raw.split("|")] if raw else []
    url = unescape(link.group("url")).split("?")[0]
    return {
        "id": link.group("id"),
        "title": title,
        "locations": [l for l in locs if l],
        "url": url,
        "date": None,                       # the search listing publishes none
        "date_note": "",
    }


def fetch(cfg):
    seen, pages, pr = {}, None, 0
    max_pages = cfg.get("max_pages", 20)
    while pr < max_pages:
        body = http(_page_url(cfg["endpoint"], pr))
        counter = PAGE_RX.search(body)
        if counter:
            total = int(counter.group(2))
            if pages is None:
                pages = total
            elif total != pages:
                raise BoardError(
                    f"{cfg['slug']}: page count changed mid-walk ({pages} -> {total}); "
                    "the result set moved under us, so the read is not contiguous"
                )
        cards = CARD_RX.findall(body)
        if not cards:
            break
        for card in cards:
            rec = _parse(card)
            if rec and rec["id"] not in seen:
                seen[rec["id"]] = rec
        pr += 1
        if pages is not None and pr >= pages:
            break
    if pages is not None and pr < pages:
        raise BoardError(
            f"{cfg['slug']}: stopped after {pr} of {pages} pages the board reports. "
            "An empty page mid-walk is a failed fetch, not the end of the board."
        )
    records = list(seen.values())
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    # A card whose location cell did not parse is dropped by the location rule, so a
    # renamed label reads as "no matches" rather than as a break. Fail loudly instead.
    assert_field_coverage(cfg["slug"], records, "locations", minimum=0.8)
    return records
