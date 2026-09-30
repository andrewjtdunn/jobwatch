#!/usr/bin/env python3
"""Fail the build if a targeted employer has leaked into this PUBLIC repo.

  python3 privacy_audit.py --targets ~/jobwatch-tmp/targets.json --repo .
  python3 privacy_audit.py --targets targets.json --repo . --history   # also scan git log

Exit code is the NUMBER OF FINDINGS, so a caller can treat non-zero as an alert.

WHY THIS EXISTS. The repo is public; the board list, the endpoints and the criteria are
private and live in Notion. That separation is the whole privacy model, and it is held
together by nothing but care. On 2026-09-30 a single patch leaked three employer names
into code comments and a real posting URL into a test fixture, and it was caught only
because someone happened to grep. A leak here is worse than any board fault: it is
silent, and `git` makes it permanent.

WHY IT IS FUSSY ABOUT NOISE. A naive "does any company name appear" scan flags `board`,
ordinary nouns, because employer names are made of ordinary words. An audit that cries wolf is an audit that gets ignored, so a token is only
reported when it is DISTINCTIVE: long enough, not an ordinary English or
domain word, and not a word this repo legitimately needs. Full company names and
endpoint hosts are always reported, however common their parts.

The targets file is PRIVATE INPUT. Point at it outside the repo; never commit it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Ordinary words, and words this repo needs for its own vocabulary. A company name
# built only from these is reported by its FULL name, never by a single token.
COMMON = {
    # the repo's own domain language
    "board", "boards", "job", "jobs", "career", "careers", "posting", "postings",
    "data", "analytics", "analyst", "science", "scientist", "research", "remote",
    "location", "locations", "title", "titles", "search", "index", "roster", "status",
    "adapter", "adapters", "config", "params", "record", "records", "page", "pages",
    "token", "tokens", "slug", "slugs", "date", "dates", "test", "tests", "run",
    # ordinary corporate filler
    "inc", "llc", "ltd", "corp", "company", "companies", "group", "holdings", "partners",
    "technologies", "technology", "solutions", "services", "systems", "global", "labs",
    "digital", "ventures", "capital", "financial", "finance", "bank", "banking", "fund",
    "health", "healthcare", "medical", "clinical", "care", "credit", "money", "pay",
    "institute", "foundation", "university", "college", "school", "center", "centre",
    "national", "american", "america", "united", "states", "federal", "state", "city",
    "county", "authority", "department", "bureau", "office", "agency", "public",
    "coalition", "netwrk_", "curr_", "blk_", "first", "one", "two",
    "new", "york", "metro", "east", "west", "north", "south", "central",
    "people", "team", "work", "works", "studio", "media", "market", "markets",
    "open", "link", "next", "core", "prime", "star", "light", "edge", "wave", "flow",
    "development", "management", "consulting", "advisors", "advisory", "associates",
    # words that produced false positives on the first real run of this script
    "union", "unions", "spring", "summer", "winter", "autumn", "block", "blocks",
    "current", "currently", "network", "networks", "reset", "shift",
    # generic hostname labels: these are subdomains, never the employer
    "apply", "jobs", "job", "careers", "career", "recruiting", "recruit", "boards",
    "board", "hire", "hiring", "talent", "join", "work", "people", "www", "api",
    "search", "portal", "external", "internal", "candidate", "candidates",
}

# ATS and job-board PLATFORMS. A platform host says nothing about WHICH employer is
# targeted -- many employers share one -- so matching it is pure noise. A host used by
# more than one employer is detected as a platform automatically; this list covers the
# case where only one target happens to sit on a given platform.
PLATFORM_HOSTS = {
    "greenhouse.io", "boards-api.greenhouse.io", "job-boards.greenhouse.io",
    "boards.greenhouse.io", "ashbyhq.com", "api.ashbyhq.com", "jobs.ashbyhq.com",
    "lever.co", "api.lever.co", "jobs.lever.co", "workable.com", "apply.workable.com",
    "jobvite.com", "jobs.jobvite.com", "myworkdayjobs.com", "myworkdaysite.com",
    "icims.com", "oraclecloud.com", "ocs.oraclecloud.com", "recruiting2.ultipro.com",
    "ultipro.com", "workforcenow.adp.com", "adp.com", "applytojob.com", "breezy.hr",
    "trakstar.com", "hire.trakstar.com", "eightfold.ai", "jobs.deel.com", "deel.com",
    "smartrecruiters.com", "taleo.net", "avature.net", "phenompeople.com",
}


def _is_platform(host, host_owners):
    if host in PLATFORM_HOSTS:
        return True
    if any(host.endswith("." + p) or host == p for p in PLATFORM_HOSTS):
        return True
    return len(host_owners.get(host, ())) > 1

# Files that legitimately hold private data and are not part of the public repo.
SKIP_NAMES = {"boards.json", "targets.json", "params.json", "dedupe_index.txt"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}
TEXT_EXT = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini",
            ".sh", ".html", ".rst", ""}


# \b does NOT fire against an underscore, because _ is a word character: a pattern
# ending \b never matches inside ZORPTEK_ANALYTICS_LIMIT. SCREAMING_SNAKE constants are
# exactly where a name leaks, so use explicit alphanumeric boundaries instead.
EDGE_L = r"(?<![A-Za-z0-9])"
EDGE_R = r"(?![A-Za-z0-9])"


def slugify(name):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (name or "").lower())).strip("-")


def load_targets(path):
    """Accepts the raw Notion row shape the daily run writes."""
    with open(path) as fh:
        rows = json.load(fh)
    if isinstance(rows, dict):
        rows = rows.get("results") or rows.get("rows") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = (r.get("Company") or r.get("company") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "endpoints": [v for v in (r.get("Fetch Endpoint"), r.get("Careers URL")) if v],
        })
    return out


def needles(targets):
    """Build the search set. Each needle is (kind, pattern, label).

    Two kinds of thing are deliberately NOT searched for, because searching for them
    produces noise that gets the whole audit ignored:

      * PLATFORM HOSTS. Many employers share one ATS host, so the host identifies the
        platform, not the target.
      * ONE-WORD EMPLOYER NAMES THAT ARE ORDINARY WORDS. A target called after a common
        noun cannot be distinguished from that noun by grep. Those are returned
        separately as `unauditable` so the caller can say so out loud rather than
        quietly passing.
    """
    host_owners = {}
    for t in targets:
        for ep in t["endpoints"]:
            host = re.sub(r"^https?://", "", ep).split("/")[0].lower()
            if host:
                host_owners.setdefault(host, set()).add(t["name"])

    found, seen, unauditable = [], set(), []

    def add(kind, pattern, label):
        key = (kind, pattern.lower())
        if key not in seen:
            seen.add(key)
            found.append((kind, pattern, label))

    for t in targets:
        name = t["name"]
        words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
        distinctive = [w for w in words if len(w) >= 4 and w.lower() not in COMMON]

        if len(words) == 1 and not distinctive:
            unauditable.append(name)          # an ordinary word; grep cannot judge it
        else:
            add("name", EDGE_L + r"[^A-Za-z0-9]{0,2}".join(map(re.escape, words)) + EDGE_R, name)
            add("slug", EDGE_L + re.escape(slugify(name)) + EDGE_R, name)
            for w in distinctive:
                if len(w) >= 5:          # a 4-letter token alone is too collision-prone
                    add("token", EDGE_L + re.escape(w) + EDGE_R, name)

        for ep in t["endpoints"]:
            host = re.sub(r"^https?://", "", ep).split("/")[0].lower()
            if not host or _is_platform(host, host_owners):
                continue
            add("host", re.escape(host), name)
            # The employer sits in the REGISTRABLE label, not the first subdomain:
            # in apply.<employer>.com the first label is "apply" and matching it flags
            # every other apply.* host in the tree. Found on this script's first run.
            parts = [p for p in host.split(".") if p]
            label = parts[-2] if len(parts) >= 2 else ""
            if len(label) >= 4 and label not in COMMON and not label.isdigit():
                add("host", EDGE_L + re.escape(label) + EDGE_R, name)

        # A tenant id inside a platform URL path IS identifying: the path segment after
        # a known platform host is usually the employer's own account name.
        for ep in t["endpoints"]:
            m = re.search(r"(?:job-board|boards|postings|v1/boards)/([A-Za-z0-9_-]{4,})", ep)
            if m and m.group(1).lower() not in COMMON:
                add("tenant", EDGE_L + re.escape(m.group(1)) + EDGE_R, name)

    return found, unauditable


def repo_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_NAMES:
                continue
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                continue
            yield os.path.join(dirpath, fn)


def scan_text(text, pats, where):
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:            # a minified blob is not prose; skip it
            continue
        for kind, pattern, label in pats:
            if re.search(pattern, line, re.I):
                hits.append((where, i, kind, label, line.strip()[:120]))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True, help="private targets.json (keep it OUT of the repo)")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--history", action="store_true",
                    help="also scan committed history; slow, and findings there cannot be "
                         "removed by editing files. NOTE: a shallow clone (git clone "
                         "--depth 1, which the daily run uses) has almost no history, so "
                         "this finds nothing there regardless. Run it on a full clone.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    targets = load_targets(args.targets)
    pats, unauditable = needles(targets)
    if not args.quiet:
        print(f"privacy_audit: {len(targets)} employers -> {len(pats)} needles")
        if unauditable:
            print(f"privacy_audit: {len(unauditable)} one-word name(s) are ordinary words "
                  f"and CANNOT be checked by grep -- review these by eye: "
                  + ", ".join(sorted(unauditable)))

    findings = []
    for path in repo_files(args.repo):
        try:
            with open(path, errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        findings += scan_text(text, pats, os.path.relpath(path, args.repo))

    hist = []
    if args.history:
        shallow = os.path.exists(os.path.join(args.repo, ".git", "shallow"))
        depth = subprocess.run(["git", "-C", args.repo, "rev-list", "--count", "HEAD"],
                               capture_output=True, text=True).stdout.strip()
        if shallow or depth in ("", "1"):
            print("privacy_audit: WARNING - this is a SHALLOW clone "
                  f"({depth or '?'} commit(s)). A history scan here proves nothing. "
                  "Re-run on a full clone to audit history.")
        try:
            log = subprocess.run(["git", "-C", args.repo, "log", "-p", "--no-color"],
                                 capture_output=True, text=True, timeout=180).stdout
            hist = scan_text(log, pats, "git-history")
        except Exception as e:                                    # noqa: BLE001
            print(f"privacy_audit: history scan skipped ({type(e).__name__})")

    for where, line, kind, label, snippet in findings:
        print(f"LEAK {where}:{line}  [{kind}: {label}]  {snippet}")
    if hist:
        seen = set()
        for _, _, kind, label, _ in hist:
            if (kind, label) not in seen:
                seen.add((kind, label))
                print(f"HISTORY [{kind}: {label}] present in committed history")
        print("\nHistory findings cannot be fixed by editing the working tree. Rewriting "
              "published history is a decision for the repo owner, not for this script.")

    if not findings and not args.quiet:
        print("privacy_audit: clean — no employer name, slug or endpoint host in the working tree")
    # Exit code is the working-tree finding count: that is what a run can actually fix.
    sys.exit(min(len(findings), 250))


if __name__ == "__main__":
    main()
