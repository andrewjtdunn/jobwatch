"""Greenhouse job board API. Use the BARE endpoint: content=false has returned 404s."""
from ..common import assert_records, http, iso_date

NOTE = "Date is Greenhouse updated_at (last-updated, approximate)"


def fetch(cfg):
    data = http(cfg["endpoint"], expect_json=True)
    jobs = data.get("jobs", [])
    assert_records(cfg["slug"], jobs, minimum=cfg.get("min_records", 1))
    total = (data.get("meta") or {}).get("total")
    if total is not None and len(jobs) != total:
        from ..common import BoardError
        raise BoardError(f"{cfg['slug']}: got {len(jobs)} of meta.total {total} — truncated read")
    out = []
    for j in jobs:
        name = ((j.get("location") or {}).get("name")) or ""
        locs = [p.strip() for p in name.replace("/", ";").split(";") if p.strip()]
        out.append({
            "id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "locations": locs,
            "url": j.get("absolute_url", ""),
            "date": iso_date(j.get("updated_at")),
            "date_note": NOTE,
        })
    return out
