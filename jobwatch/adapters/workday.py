"""Workday CXS search. limit is capped at 20 regardless of what you ask for, and "N
Locations" rows must be resolved on the detail endpoint or the all-locations rule
silently fails."""
import time

from ..common import assert_records, http, relative_date


def _search(cfg, keyword, offset, facets=None):
    payload = {"appliedFacets": facets or {}, "limit": 20, "offset": offset, "searchText": keyword or ""}
    return http(cfg["endpoint"], data=payload, expect_json=True)


def _detail(cfg, external_path):
    base = cfg["endpoint"].rsplit("/jobs", 1)[0]
    data = http(base + external_path, expect_json=True)
    info = data.get("jobPostingInfo") or {}
    locs = [info.get("location")] + list(info.get("additionalLocations") or [])
    return [l for l in locs if l], info.get("startDate")


def fetch(cfg):
    seen = {}
    passes = [(k, None) for k in cfg.get("keywords", [""])]
    for facet in cfg.get("facet_passes", []):
        passes.append((facet.get("keyword", ""), facet.get("facets")))
    for keyword, facets in passes:
        offset, total = 0, None
        while True:
            data = _search(cfg, keyword, offset, facets)
            posts = data.get("jobPostings", [])
            total = data.get("total", total)
            for p in posts:
                path = p.get("externalPath", "")
                seen[path] = {
                    "id": p.get("bulletFields", [""])[0] if p.get("bulletFields") else path,
                    "title": p.get("title", ""),
                    "locations": [p.get("locationsText", "")],
                    "url": cfg["url_shape"].format(path=path),
                    "date": relative_date(p.get("postedOn")),
                    "date_note": "",
                    "_path": path,
                    "_multi": "location" in (p.get("locationsText") or "").lower()
                              and any(ch.isdigit() for ch in (p.get("locationsText") or "")),
                }
            offset += 20
            if not posts or (total is not None and offset >= total):
                break
            time.sleep(0.3)
    records = list(seen.values())
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    return records


def resolve_locations(cfg, records):
    """Second pass: only for title hits, and only where the row says 'N Locations'."""
    for r in records:
        if not r.get("_multi"):
            continue
        try:
            locs, start = _detail(cfg, r["_path"])
        except Exception:  # a single detail miss must not fail the board
            continue
        if locs:
            r["locations"] = locs
        if start and not r.get("date"):
            from ..common import iso_date
            r["date"] = iso_date(start)
        time.sleep(0.3)
    return records
