"""Oracle HCM recruiting sites.

expand=requisitionList.secondaryLocations is REQUIRED or you get facets and no jobs.
Run every keyword in the board's set and union by req id.
"""
import urllib.parse

from ..common import BoardError, assert_records, http, iso_date

TEMPLATE = ("{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
            "&expand=requisitionList.secondaryLocations"
            "&finder=findReqs;siteNumber={site},limit={limit},offset={offset},keyword={kw}")


def _page(cfg, keyword, offset):
    url = TEMPLATE.format(host=cfg["host"], site=cfg["site"], limit=cfg.get("limit", 200),
                          offset=offset, kw=urllib.parse.quote(keyword))
    data = http(url, expect_json=True)
    items = (data.get("items") or [{}])[0]
    if "requisitionList" not in items:
        raise BoardError(f"{cfg['slug']}: no requisitionList for {keyword!r} — expand param lost?")
    return items.get("requisitionList", []), items.get("TotalJobsCount", 0)


def fetch(cfg):
    seen, partials = {}, []
    for kw in cfg["keywords"]:
        offset, total = 0, None
        while True:
            reqs, total = _page(cfg, kw, offset)
            for r in reqs:
                locs = [r.get("PrimaryLocation")] + [s.get("Name") for s in r.get("secondaryLocations") or []]
                seen[r.get("Id")] = {
                    "id": r.get("Id", ""),
                    "title": r.get("Title", ""),
                    "locations": [l for l in locs if l],
                    "url": cfg["url_shape"].format(id=r.get("Id")),
                    "date": iso_date(r.get("PostedDate")),
                    "date_note": "",
                }
            offset += cfg.get("limit", 200)
            if offset >= min(total or 0, cfg.get("max_records_per_keyword", 10_000)):
                if total and offset < total:
                    partials.append(f"{kw}: read {offset} of {total}")
                break
            if not reqs:
                break
    records = list(seen.values())
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    if partials:
        records[0].setdefault("_partial", "; ".join(partials))
    return records
