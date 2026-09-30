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
    """Both dedupe passes, in order. Returns "url", "role", or None.

    PASS 2 IS NOT A SAFETY NET FOR PASS 1 -- it missed all 27 duplicates on 2026-09-23
    because one side's titles were slug-derived. Both passes run; neither is optional.
    """
    mine = {norm_id(t) for t in translate(tokens(url), legacy_id_map)}
    if mine & ids_by_slug.get(slug, set()):
        return "url"
    if role_key(company, role) in role_keys:
        return "role"
    return None
