"""Avature careers sites. Pagination is jobRecordsPerPage/jobOffset with a TRAILING
SLASH on the path, and redirects must be followed: some of these sites 302 every paged
request. The obvious-looking "startrow" parameter silently re-serves page 1."""
import re
import time

from ..common import assert_records, http

ROW_RX = re.compile(r'<a[^>]+href="(?P<href>[^"]*/JobDetail/[^"]+)"[^>]*>(?P<title>[^<]+)</a>', re.I)


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
                "id": href.rstrip("/").split("/")[-1],
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
JSONLD_DATE_RX = re.compile(r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def resolve_job_page(cfg, record):
    """Consulting boards hide 40+ cities behind "Multiple Locations"; the job page lists them."""
    html = http(record["url"])
    block = LOC_BLOCK_RX.search(html)
    if block:
        record["locations"] = CITY_RX.findall(block.group(1)) or record["locations"]
    date = JSONLD_DATE_RX.search(html)
    if date:
        record["date"] = date.group(1)
    return record
