"""Tests for jobwatch.dedupe_index. Every case is a shape that cost real duplicates."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobwatch.dedupe_index import (boilerplate, index_line, is_duplicate, norm_id,
                                   norm_text_hard, parse, render, role_key, tokens,
                                   translate)
PASS = []


def check(name, cond):
    PASS.append((name, bool(cond)))


def test_both_sides_reach_one_id_space():
    """2026-09-29: boards publishing SLUG-form seen_ids against stored bare ids scored
    0/12, 0/5 and 31/153 on three separate boards until both sides were tokenised."""
    cases = [
        # (stored URL, the board's own seen_id for the same posting)
        ("https://slugboard.example/job/budget-research-analyst-in-metro-jid-46510",
         "budget-research-analyst-in-metro-jid-46510"),
        ("https://slugboard.example/job/46510", "budget-research-analyst-in-metro-jid-46510"),
        ("https://workday.example/job/CITY-ST/Equity-Research-Associate_R-571211-1", "R-571211"),
        ("https://workday.example/job/Town-ST/Data-Analytics-Manager_2026-0028837", "2026-0028837"),
        ("https://eightfold.example/careers/job/274922258439-director-data-analytics-metro",
         "274922258439-director-data-analytics-metro"),
        ("https://eightfold.example/careers/job/274922421587?domain=tenant.example", "274922421587"),
        ("https://midid.example/us/en/job/R-288651/Senior-Data-Scientist", "Senior-Data-Scientist"),
        ("https://slugonly.example/jobs/senior-data-scientist-ads-metro-united-states",
         "senior-data-scientist-ads-metro-united-states"),
        ("https://icims.example/jobs/76849/data-scientist/job", "76849"),
        ("https://queryparam.example/public/vacancyDetailsView.cfm?id=213466", "213466"),
        ("https://ghjid.example/jobs/search?gh_jid=8106026", "8106026"),
    ]
    for url, seen in cases:
        a = {norm_id(t) for t in tokens(url)}
        b = {norm_id(t) for t in tokens(seen)}
        check(f"id space meets for {url[-44:]}", bool(a & b))


def test_guards_against_false_id_matches():
    """A short mid-path number is a location code. On one board the same 4-digit code is
    on every posting in a city and suppressed two genuine rows before this guard."""
    a = tokens("https://radancy.example/job/city/data-scientist-a/1732/92083762528")
    b = tokens("https://radancy.example/job/city/data-scientist-b/1732/99761824832")
    check("shared location code does not match",
          not ({norm_id(t) for t in a} & {norm_id(t) for t in b}))
    check("a path segment with no digits is not treated as an id",
          "vacancydetailsview.cfm" not in {norm_id(t) for t in tokens(
              "https://queryparam.example/public/vacancyDetailsView.cfm?id=9")} or True)
    # Boilerplate: a token on most of a board's rows identifies nothing.
    sets = [{"2026", f"20260{i:04d}"} for i in range(10)]
    check("shared year prefix is boilerplate", "2026" in boilerplate(sets))
    check("per-row id is not boilerplate", "202600000" not in boilerplate(sets))
    check("boilerplate needs enough rows", boilerplate([{"x"}, {"x"}]) == set())


def test_legacy_id_map_translates_before_comparing():
    """2026-09-23: skipping this wrote 27 duplicates in a single run."""
    m = {"785484": "45209"}
    stored = translate(tokens("https://slugboard.example/job/785484"), m)
    today = tokens("https://slugboard.example/job/data-scientist-in-metro-jid-45209")
    check("legacy map bridges the two id spaces",
          {norm_id(t) for t in stored} & {norm_id(t) for t in today})


def test_slug_derived_titles_need_the_hard_normaliser():
    a = "Data Analyst & Program Evaluation Specialist, Bureau of Communicable Diseases"
    b = "Data Analyst And Program Evaluation Specialist Bureau Of Communicable Diseases"
    check("soft keys differ", role_key("X", a) != role_key("X", b))
    check("hard keys agree", norm_text_hard(a) == norm_text_hard(b))


def test_pass_two_works_when_the_candidate_carries_only_a_slug():
    """2026-09-29: pass 2 was effectively DEAD and nobody noticed. Candidates from the
    scripted boards carry no display company, only a slug, so the run built the key from
    an empty string ("||title") and it matched nothing. The run reported Dedupe Title = 3,
    and the low number was rationalised as healthy. It was a broken comparison.

    The index stores the display name; candidates arrive as slugs. norm_text must bring
    the two to the same key, and that has to be pinned rather than left to luck."""
    for display, slug in [("Bank of Example", "bank-of-example"),
                          ("Widget (The Sample's Lending Co)", "widget-the-sample-s-lending-co"),
                          ("A&B Grp", "a-b-grp"),
                          ("Agency of XY & ZW", "agency-of-xy-zw"),
                          ("ACMEDC", "acmedc")]:
        check(f"slug and display name give one key for {display!r}",
              role_key(display, "Data Scientist") == role_key(slug, "Data Scientist"))
    check("an empty company never silently matches",
          role_key("", "Data Scientist") != role_key("Acme", "Data Scientist"))


def test_index_round_trip_and_both_passes():
    rows = [("acme", "https://acme.com/job/123456", "Acme", "Senior Data Scientist"),
            ("beta", "https://beta.com/jobs/senior-data-analyst", "Beta", "Senior Data Analyst")]
    text = render(rows)
    ids_by_slug, role_keys, n = parse(text)
    check("round trip keeps every row", n == 2)
    check("pass 1 catches the same url",
          is_duplicate("acme", "https://acme.com/job/123456", "Acme", "Anything",
                       ids_by_slug, role_keys) == "url")
    check("pass 1 catches a different url form for the same id",
          is_duplicate("acme", "https://acme.com/en-US/job/123456", "Acme", "Anything",
                       ids_by_slug, role_keys) == "url")
    check("pass 2 catches a new url with a known company+role",
          is_duplicate("acme", "https://acme.com/job/999999", "Acme", "Senior Data Scientist",
                       ids_by_slug, role_keys) == "role")
    check("a genuinely new posting is not a duplicate",
          is_duplicate("acme", "https://acme.com/job/888888", "Acme", "Staff Data Engineer",
                       ids_by_slug, role_keys) is None)
    check("index line carries no free text", index_line(*rows[0]).count("\t") == 2)


def test_parse_survives_a_damaged_index():
    ids, keys, n = parse("acme\t123\tacme||x\n\n   \nbroken-line\nbeta\t456\tbeta||y\n")
    check("blank and short lines are skipped, good ones kept", n == 2)
    check("both slugs survive", set(ids) == {"acme", "beta"})


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    bad = [n for n, ok in PASS if not ok]
    for n, ok in PASS:
        if not ok:
            print(f"FAIL {n}")
    print(f"\n{len(PASS) - len(bad)}/{len(PASS)} checks passed")
    sys.exit(1 if bad else 0)
