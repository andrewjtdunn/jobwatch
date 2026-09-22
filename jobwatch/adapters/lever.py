"""Lever postings API. categories.allLocations carries the full list."""
from ..common import assert_records, http, iso_date


def fetch(cfg):
    jobs = http(cfg["endpoint"], expect_json=True)
    assert_records(cfg["slug"], jobs, minimum=cfg.get("min_records", 1))
    out = []
    for j in jobs:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or ([cat.get("location")] if cat.get("location") else [])
        if (j.get("workplaceType") or "").lower() == "remote":
            locs = list(locs) + ["Remote"]
        out.append({
            "id": j.get("id", ""),
            "title": j.get("text", ""),
            "locations": locs,
            "url": j.get("hostedUrl", ""),
            "date": iso_date(j.get("createdAt")),
            "date_note": "Date is Lever createdAt",
        })
    return out
