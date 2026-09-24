"""Avature careers sites. Pagination is jobRecordsPerPage/jobOffset with a TRAILING
SLASH on the path, and redirects must be followed: some of these sites 302 every paged
request. The obvious-looking "startrow" parameter silently re-serves page 1."""
import re
import time

from ..common import assert_records, http

# Listing anchors come in two shapes. The slug form (/JobDetail/<slug>/<id>) now survives
# only in the detail page's canonical tag and its share links; current listing pages emit
# the query-string form (JobDetail?jobId=<id>). Matching only the slug form finds no rows,
# which breaks the paging loop on page 1 and reports as an empty board.
ROW_RX = re.compile(
    r'<a[^>]+href="(?P<href>[^"]*JobDetail(?:/[^"?]+|\?jobId=\d+)[^"]*)"[^>]*>(?P<title>[^<]+)</a>',
    re.I,
)
JOBID_RX = re.compile(r'[?&]jobId=(\d+)', re.I)


def _id_from(href):
    """The id is the last path segment in the slug form, the jobId in the query form."""
    m = JOBID_RX.search(href)
    return m.group(1) if m else href.rstrip("/").split("/")[-1]


def fetch(cfg):
    per = cfg.get("per_page", 10)
    seen, offset = {}, 0
    while offset < cfg.get("max_records", 300):
        url = f"{cfg['endpoint'].rstrip('/')}/?jobRecordsPerPage={per}&jobOffset={offset}"
        html = http(url)
        rows = list(ROW_RX.finditer(html))
        if not rows:
            break
        for m in rows:
            href = m.group("href")
            seen[href] = {
                "id": _id_from(href),
                "title": m.group("title").strip(),
                "locations": [],          # resolved on the job page
                "url": href if href.startswith("http") else cfg["base"] + href,
                "date": None,
                "date_note": "",
                "_href": href,
            }
        offset += per
        time.sleep(0.8)
    records = list(seen.values())
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    return records


LOC_BLOCK_RX = re.compile(r'article__header--locations(.*?)</div>', re.S | re.I)
CITY_RX = re.compile(r'>\s*([A-Z][A-Za-z .\'-]+,\s*[A-Za-z ]+,\s*United States)\s*<')
# Newer detail pages drop the locations block and carry a single "Location:" field inside
# an inline JS payload, with "Remote Work:" as a SEPARATE flag. That flag is the office's
# remote toggle, not a remote-first role, so it is only evidence of remote work when no
# office is named at all -- location_verdict() decides, not this adapter.
INLINE_LOC_RX = re.compile(r'"Location:"\s*:\s*"([^"]*)"')
INLINE_REMOTE_RX = re.compile(r'"Remote Work:"\s*:\s*"(Yes|No)"', re.I)
JSONLD_DATE_RX = re.compile(r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def resolve_job_page(cfg, record):
    """Consulting boards hide 40+ cities behind "Multiple Locations"; the job page lists them."""
    html = http(record["url"])
    block = LOC_BLOCK_RX.search(html)
    locs = CITY_RX.findall(block.group(1)) if block else []
    if not locs:
        locs = [v.strip() for v in INLINE_LOC_RX.findall(html) if v.strip()]
        if not locs:
            flag = INLINE_REMOTE_RX.search(html)
            if flag and flag.group(1).lower() == "yes":
                locs = ["Remote"]
    if locs:
        record["locations"] = locs
    date = JSONLD_DATE_RX.search(html)
    if date:
        record["date"] = date.group(1)
    return record
