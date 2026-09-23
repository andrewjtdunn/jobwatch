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

NYC_RX = re.compile(
    r"\b(new york|nyc|manhattan|brooklyn|queens|the bronx|bronx|staten island|"
    r"long island city|jersey city|hoboken|white plains|yonkers|stamford|morristown|"
    r"princeton|pennington|purchase|harrison|westchester|nassau|suffolk|"
    r"west brentwood)\b", re.I)
NEWARK_NJ_RX = re.compile(r"newark,?\s*(nj|new jersey)\b", re.I)
# Newark, DE is not Newark, NJ.
NOT_NYC_RX = re.compile(r"newark,?\s*(de|delaware)", re.I)
# A bare "NY" token ("Acme NY", "NY - New York") means the New York office.
NY_BARE_RX = re.compile(r"(^|[^A-Za-z])NY($|[^A-Za-z])")
REMOTE_RX = re.compile(r"\bremote\b|\bwfh\b|work from home|work at home|virtual office|anywhere", re.I)
# A remote token that positively scopes itself to the US. Without one of these, a bare
# "Remote" beside an office is that office's remote-work flag, not a US-remote role.
US_REMOTE_RX = re.compile(
    r"remote[\s\-\u2013(,]*(us|u\.s\.|usa|united states|north america|nationwide)\b|"
    r"\b(us|u\.s\.|usa|united states)[\s\-\u2013]*remote|"
    r"anywhere in the (us|united states)|work from home[\s\-\u2013,]*(us|usa)\b", re.I)
# A location that is nothing but a remote token, i.e. names no place at all.
BARE_REMOTE_RX = re.compile(
    r"^(remote|fully remote|remote work|remote - flexible|virtual|virtual office|wfh|"
    r"work from home|work at home|anywhere)$", re.I)
# "MYS - Kuala Lumpur", "CZE - Prague": an ISO-3166 alpha-3 prefix that is not USA.
ISO_NON_US_RX = re.compile(r"^(?!USA\b)[A-Z]{3}\s*[-\u2013]\s*")
US_PLACE_RX = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|"
    r"NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b|"
    r"\b(alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|"
    r"georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|"
    r"massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|"
    r"new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|"
    r"oklahoma|oregon|pennsylvania|rhode island|south carolina|tennessee|texas|utah|"
    r"vermont|virginia|washington|west virginia|wisconsin|wyoming|"
    r"district of columbia|united states)\b|\bUSA\b", re.I)



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


def location_verdict(locations):
    """Where a posting stands against "NYC metro, or fully remote / remote-first".

    Returns "nyc", "remote", "ambiguous", or None.

    ALL-LOCATIONS RULE: any listed location being NYC metro qualifies, however far down
    the list it sits. But the remote leg needs POSITIVE evidence of US-wide remote work.
    A bare "Remote" sitting beside a specific office is that office's remote-work flag:
    beside a non-US office it means remote-in-that-country, and beside a US office it
    means a hybrid role anchored to a city that is not New York. Neither is what we want,
    and treating them as remote is what surfaced roles in other countries and other US cities as
    NYC-eligible on 2026-09-23. Deciding this from a blocklist of foreign city names was
    the original mistake: the list can only ever be incomplete.
    """
    locs = [(l or "").strip() for l in (locations or []) if (l or "").strip()]
    if not locs:
        return None
    for s in locs:                                   # --- NYC leg
        if NOT_NYC_RX.search(s):
            continue
        if NYC_RX.search(s) or NEWARK_NJ_RX.search(s) or NY_BARE_RX.search(s):
            return "nyc"
    remote_toks = [s for s in locs if REMOTE_RX.search(s)]
    if not remote_toks:                              # --- no NYC, no remote
        return None
    if any(US_REMOTE_RX.search(s) for s in remote_toks):
        return "remote"                              # "Remote - US" and friends
    anchors = [s for s in locs if not BARE_REMOTE_RX.match(s)]
    if not anchors:
        return "remote"                              # listed as remote, anchored nowhere
    if all(REMOTE_RX.search(a) and US_PLACE_RX.search(a) for a in anchors):
        # "AZ - Work from home": genuinely remote, but anchored to a state for payroll and
        # the req may require residence there. Surface it, flagged, rather than drop it.
        return "ambiguous"
    return None


def location_ok(locations) -> bool:
    """True when a posting is worth surfacing on location. Ambiguous cases count: the
    human would rather dismiss a flagged maybe than lose it to an invisible filter."""
    return location_verdict(locations) is not None


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
        # Show the location that actually qualified, and never let a bare "Remote"
        # stand in front of the office the role is really anchored to.
        nyc = next((l for l in self.locations
                    if not NOT_NYC_RX.search(l)
                    and (NYC_RX.search(l) or NEWARK_NJ_RX.search(l) or NY_BARE_RX.search(l))), None)
        us_remote = next((l for l in self.locations if US_REMOTE_RX.search(l)), None)
        anchors = [l for l in self.locations if not BARE_REMOTE_RX.match(l)]
        extra = len(self.locations) - 1
        loc = nyc or us_remote or (anchors[0] if anchors else
                                   (self.locations[0] if self.locations else ""))
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
