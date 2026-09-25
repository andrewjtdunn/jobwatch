#!/usr/bin/env python3
"""Build boards.json at runtime from a private Targets export.

Nothing in this repo names a company. The board list, its endpoints and any per-board
overrides live in the caller's own Targets table; this turns that export into the config
run.py reads, and prints which rows have no adapter and therefore need the agent path.

    python3 make_config.py --targets targets.json --out boards.json

    python3 make_config.py --targets targets.json --params params.json --out boards.json

The export is a JSON list of rows with at least: Company, Active, Category, Board Type,
Fetch Endpoint, Careers URL, and optionally Params (a JSON object of overrides). --params
is the same thing for every board at once, keyed by slug: keywords for the search-driven
boards, record floors learned from real runs, url shapes, sitemap settings. Both files are
private to the caller and neither is committed here.
"""
import argparse
import json
import re
import sys


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def infer_adapter(endpoint):
    e = (endpoint or "").lower()
    rules = [
        ("ashbyhq.com", "ashby"),
        ("boards-api.greenhouse.io", "greenhouse"),
        ("myworkdayjobs.com", "workday"),
        ("myworkdaysite.com", "workday"),
        ("oraclecloud.com", "oracle"),
        ("jobs.jobvite.com", "jobvite"),
        ("apply.workable.com", "workable"),
        ("jobs.lever.co", "lever"),
        ("icims.com", "icims"),
        ("/search-jobs", "radancy"),
    ]
    for needle, adapter in rules:
        if needle in e:
            return adapter
    if e.endswith(".xml") or "sitemap" in e:
        return "sitemap"
    if "/careers/searchjobs/" in e or "/careers/searchjobs" in e:
        return "avature"
    return None


def build(rows, *, radancy_adapter="radancy", overrides=None):
    overrides = overrides or {}
    boards, unsupported = [], []
    for row in rows:
        if (row.get("Active") or "").upper() not in ("__YES__", "YES", "TRUE"):
            continue
        company = (row.get("Company") or "").strip()
        if not company:
            continue
        endpoint = (row.get("Fetch Endpoint") or row.get("Careers URL") or "").strip()
        adapter = infer_adapter(endpoint)
        if adapter == "radancy":
            adapter = radancy_adapter
        cfg = {
            "slug": slugify(company),
            "company": company,
            "adapter": adapter,
            "categories": _as_list(row.get("Category")),
            "endpoint": endpoint.split("?")[0] if adapter == "greenhouse" else endpoint,
            "min_records": 1,
        }
        if adapter == "oracle":
            host = re.match(r"(https://[^/]+)", endpoint)
            site = re.search(r"siteNumber%3D(CX_\d+)", endpoint) or re.search(r"siteNumber=(CX_\d+)", endpoint)
            cfg.update(host=host.group(1) if host else "", site=site.group(1) if site else "CX_1",
                       keywords=["data scientist"], limit=200)
            cfg.setdefault("url_shape", cfg["host"] + "/hcmUI/CandidateExperience/en/sites/"
                           + cfg["site"] + "/job/{id}")
            cfg.pop("endpoint", None)
        if adapter == "workday":
            cfg["keywords"] = ["data scientist", "machine learning", "analytics"]
            cfg["url_shape"] = endpoint.replace("/wday/cxs", "").replace("/jobs", "") + "{path}"
        if adapter == "avature":
            cfg["base"] = re.match(r"(https://[^/]+)", endpoint).group(1)
            cfg.update(per_page=10, max_records=200)
        if adapter == "jobvite":
            cfg["base"] = "https://jobs.jobvite.com"
            cfg["min_records"] = 20
        if adapter == "sitemap":
            cfg["sitemaps"] = [endpoint]
            cfg.pop("endpoint", None)
        params = row.get("Params")
        if params:
            cfg.update(params if isinstance(params, dict) else json.loads(params))
        if cfg["slug"] in overrides:          # per-board overrides from the private params file
            cfg.update(overrides[cfg["slug"]])
        if not cfg["adapter"]:
            unsupported.append(cfg["slug"])
        boards.append(cfg)
    return boards, unsupported


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        return json.loads(value)
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True, help="JSON export of the private Targets table")
    ap.add_argument("--params", help="JSON file of per-board overrides, keyed by slug")
    ap.add_argument("--out", default="boards.json")
    args = ap.parse_args()
    rows = json.load(open(args.targets))
    rows = rows.get("results", rows) if isinstance(rows, dict) else rows
    overrides = json.load(open(args.params)) if args.params else {}
    boards, unsupported = build(rows, overrides=overrides)
    with open(args.out, "w") as fh:
        json.dump(boards, fh, indent=1)
    scripted = len(boards) - len(unsupported)
    print(f"{len(boards)} active boards -> {args.out}: {scripted} scripted, {len(unsupported)} need the agent path")
    if unsupported:
        print("agent path: " + ",".join(sorted(unsupported)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
