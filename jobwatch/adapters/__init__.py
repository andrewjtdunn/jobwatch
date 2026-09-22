"""Platform adapters. Each exposes fetch(cfg) -> list[record].

record = {"id", "title", "locations": [str], "url", "date": "YYYY-MM-DD"|None, "date_note"}
Most boards are a config row in boards.json, not code. Add code only for a real oddity.
"""
from . import ashby, greenhouse, workable, lever, oracle, workday, avature, radancy, jobvite, sitemap, socrata  # noqa: F401

REGISTRY = {
    "ashby": ashby,
    "greenhouse": greenhouse,
    "workable": workable,
    "lever": lever,
    "oracle": oracle,
    "workday": workday,
    "avature": avature,
    "radancy": radancy,
    "jobvite": jobvite,
    "sitemap": sitemap,
    "socrata": socrata,
}


def get(name):
    if name not in REGISTRY:
        raise KeyError(f"unknown adapter {name!r}; have {sorted(REGISTRY)}")
    return REGISTRY[name]
