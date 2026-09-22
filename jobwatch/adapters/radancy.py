"""Radancy-style careers sites, which expose their own search-results endpoint returning
100 records per page with title, location and posted date in one request.

The site's location parameter is silently ignored on these boards, so location is filtered
client-side. cfg supplies "base" (the site root) and "org" (the numeric org id in job
URLs); nothing about a specific employer lives in this file.
"""
import re
import time

from ..common import assert_records, http, iso_date

RESULTS = ("{base}/search-jobs/results?ActiveFacetID=0&CurrentPage={page}"
           "&RecordsPerPage=100&Distance=50&RadiusUnitType=0&Keywords={kw}&Location=&ShowRadius=False"
           "&IsPagination=True&SearchResultsModuleName=Search+Results&SearchFiltersModuleName=Search+Filters"
           "&SortCriteria=0&SortDirection=0&SearchType=5")
JOB_RX = re.compile(
    r'<a[^>]+href="(?P<href>/job/[^"]+)"[^>]*>.*?<h2[^>]*>(?P<title>.*?)</h2>.*?'
    r'(?:<span[^>]*class="job-location"[^>]*>(?P<loc>.*?)</span>)?.*?'
    r'(?:<span[^>]*class="job-date-posted"[^>]*>(?P<date>[^<]*)</span>)?',
    re.S | re.I)
TAG_RX = re.compile(r"<[^>]+>")


def fetch(cfg):
    seen = {}
    for kw in cfg["keywords"]:
        for page in range(1, cfg.get("max_pages", 8) + 1):
            url = RESULTS.format(base=cfg["base"].rstrip("/"), page=page, kw=kw.replace(" ", "+"))
            data = http(url, expect_json=True)
            html = data.get("results", "")
            hits = list(JOB_RX.finditer(html))
            if not hits:
                break
            for m in hits:
                href = m.group("href")
                seen[href] = {
                    "id": href.rstrip("/").split("/")[-1],
                    "title": TAG_RX.sub("", m.group("title") or "").strip(),
                    "locations": [TAG_RX.sub("", m.group("loc") or "").strip()],
                    "url": cfg["base"].rstrip("/") + href,
                    "date": iso_date((m.group("date") or "").strip()),
                    "date_note": "",
                }
            time.sleep(1.0)
    records = list(seen.values())
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    return records
