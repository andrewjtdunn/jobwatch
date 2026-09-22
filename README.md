# jobwatch

Adapters for reading public job boards, plus the health checks that tell you when one has
quietly stopped returning results.

The repo is deliberately impersonal: **it contains no board list.** Which employers to
watch, their endpoints, the matching criteria and the results all live in the caller's own
private store. `make_config.py` turns a private export of that list into the `boards.json`
this code reads, and `boards.json` is gitignored.

## Running it

    python3 make_config.py --targets targets.json --params params.json --out boards.json
    python3 run.py --group ashby --out out/
    python3 run.py --board example-co --out out/
    python3 run.py --out out/                     # every board with an adapter

Per board it writes `out/cands/<slug>.json` (postings that pass the title and location
rules) and `out/status/<slug>.json` (counts, seen ids, errors). The exit code is the
number of boards that **failed**, which is what lets a caller tell "nothing new" apart
from "nothing read".

    python3 health.py --status out/status --baseline "<counts from the last run>" \
                      --canaries "<canary ids from the last run>"

prints the board-health block and the new counts string. Exit 2 = Red (a board failed or a
canary vanished), 1 = Amber, 0 = Green.

## Silent staleness

A board that returns HTTP 200, parses cleanly and yields nothing is the failure mode that
actually happens, and no single run can detect it. Four checks, in the order they earn
their keep:

1. **Floors.** Every board carries `min_records`, learned from real runs. Under it raises
   `BoardError`; it never returns quietly.
2. **Baseline comparison.** `health.py` flags any board reading below 60% of its last
   recorded count, and any board returning zero candidates where the baseline had some.
3. **Canaries.** One known-live posting id per board, carried between runs. Not re-found
   means: go check that posting. Still live? The parser broke.
4. **Field coverage.** `assert_field_coverage` fails a board when a field the parser
   depends on goes empty across most records — which is how one sitemap board's JSON-LD
   locality field disappeared and silently took its local roles with it.

`tests/test_parsers.py` runs offline against synthetic fixtures, so a refactor cannot
quietly change what a parser returns. CI runs it on every push and never touches a live
board.

## Adapters

`ashby`, `greenhouse`, `workable`, `lever`, `oracle` (Oracle HCM), `workday`, `avature`,
`capitalone` (Radancy-style results endpoint), `jobvite`, `sitemap`, `socrata`.

Each exposes `fetch(cfg)` returning records of
`{id, title, locations[], url, date, date_note}`. Optional `resolve_*` helpers do second
passes — Workday's "N Locations" rows, Avature job pages, sitemap job pages — and run only
for rows that already passed the title filter, so a board costs one request per page plus
a handful of detail fetches.

Adding a board is usually a row in the private export, not code here. Write an adapter
only for a genuine oddity; anything `make_config.py` cannot map is reported as needing a
different route rather than silently skipped.

## Deliberately not here

- **Criteria and match levels.** Whether a posting fits someone's search is judgment, not
  regex. These scripts over-include on purpose: `title_hit` and `location_ok` are wide,
  and the caller decides.
- **Dates that cannot be justified.** `iso_date` returns `None` rather than a guess. A
  wrong date is worse than a blank one because it looks authoritative when sorted.
- **Credentials.** Nothing here authenticates to anything. Every board it reads is public.
- **Any board list, employer name, endpoint or result.** See above; that is the point.

## Courtesy

Public boards, once a day, a handful of pages each. Requests are paced, retries are capped
at one, and a 403 or 429 is recorded as a failure rather than retried differently.
