"""Jobvite boards. The list markup changed in Sept 2026; zero anchors is a FAILURE, not
an empty board."""
import re

from ..common import assert_records, http

ROW_RX = re.compile(r'class="jv-job-list-name">\s*<a href="([^"]+)">(.*?)</a>', re.S | re.I)
TAG_RX = re.compile(r"<[^>]+>")


def fetch(cfg):
    html = http(cfg["endpoint"])
    rows = ROW_RX.findall(html)
    records = [{
        "id": href.rstrip("/").split("/")[-1],
        "title": TAG_RX.sub("", title).strip(),
        "locations": cfg.get("default_locations", ["New York, NY"]),
        "url": href if href.startswith("http") else cfg["base"] + href,
        "date": None,
        "date_note": "Board publishes no posting date",
    } for href, title in rows]
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 20),
                   note="Jobvite markup may have changed again.")
    return records
