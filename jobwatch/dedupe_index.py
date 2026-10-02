"""Dedupe keys for stored postings, and the compact index that carries them between runs.

THE PROBLEM THIS SOLVES. Dedupe needs every posting ever recorded, but the run reads
that set by paging the whole store every morning -- ~10 round trips for ~980 rows to
find ~45 new ones -- and the last short page arrives inline rather than as a file, so it
gets transcribed by hand. On 2026-09-29 that transcription happened to land exactly on
the row count; it is the most fragile step in the run and it grows every day.

Instead: keep a compact append-only INDEX of the keys dedupe actually needs, and read
that. One line per stored posting, and the line holds nothing but a board slug, the
posting's id tokens, and a normalised company||role key.

WHERE THE INDEX LIVES. Not here. The index contains employer slugs and posting ids, so
it is private and belongs beside Targets and Board Params. It also cannot live on disk:
the run's sandbox is rebuilt from scratch each morning, so anything written to a local
file is gone by the next run. This module is the generic reader/writer; the caller
supplies and persists the text.

THE ID PROBLEM. A posting's id appears in at least six shapes across boards, and the
stored URL and the board's own seen_ids are frequently in DIFFERENT shapes. Comparing
them as strings scored nine healthy boards at 0% on 2026-09-24 and five more on
2026-09-29. So both sides go through the same tokeniser and the comparison is a set
intersection in id space. That is the whole point of this module: one extractor, used on
both sides, tested.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------- tokens

def norm_id(value):
    """Case-fold and strip separators, so `R-571211` and `r571211` are one token."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def tokens(value):
    """Every plausible posting id in a URL *or* a bare seen_id.

    Run this over BOTH sides before comparing. The shapes it has to cope with, each
    found the hard way:
      Workday    stored `..._R-571211-1`, board emits `R-571211`  (trailing revision)
      iCIMS      id in a MID path segment, `/jobs/76849/<slug>/job`
      NYS        id in a QUERY PARAM, `?id=213466`
      Eightfold  numeric PREFIX of a long slug, `/job/274922258439-director-...`
      NYC jobs   `-jid-<n>` SUFFIX inside a slug
      slug-only  a bare title slug with NO number anywhere
    """
    out = set()
    if not value:
        return out
    value = str(value).split("#")[0]
    path, _, query = value.partition("?")

    for m in re.finditer(r"[?&]([A-Za-z_]+)=([A-Za-z0-9._\-]+)", "?" + query):
        if re.search(r"\d", m.group(2)):
            out.add(m.group(2))

    segs = [x for x in path.split("/") if x] if "/" in path else [path]
    for i, seg in enumerate(segs):
        if not seg:
            continue
        last = i == len(segs) - 1
        if seg.isdigit():
            # A short numeric MID segment is a location or tenant code, not an id. One
            # board's 4-digit location code is shared by every posting in that city and
            # suppressed two genuine rows on 2026-09-24 before this guard existed.
            if not last and len(seg) < 5:
                continue
            out.add(seg)
            continue
        if last:
            out.add(seg)                                   # slug-keyed boards live here
            m = re.match(r"^(\d{4,})", seg)
            if m:
                out.add(m.group(1))
            m = re.search(r"jid[-_]?(\d+)", seg)
            if m:
                out.add(m.group(1))
            if "_" in seg:
                tail = seg.rsplit("_", 1)[1]
                if re.search(r"\d", tail):
                    out.add(tail)
            for m in re.finditer(r"([A-Za-z]{0,2}-?\d{5,})", seg):
                out.add(m.group(1))
            for t in list(out):                            # trailing -N is a revision
                stripped = re.sub(r"-\d+$", "", t)
                if stripped != t and re.search(r"\d", stripped):
                    out.add(stripped)
        elif re.search(r"\d", seg) and len(re.sub(r"\D", "", seg)) >= 5:
            out.add(seg)
    return {t for t in out if t}


def translate(id_tokens, legacy_id_map=None):
    """Map old ids to current ones for a board that changed its identifier scheme.

    Without this, two URL forms of the SAME posting look like two postings: skipping it
    wrote 27 duplicates in one run on 2026-09-23.
    """
    out = set(id_tokens)
    if not legacy_id_map:
        return out
    folded = {norm_id(k): v for k, v in legacy_id_map.items()}
    for t in id_tokens:
        if t in legacy_id_map:
            out.add(legacy_id_map[t])
        hit = folded.get(norm_id(t))
        if hit:
            out.add(hit)
    return out


