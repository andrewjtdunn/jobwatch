#!/usr/bin/env python3
"""Compare today's run against the previous run's baseline and print the alerts block.

  python health.py --status out/status --baseline "slug:records/cands;..." \
                   --canaries "slug=id;..." [--refound "slug:found/expected;..."]

Prints a Markdown "Board health" section and the compact counts string to carry into the
next run. Exit 2 = Red (a board failed, or a canary vanished), 1 = Amber, 0 = Green.
"""
import argparse
import glob
import json
import os

FLOOR = 0.6          # today's records must be at least this share of the baseline
REFOUND_DROP = 0.25  # a re-found rate falling this far vs baseline is a parser smell


def parse_counts(s):
    out = {}
    for part in (s or "").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        slug, rest = part.split(":", 1)
        rest = rest.rstrip("!")
        if "/" not in rest:
            continue
        rec, cand = rest.split("/", 1)
        if rec.isdigit() and cand.isdigit():
            out[slug] = (int(rec), int(cand))
    return out


def parse_pairs(s, sep="="):
    out = {}
    for part in (s or "").split(";"):
        if sep in part:
            k, v = part.split(sep, 1)
            out[k.strip()] = v.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="out/status")
    ap.add_argument("--baseline", default="")
    ap.add_argument("--canaries", default="")
    ap.add_argument("--refound", default="")
    args = ap.parse_args()

    base = parse_counts(args.baseline)
    canaries = parse_pairs(args.canaries)
    alerts, counts = [], []

    for path in sorted(glob.glob(f"{args.status}/*.json")):
        s = json.load(open(path))
        slug = s.get("slug") or os.path.basename(path)[:-5]
        rec, cand = s.get("records_read", 0), s.get("candidates", 0)
        counts.append(f"{slug}:{rec}/{cand}{'' if s.get('ok') else '!'}")

        if not s.get("ok"):
            alerts.append(f"**{slug} — FAILED.** {s.get('error', '')}")
            continue
        if slug in base:
            was = base[slug][0]
            if was and rec < was * FLOOR:
                alerts.append(
                    f"**{slug} — read {rec} records, baseline {was} "
                    f"({rec / was:.0%}).** Below the {FLOOR:.0%} floor; treat as under-reading, not a quiet board.")
            if base[slug][1] > 0 and cand == 0:
                alerts.append(
                    f"**{slug} — 0 candidates, baseline {base[slug][1]}.** Records parsed, "
                    "so suspect a field or filter change rather than an empty board.")
        if slug in canaries:
            cid = canaries[slug]
            if not any(cid in str(x) for x in s.get("seen_ids", [])):
                alerts.append(
                    f"**{slug} — canary {cid} not re-found.** Verify that posting directly: "
                    "if it is still live, this board is under-reading.")
        if s.get("partial"):
            alerts.append(f"{slug} — partial read: {s['partial']}")

    if args.refound:
        today = parse_pairs(args.refound, ":")
        for slug, frac in today.items():
            try:
                found, expected = (int(x) for x in frac.split("/"))
            except ValueError:
                continue
            if expected >= 5 and found / expected < REFOUND_DROP:
                alerts.append(
                    f"**{slug} — only {found}/{expected} existing postings re-found.** "
                    "Either the board purged, or the parser stopped seeing them.")

    red = any(a.startswith("**") and ("FAILED" in a or "canary" in a) for a in alerts)
    print("## ⚠️ Board health\n")
    print("\n".join(f"- {a}" for a in alerts) if alerts
          else f"- {len(counts)} boards, all within normal range.")
    print("\n### Counts (carry into the next run)\n")
    print(";".join(counts))
    return 2 if red else (1 if alerts else 0)


if __name__ == "__main__":
    raise SystemExit(main())
