"""Breezy HR public feed: https://<slug>.breezy.hr/json.

One call, no paging, and the body is a JSON ARRAY at the top level (not an object with a
.jobs key). An empty array is a real, common state for a small company and is a clean
read; anything that is not an array is a failure. So these boards default to
min_records 0 and the shape check, not a floor, is what tells empty from broken.

Each item carries name, url, published_date, and location / locations[] objects of the
form {city, state{name}, country{name, id}, is_remote, name}. Remote is read
conservatively: an is_remote entry naming no city becomes "Remote - <country>" (so a US
one reads as US-wide remote); beside a city it stays a bare "Remote", which the location
rule treats as that office's flag.
"""
from ..common import BoardError, assert_records, http, iso_date


def _label(loc):
    loc = loc or {}
    city = (loc.get("city") or "").strip()
    state = ((loc.get("state") or {}).get("name") or "").strip()
    country = ((loc.get("country") or {}).get("name") or "").strip()
    out = []
    place = ", ".join(p for p in (city, state) if p)
    if place:
        out.append(place)
    if loc.get("is_remote"):
        out.append(f"Remote - {country}" if country and not city else "Remote")
    if not out and (loc.get("name") or "").strip():
        out.append(loc["name"].strip())
    return out


def _url(u):
    u = u.strip()
    return u if not u or u.startswith("http") else "https://" + u.lstrip("/")


def parse(items):
    out = []
    for j in items:
        locs = []
        for loc in (j.get("locations") or []) or [j.get("location")]:
            for label in _label(loc):
                if label not in locs:
                    locs.append(label)
        if not locs:
            for label in _label(j.get("location")):
                locs.append(label)
        out.append({
            "id": j.get("id") or j.get("friendly_id") or "",
            "title": (j.get("name") or "").strip(),
            "locations": locs,
            "url": _url(j.get("url") or ""),
            "date": iso_date(j.get("published_date")),
            "date_note": "",
        })
    return out


def fetch(cfg):
    data = http(cfg["endpoint"], expect_json=True)
    if not isinstance(data, list):
        raise BoardError(f"{cfg['slug']}: feed is not a JSON array ({type(data).__name__}); "
                         "the slug moved or the route changed")
    records = parse(data)
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 0))
    return records