def boilerplate(id_sets, *, minimum_rows=5, share=0.40):
    """Tokens so common on one board that they identify nothing.

    A token on more than `share` of a board's stored rows is structural, not an id. This
    independently caught a shared year prefix on one board and a 4-digit location code on
    another, both of which were suppressing real postings.
    """
    if len(id_sets) < minimum_rows:
        return set()
    freq = {}
    for s in id_sets:
        for t in s:
            freq[norm_id(t)] = freq.get(norm_id(t), 0) + 1
    return {t for t, n in freq.items() if n > share * len(id_sets)}


# ------------------------------------------------------------------------- text keys

def norm_text(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def norm_text_hard(value):
    """For boards whose titles come from URL slugs, where punctuation differs.

    "Data Analyst & Program Evaluation Specialist, Bureau of X" against
    "Data Analyst And Program Evaluation Specialist Bureau Of X" is the same posting;
    the soft normaliser treats them as different and let 27 duplicates through.
    """
    value = re.sub(r"\([^)]*\)", " ", value or "")
    return " ".join(w for w in norm_text(value).split() if w not in {"and", "the", "of"})


def role_key(company, role, *, hard=False):
    fn = norm_text_hard if hard else norm_text
    return f"{fn(company)}||{fn(role)}"


# ----------------------------------------------------------------------------- index

SEP = "\t"


def index_line(slug, url, company, role, *, legacy_id_map=None):
    ids = sorted(norm_id(t) for t in translate(tokens(url), legacy_id_map))
    return SEP.join([slug, " ".join(ids), role_key(company, role)])


def render(rows, *, legacy_maps=None):
    """rows: iterable of (slug, url, company, role). Returns the index text."""
    legacy_maps = legacy_maps or {}
    out = []
    for slug, url, company, role in rows:
        out.append(index_line(slug, url, company, role,
                              legacy_id_map=legacy_maps.get(slug)))
    return "\n".join(out)


def parse(text):
    """Returns (ids_by_slug, role_keys, line_count)."""
    ids_by_slug, role_keys, n = {}, set(), 0
    for line in (text or "").splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split(SEP)
        if len(parts) < 3:
            continue
        slug, ids, key = parts[0], parts[1], parts[2]
        ids_by_slug.setdefault(slug, set()).update(t for t in ids.split() if t)
        role_keys.add(key)
        n += 1
    return ids_by_slug, role_keys, n


def is_duplicate(slug, url, company, role, ids_by_slug, role_keys, *, legacy_id_map=None):
    """DEPRECATED -- kept so old callers fail safe. Use DedupeIndex.judge().

    Returns "url" only when the id matches; it can no longer return "role", because a
    company+title match is NOT a duplicate (see DedupeIndex). It cannot check the title,
    so prefer judge(), which can.
    """
    mine = {norm_id(t) for t in translate(tokens(url), legacy_id_map)}
    if mine & ids_by_slug.get(slug, set()):
        return "url"
    return None


# ------------------------------------------------------------------- true duplicates
#
# THE RULE. A candidate is a duplicate ONLY when it is the same posting already stored:
# the SAME POSTING ID (after translating id forms) AND the SAME TITLE. Nothing else
# suppresses a row.
#
#   * Same title, different id  -> NOT a duplicate. Write it. Civil-service boards reuse
#     one title for unrelated jobs: on 2026-10-02 a company+title match suppressed a
#     second "Senior Data Scientist" at one employer -- a different team, different
#     duties, a different requisition number -- and on the same day it suppressed 22
#     other rows, most of them genuinely separate requisitions.
#   * Same id, different title  -> NOT a duplicate. Write it, and say in Notes that the
#     requisition was previously listed under another title.
#   * A token that identifies nothing is not an id. Path words ("job",
#     "detail", "listingview.cfm") and board GUIDs sit in EVERY url on
#     a board; the old pass 1 matched on them and suppressed three real postings on
#     2026-10-02. A token is structural if stored rows with DIFFERENT titles share it, or
#     if more than one of today's candidates on the board carries it.
#
# Title equality tolerates formatting only: case, punctuation, "&" vs "and", plurals,
# Sr/Senior, and words appended by slug derivation or a req-number suffix (one title's
# words being a subset of the other's). Because the id must ALSO match, that tolerance
# can never merge two different requisitions.
#
# When a board changes its id scheme (an ATS migration), every posting gets a new id and
# this rule will write them all again. That is deliberate: the fix is a legacy_id_map
# for that board, built once and checked, not a title match that guesses.

_ABBREV = {"sr": "senior", "jr": "junior", "mgr": "manager", "mgmt": "management",
           "eng": "engineer", "dir": "director", "assoc": "associate", "ml": "machine learning"}
_DROP = {"and", "the", "of", "a", "an", "for", "to", "with", "amp"}


def title_words(value):
    """The words of a title, normalised for formatting only."""
    import html
    v = html.unescape(value or "").lower().replace("&", " and ")
    out = []
    for w in re.sub(r"[^a-z0-9]+", " ", v).split():
        w = _ABBREV.get(w, w)
        for part in w.split():
            if part in _DROP:
                continue
            if len(part) > 3 and part.endswith("s") and not part.endswith("ss"):
                part = part[:-1]
            out.append(part)
    return set(out)


def same_title(a, b):
    """True when two titles differ only in formatting (see the rule above)."""
    wa, wb = title_words(a), title_words(b)
    if not wa or not wb:
        return False
    return wa <= wb or wb <= wa


def structural_tokens(urls, *, legacy_id_map=None):
    """Tokens carried by more than one of TODAY's postings on one board: not ids.

    Counted over DISTINCT urls: a keyword-union read returns one posting several times,
    and its id must not turn structural because of that.
    """
    seen = {}
    for u in set(urls):
        for t in {norm_id(x) for x in translate(tokens(u), legacy_id_map)}:
            seen[t] = seen.get(t, 0) + 1
    return {t for t, n in seen.items() if n > 1}


class Verdict:
    __slots__ = ("kind", "stored_key")
    DUPLICATE, RETITLED, SAME_TITLE, NEW = "duplicate", "retitled", "same_title", "new"

    def __init__(self, kind, stored_key=None):
        self.kind, self.stored_key = kind, stored_key

    @property
    def is_duplicate(self):
        return self.kind == self.DUPLICATE

    def __repr__(self):  # pragma: no cover
        return f"Verdict({self.kind!r}, {self.stored_key!r})"


class DedupeIndex:
    """The stored postings, line by line, with the true-duplicate test."""

    def __init__(self, text, *, legacy_maps=None):
        """`legacy_maps` = {slug: legacy_id_map}. Stored lines are translated on load too,
        so a map added AFTER a row was indexed still applies to that row."""
        legacy_maps = legacy_maps or {}
        self.lines = []                                   # (slug, ids, role)
        for line in (text or "").splitlines():
            parts = line.rstrip("\n").split(SEP)
            if len(parts) < 3 or not line.strip():
                continue
            role = parts[2].split("||", 1)[-1]
            ids = {t for t in parts[1].split() if t}
            ids |= {norm_id(t) for t in translate(ids, legacy_maps.get(parts[0]))}
            self.lines.append((parts[0], frozenset(ids), role))
        owners = {}
        for slug, ids, role in self.lines:
            for t in ids:
                owners.setdefault((slug, t), []).append(role)
        # Shared by stored postings with genuinely different titles -> structure, not an
        # id. (Two stored copies of one posting under slightly different titles do NOT
        # make its id structural.)
        self._structural = {k for k, roles in owners.items()
                            if any(not same_title(a, b) for a in roles for b in roles)}

    def __len__(self):
        return len(self.lines)

    def _ids(self, slug, ids):
        return {t for t in ids if (slug, t) not in self._structural}

    def judge(self, slug, url, role, *, extra_ids=(), legacy_id_map=None, structural=()):
        """Is this candidate a posting already stored?

        `structural` = structural_tokens() over today's candidate urls for this board.
        Ids are compared against EVERY stored line, not only this board's, because a
        posting read via a second board is stored under the employer's own board; the
        title check makes that safe.
        """
        raw = set(tokens(url))
        for e in extra_ids:
            raw |= tokens(str(e))
        mine = {norm_id(t) for t in translate(raw, legacy_id_map)} - set(structural)
        # A title slug that carries the id ("senior-data-scientist-in-x-jid-70002") is the
        # published title, so matching it IS a title match -- the candidate's own title may
        # only be a machine reading of that slug.
        last = str(url).split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        title_slug = norm_id(last) if re.search(r"[a-z]{3}", last.lower()) and re.search(r"\d", last) else None
        retitled = None
        for s, ids, stored_role in self.lines:
            shared = mine & self._ids(s, ids)
            if shared:
                if same_title(role, stored_role) or (title_slug and title_slug in shared):
                    return Verdict(Verdict.DUPLICATE, f"{s}\t{stored_role}")
                if s == slug and retitled is None:
                    retitled = f"{s}\t{stored_role}"
        if retitled:
            return Verdict(Verdict.RETITLED, retitled)
        target = title_words(role)
        for s, ids, stored_role in self.lines:
            if s == slug and title_words(stored_role) == target:
                return Verdict(Verdict.SAME_TITLE, f"{s}\t{stored_role}")
        return Verdict(Verdict.NEW)
