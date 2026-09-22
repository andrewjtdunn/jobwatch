"""Ashby posting API. Secondary locations matter: boards routinely list a headquarters as
the primary location and the office you care about only as a secondary one."""
from ..common import assert_records, http, iso_date


def fetch(cfg):
    data = http(cfg["endpoint"], expect_json=True)
    jobs = data.get("jobs", [])
    assert_records(cfg["slug"], jobs, minimum=cfg.get("min_records", 1))
    out = []
    for j in jobs:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []]
        if j.get("isRemote"):
            locs.append("Remote")
        out.append({
            "id": j.get("id", ""),
            "title": j.get("title", ""),
            "locations": [l for l in locs if l],
            "url": j.get("jobUrl", ""),
            "date": iso_date(j.get("publishedAt")),
            "date_note": "",
        })
    return out
