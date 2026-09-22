"""Shared helpers: HTTP, title/location matching, date normalisation, assertions."""
from __future__ import annotations

import dataclasses
import datetime as _dt
import gzip
import io
import json
import re
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; jobwatch/1.0; personal job-board check, once daily)"
TIMEOUT = 25

# 'analyt' does NOT match the word "Analyst" — keep 'analy'.
TITLE_RX = re.compile(
    r"data|analy|machine learning|[^a-z]ml[^a-z]|[^a-z]ai[^a-z]|scien|research|statist|quant",
    re.I,
)

# Evergreen pipelines that are never real openings.
EVERGREEN_RX = re.compile(
    r"resume bank|resume drop|future opportunit|general application|talent (community|network|pool)",
    re.I,
)

NYC_TOKENS = [
    "new york", "nyc", "manhattan", "brooklyn", "queens", "bronx", "staten island",
    "long island city", "jersey city", "newark, nj", "newark nj", "hoboken",
    "jersey city, nj", "white plains", "purchase, ny", "yonkers", "stamford",
    "morristown", "princeton", "newark, new jersey", "west brentwood", "suffolk",
    "westchester", "nassau", "harrison, ny", "pennington",
]
# Newark, DE is not Newark, NJ.
NOT_NYC_RX = re.compile(r"newark,?\s*(de|delaware)", re.I)
REMOTE_RX = re.compile(r"\bremote\b|work from home|wfh|remote-?usa|virtual office", re.I)
NON_US_RX = re.compile(
    r"costa rica|india|brazil|brasil|mexico|méxico|canada|ireland|united kingdom|london|"
    r"poland|philippines|singapore|australia|germany|france|spain|portugal|netherlands|"
    r"israel|japan|china|colombia|argentina|chile|peru|uruguay|sweden|switzerland|"
    r"são paulo|sao paulo|bogot|buenos aires|ciudad de m|mexico city|guadalajara|"
    r"melbourne|sydney|brisbane|auckland|berlin|munich|paris|amsterdam|dublin|madrid|"
    r"barcelona|lisbon|tel aviv|tokyo|bangalore|bengaluru|hyderabad|gurgaon|pune|"
    r"warsaw|krakow|kraków|manila|zurich|stockholm|copenhagen|toronto|vancouver|montreal",
    re.I,
)


class BoardError(RuntimeError):
    """A board could not be read. Never swallow this into 'no new jobs'."""


def http(url, *, data=None, headers=None, retries=2, expect_json=False):
    """GET/POST with a browser UA, gzip, and one retry on a reset connection."""
    hdrs = {"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        hdrs.setdefault("Content-Type", "application/json")
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                text = raw.decode("utf-8", "replace")
                if expect_json:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as e:
                        raise BoardError(f"PARSE-FAIL {url}: {e}") from e
                return text
        except urllib.error.HTTPError as e:
            # 429/403 are courtesy stops: record and move on, do not retry differently.
            raise BoardError(f"HTTP {e.code} {url}") from e
        except Exception as e:  # noqa: BLE001 - connection resets are common on Avature
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
    raise BoardError(f"{type(last).__name__} {url}: {last}")


def title_hit(title: str) -> bool:
    t = f" {title or ''} "
    return bool(TITLE_RX.search(t)) and not EVERGREEN_RX.search(t)


def location_ok(locations) -> bool:
    """ALL-LOCATIONS RULE: any listed location being NYC metro or US-remote qualifies.

    Judged over the whole set, not per item: a board may list "Remote" beside only
    non-US cities, where remote means remote-in-that-country.
    """
    locs = [(l or "").strip() for l in (locations or []) if (l or "").strip()]
    for s in locs:
        if NOT_NYC_RX.search(s):
            continue
        if any(tok in s.lower() for tok in NYC_TOKENS):
            return True
    non_us = any(NON_US_RX.search(s) for s in locs)
    remote = any(REMOTE_RX.search(s) for s in locs)
    return bool(remote and not non_us)


def iso_date(value, *, fmt=None):
    """Normalise a board's date to YYYY-MM-DD, or None. Never guess."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):  # epoch seconds or millis
        secs = value / 1000 if value > 10_000_000_000 else value
        return _dt.datetime.utcfromtimestamp(secs).date().isoformat()
    s = str(value).strip()
    if fmt:
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)  # non-zero-padded US format
    if m:
        mo, d, y = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def relative_date(text, *, today=None):
    """Workday-style 'Posted 3 Days Ago'. '30+ Days Ago' is not a date — return None."""
    if not text:
        return None
    t = str(text).lower()
    today = today or _dt.date.today()
    if "30+" in t:
        return None
    if "today" in t:
        return today.isoformat()
    if "yesterday" in t:
        return (today - _dt.timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*day", t)
    if m:
        return (today - _dt.timedelta(days=int(m.group(1)))).isoformat()
    return None  # weeks/months are too coarse to be honest


@dataclasses.dataclass
class Candidate:
    slug: str
    company: str
    role: str
    locations: list
    url: str
    req_id: str = ""
    date_posted: str = None
    date_note: str = ""
    flags: list = dataclasses.field(default_factory=list)

    def to_row(self, categories, *, loc_cap=80, why=""):
        qualifying = next((l for l in self.locations if location_ok([l])), None)
        extra = len(self.locations) - 1
        loc = qualifying or (self.locations[0] if self.locations else "")
        if extra > 0 and len(loc) < loc_cap:
            loc = f"{loc} +{extra} more"
        return {
            "Role": self.role,
            "Company": self.company,
            "Location": loc[:loc_cap],
            "userDefined:URL": self.url,
            "date:Date Posted:start": self.date_posted,
            "Category": json.dumps(categories),
            "Why": why[:140],
            "Notes": self.date_note,
        }


def assert_records(slug, records, *, minimum=1, note=""):
    """A board that returns fewer records than it must is a FAILURE, never 'no new jobs'."""
    if len(records) < minimum:
        raise BoardError(
            f"{slug}: read {len(records)} records, expected at least {minimum}. {note}".strip()
        )
    return records


def assert_field_coverage(slug, records, field, *, minimum=0.8):
    """Catches silent field drift, e.g. a board's JSON-LD locality going empty."""
    if not records:
        return records
    filled = sum(1 for r in records if r.get(field))
    ratio = filled / len(records)
    if ratio < minimum:
        raise BoardError(
            f"{slug}: field '{field}' populated on only {filled}/{len(records)} "
            f"records ({ratio:.0%} < {minimum:.0%}) — the board's shape probably changed."
        )
    return records


def assert_closes_with(slug, text, marker):
    """Sitemaps and HTML tables must arrive whole."""
    if marker not in text:
        raise BoardError(f"{slug}: response did not contain closing marker {marker!r} — truncated?")
    return text
