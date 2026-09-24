#!/usr/bin/env python3
"""Fetch job boards and write candidates + status.

  python run.py --group ashby --out out/
  python run.py --board example-co,other-co --out out/

Writes, per board:
  out/cands/<slug>.json    qualifying postings (title hit + all-locations rule)
  out/status/<slug>.json   {ok, records_read, title_hits, candidates, seen_ids, error, partial}

Exit code is the number of boards that FAILED, so a caller can tell "nothing new" from
"nothing read". A board is never allowed to fail quietly.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobwatch import adapters
from jobwatch.common import BoardError, location_ok, title_hit

GROUPS = {
    "ashby": ["ashby"],
    "greenhouse": ["greenhouse", "workable", "lever"],
    "workday": ["workday"],
    "oracle": ["oracle", "radancy"],
    "avature": ["avature"],
    "sitemap": ["sitemap"],
    "gov": ["socrata", "jobvite"],
}


def load_boards(path="boards.json"):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), path)) as fh:
        return json.load(fh)


def select(boards, args):
    if args.board:
        wanted = set(args.board.split(","))
        return [b for b in boards if b["slug"] in wanted]
    if args.group:
        kinds = GROUPS[args.group]
        return [b for b in boards if b.get("adapter") in kinds]
    return [b for b in boards if b.get("adapter")]


def run_board(cfg):
    mod = adapters.get(cfg["adapter"])
    records = mod.fetch(cfg)
    # Platform-specific second passes, only for rows we might actually keep.
    hits = [r for r in records if title_hit(r["title"])]
    if cfg["adapter"] == "workday" and hasattr(mod, "resolve_locations"):
        mod.resolve_locations(cfg, hits)
    if cfg["adapter"] == "sitemap" and hasattr(mod, "resolve"):
        mod.resolve(cfg, hits)
    if cfg["adapter"] == "avature":
        for r in hits[: cfg.get("max_detail_pages", 40)]:
            try:
                mod.resolve_job_page(cfg, r)
            except BoardError:
                pass
            time.sleep(0.5)
    cands = [r for r in hits if location_ok(r["locations"])]
    return records, hits, cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=sorted(GROUPS))
    ap.add_argument("--board")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    os.makedirs(f"{args.out}/cands", exist_ok=True)
    os.makedirs(f"{args.out}/status", exist_ok=True)

    failures = 0
    for cfg in select(load_boards(), args):
        slug = cfg["slug"]
        status = {"board": cfg["company"], "slug": slug, "adapter": cfg["adapter"],
                  "ok": False, "records_read": 0, "title_hits": 0, "candidates": 0,
                  "seen_ids": [], "error": "", "partial": "", "new_watermark": "",
                  "watermark_backlog": 0}
        try:
            records, hits, cands = run_board(cfg)
            status.update(ok=True, records_read=len(records), title_hits=len(hits),
                          candidates=len(cands),
                          seen_ids=[r["id"] for r in records if r.get("id")],
                          partial=records[0].get("_partial", "") if records else "")
            # A watermarked board only reads titles for what is new, so it must report the
            # mark it reached. Nothing here can write config; the caller persists it.
            if cfg.get("_new_watermark") is not None:
                status["new_watermark"] = str(cfg["_new_watermark"])
                status["watermark_backlog"] = cfg.get("_watermark_backlog", 0)
            with open(f"{args.out}/cands/{slug}.json", "w") as fh:
                json.dump([{k: v for k, v in c.items() if not k.startswith("_")} for c in cands], fh, indent=1)
            print(f"{slug:42s} ok  records={len(records):5d} hits={len(hits):4d} cands={len(cands):3d}")
        except BoardError as e:
            failures += 1
            status["error"] = str(e)
            print(f"{slug:42s} FAIL {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - an unexpected break is still a board failure
            failures += 1
            status["error"] = f"{type(e).__name__}: {e}"
            print(f"{slug:42s} FAIL {type(e).__name__}: {e}", file=sys.stderr)
        with open(f"{args.out}/status/{slug}.json", "w") as fh:
            json.dump(status, fh, indent=1)
    print(f"\n{failures} board(s) failed")
    return failures


if __name__ == "__main__":
    sys.exit(main())
