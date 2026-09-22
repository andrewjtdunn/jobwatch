"""Workable widget API. Rate-limits hard (429): one attempt, then report a failure."""
from ..common import assert_records, http, iso_date


def fetch(cfg):
    data = http(cfg["endpoint"], expect_json=True, retries=0)
    jobs = data.get("jobs", data if isinstance(data, list) else [])
    assert_records(cfg["slug"], jobs, minimum=cfg.get("min_records", 1))
    return [{
        "id": j.get("shortcode", ""),
        "title": j.get("title", ""),
        "locations": [", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x)]
                     + (["Remote"] if j.get("telecommuting") else []),
        "url": j.get("url", ""),
        "date": iso_date(j.get("published_on")),
        "date_note": "",
    } for j in jobs]
