"""Socrata open-data job datasets. A where clause and a limit are both mandatory, and an
export can go stale without any error: check the newest posting_date before trusting it as
a primary route rather than a supplement."""
import urllib.parse

from ..common import assert_records, http, iso_date

WHERE = ("upper(business_title) like '%DATA%' or upper(business_title) like '%ANALY%' or "
         "upper(business_title) like '%SCIEN%' or upper(business_title) like '%RESEARCH%' or "
         "upper(business_title) like '%STATIST%'")


def fetch(cfg):
    q = urllib.parse.urlencode({
        "$select": "job_id,business_title,agency,work_location,posting_date,salary_range_from,salary_range_to",
        "$where": WHERE,
        "$order": "posting_date DESC",
        "$limit": cfg.get("limit", 400),
    })
    rows = http(f"{cfg['endpoint']}?{q}", expect_json=True)
    assert_records(cfg["slug"], rows, minimum=cfg.get("min_records", 50))
    return [{
        "id": str(r.get("job_id", "")),
        "title": r.get("business_title", ""),
        "locations": [r.get("work_location", "")],
        "url": cfg["url_shape"].format(id=r.get("job_id")),
        "date": iso_date(r.get("posting_date")),
        "date_note": "",
        "agency": r.get("agency", ""),
        "salary_from": r.get("salary_range_from"),
    } for r in rows]
