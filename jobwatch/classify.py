"""Match-level classification: is this posting a real match, and how strong?

`title_hit()` in common.py is a deliberately LOOSE recall gate, and its count is a
health metric compared against a stored baseline -- do not tighten it. This module is
the PRECISION stage that runs over the titles it lets through.

Why this lives in the repo rather than being re-derived each run: on 2026-09-29 the
rules were rewritten from scratch by the daily run, which admitted "AI Engineer N",
"Machine Learning Engineer N" and "Quantitative Engineer" titles that earlier runs had
dropped, and wrote 19 rows that had to be tagged FILTER/KEYWORD WIDENED. Same boards,
same postings, a different answer depending on which model ran that morning. Rules that
are not written down are not rules.

Nothing here names a company. Per-board facts arrive as flags from boards.json, which is
built from the private Targets and Board Params. Keep it that way: this file is public.
"""
from __future__ import annotations

import re

from .common import EVERGREEN_RX, posting_verdict

# --------------------------------------------------------------------------- function

# A data function, stated positively. Prefixes, not \b-anchored whole words: a trailing
# \b after an alternation of prefixes matches NOTHING ("\b(data scien|analy)\b" never
# matches "data science"), which silently dropped real Data Science Manager roles on
# 2026-09-24. test_function_rule pins that.
FUNCTION_RX = re.compile(r"""(
    data\s*scien | datascien | data\s*analy
  | machine\s*learning | \bml\b | \bmlops\b | deep\s*learning
  | \bai\b | artificial\s*intelligence | generative\s*ai | \bgenai\b | \bllm\b
  | applied\s*scien | research\s*scien | applied\s*research | decision\s*scien
  | analytics | analytical | \banalytic\b
  | quantitative\s*(analy|scien|research|model|engineer|strateg)
  | \bstatistic\w* | \beconometric\w* | biostatistic | \bbioinformatic\w*
  | informatics | data\s*insight | \bnlp\b | computer\s*vision
  | research\s*analy | \bresearcher\b | operations\s*research
  | business\s*intelligence
  | data\s*(steward|governance|strateg|management|manager|solution|engineer)
)""", re.I | re.X)

# An "analyst" or "scientist" qualified by a NON-data domain is not a data role. A bare
# \banalyst\b matches Financial Analyst, Analyst-Marketing, Risk Analysis Specialist and
# Control Management, and on 2026-09-29 that alone produced 97 false keeps.
NONDATA_RX = re.compile(r"""(
    financial\s*analyst | finance\s*analyst | \bfp&a\b | credit\s*analyst
  | marketing\s*analyst | analyst[\s,\-]*(marketing|finance|financial|control|risk|audit|sales|hr)
  | control\s*(management|mgmt) | risk\s*(analysis|management)\s*(specialist|analyst)
  | compliance\s*analyst | audit\s*analyst | equity\s*research | investment\s*analyst
  | budget\s*analyst | procurement | payroll | \bhris\b | recruit | talent\s*acquisition
  | policy\s*analyst | program\s*analyst | business\s*analyst
  | systems\s*analy | contract\s*analyst | quality\s*analyst
  | vulnerability\s*research | offensive\s*research | security\s*research | penetration
  | finance\s*&?\s*business\s*management | customer\s*service | records\s*management
  | vital\s*statistic | market\s*research | dental | clinical\s*network
  | network\s*relations
)""", re.I | re.X)

# Pure software engineering is excluded by the criteria. "AI" in the title does NOT
# rescue it: "Lead Software Engineer - Agentic AI, Java/Python" is a SWE role, and on
# 2026-09-29 letting AI override this flooded one large board with ~40 SWE postings.
#
# "Software engineer" is an ABSOLUTE exclusion with no escape. The role noun is what the
# job is; a data or ML word after it is the domain the engineer works in, not a change of
# role. "Lead Software Engineer - Data Engineer" is a software engineering job. Letting
# ML_ROLE_RX rescue it admitted exactly that title on the 2026-09-30 replay.
SWE_ABSOLUTE_RX = re.compile(
    r"software\s*(engineer|development\s*engineer|architect)", re.I)

# These SWE signals CAN be overridden by an explicit ML/DS role-noun, because they are
# describing a stack rather than the role ("Machine Learning Engineer, Backend").
SWE_SOFT_RX = re.compile(r"""(
    backend | back\s*-\s*end | front\s*-?\s*end | full\s*-?\s*stack | devops
  | site\s*reliability | platform\s*engineer | security\s*engineer | network\s*engineer
  | \bqa\b | mobile\s*engineer | android | \bios\b | web\s*developer
  | application\s*develop | solutions\s*architect | cloud\s*engineer | microservices?
)""", re.I | re.X)

# ...the ONLY escape, and only from SWE_SOFT_RX.
ML_ROLE_RX = re.compile(r"""(
    machine\s*learning\s*engineer | \bml\s*engineer | ml/?ai\s*engineer | ai/?ml\s*engineer
  | data\s*scientist | applied\s*scientist | research\s*scientist
  | analytics\s*engineer | data\s*engineer\b
)""", re.I | re.X)

PRODUCT_RX = re.compile(r"""(
    product\s*(manager|owner|lead|director|engineer|manage)
  | product\s*delivery\s*(manager|lead|owner|director) | \bux\b | \bui\b | designer
  | program\s*manager | project\s*manag | scrum | \bagile\b | salesforce
  | technical\s*program | business\s*development | \bsales\b\s*(strategy|engineer)
  | marketing\s*(ai|automation)
  # "AI Deployments PM" is a product manager. The abbreviation is as common as the words
  # and was passing the whole rule on the strength of the "AI" in front of it.
  | \bpm\b | \btpm\b
)""", re.I | re.X)

# GO-TO-MARKET AND CUSTOMER-FACING ROLES ARE NOT DATA ROLES, however much AI is in the
# title. FUNCTION_RX matches a bare "ai", so on 2026-10-01 "Account Executive, AI
# Startups", "Strategic Accounts Sales Leader, AI GTM" and two "AI Engagement Manager"
# postings all passed the function rule -- two of them as Strong. The AI is the product
# being sold or deployed, not the work.
#
# "AI advisory / consulting" IS in the criteria, so consultant/advisor/advisory titles are
# deliberately NOT listed here. "sales" is narrowed to a commercial role noun so that a
# genuine "Sales Analytics Manager" still reaches the other axes.
COMMERCIAL_RX = re.compile(r"""(
    account\s*(executive|manager|director|lead)
  | \bsales\b\s*(leader|lead|manager|director|rep|representative|executive|specialist)
  | engagement\s*manager | customer\s*success | client\s*success
  | \bgtm\b | go[\s\-]*to[\s\-]*market | pre[\s\-]*sales
  | partnerships?\s*(manager|lead|director) | field\s*enablement
  | revenue\s*(operations|manager|lead) | \bquota\b
)""", re.I | re.X)

# ------------------------------------------------------------------------------ level

VP_RX = re.compile(
    r"(\bvp\b|vice\s*president|\bsvp\b|\bevp\b|\bchief\b|\bhead\s+of\b|president"
    r"|\bcto\b|\bcio\b|\bcdo\b|executive\s*director|managing\s*director|\bpartner\b)", re.I)
SENIOR_RX = re.compile(
    r"(\bsenior\b|\bsr\.?\b|\bmanager\b|\bmgr\b|\blead\b|\bii\b|\biii\b|\blevel\s*2\b)", re.I)
# Below level I. "Fellow" and "trainee" belong here: term-limited and junior.
JUNIOR_RX = re.compile(
    r"(\bintern\b|\binternship\b|\bco-?op\b|\bapprentice\b|\bcampus\b|\bgraduate\s*program\b"
    r"|\bfellow\b|\btrainee\b|\bstudent\b|\bsummer\b)", re.I)
CLEARANCE_RX = re.compile(
    r"(security\s*clearance|\btop\s*secret\b|\bts/sci\b|polygraph|\bsecret\b\s*clearance)", re.I)
# Too senior at a tech firm, fine elsewhere -- hence the tech_firm flag.
LPS_RX = re.compile(r"(\blead\b|\bprincipal\b|\bstaff\b|\bdistinguished\b)", re.I)
# Above the manager ceiling at a corporate employer; IS the manager tier in civil service.
DIRECTOR_RX = re.compile(r"\bdirector\b", re.I)


class Verdict:
    """keep/drop plus the match level and the reason, so callers need not re-judge."""

    __slots__ = ("keep", "match", "reason")

    def __init__(self, keep, match, reason):
        self.keep, self.match, self.reason = keep, match, reason

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Verdict(keep={self.keep}, match={self.match!r}, reason={self.reason!r})"

    def __iter__(self):
        return iter((self.keep, self.match, self.reason))


def classify(title, locations, *, gov=False, tech_firm=False, text=None):
    """Judge one posting.

    gov=True       -- a government/civil-service employer, where "Director" and "Deputy
                      Director" are the manager tier rather than above it.
    tech_firm=True -- Lead/Principal/Staff are too senior here (the criteria call a
                      Staff IC at a fintech or health-tech a tech firm).

    text           -- the job description, when the adapter already has it. Some boards
                      put every office in the location list and state remote-ness only in
                      the body; without this a remote-first role on a board with no NYC
                      office is dropped. See common.posting_verdict.

    Both flags come from boards.json, never from a name test in this file.
    """
    t = f" {title or ''} "

    if EVERGREEN_RX.search(t):
        return Verdict(False, None, "evergreen pipeline")
    if JUNIOR_RX.search(t):
        return Verdict(False, None, "campus/intern/fellow - below level I")
    if CLEARANCE_RX.search(t):
        return Verdict(False, None, "security clearance required")
    if VP_RX.search(t):
        return Verdict(False, None, "VP+ / executive")
    if NONDATA_RX.search(t):
        return Verdict(False, None, "analyst/scientist in a non-data domain")
    if not FUNCTION_RX.search(t):
        return Verdict(False, None, "not a data function")
    if SWE_ABSOLUTE_RX.search(t):
        return Verdict(False, None, "software engineering role (the domain word after it does not change that)")
    if SWE_SOFT_RX.search(t) and not ML_ROLE_RX.search(t):
        return Verdict(False, None, "pure software engineering (AI in the title does not change that)")
    if PRODUCT_RX.search(t):
        return Verdict(False, None, "product/programme/design, not a data function")
    if COMMERCIAL_RX.search(t):
        return Verdict(False, None, "go-to-market/customer-facing, not a data function")
    if tech_firm and LPS_RX.search(t):
        return Verdict(False, None, "Lead/Principal/Staff at a tech firm")

    # Location is judged LAST but is not a tiebreaker: a wrong-city role is a wrong
    # match, not a borderline one. On 2026-09-23 treating it as borderline wrote 16 rows
    # in Kuala Lumpur, Prague, Palo Alto and San Francisco, six of them labelled Strong.
    verdict = posting_verdict(locations, text)
    if verdict is None:
        return Verdict(False, None, "fails the location rule")

    over_level = DIRECTOR_RX.search(t) and not gov

    if verdict == "ambiguous":
        return Verdict(True, "Stretch" if over_level else "Possible",
                       "state-anchored remote; residence in that state may be required")
    if over_level:
        return Verdict(True, "Stretch",
                       "Director sits between the manager ceiling and VP")
    if SENIOR_RX.search(t):
        return Verdict(True, "Strong", f"function, level and location all clear ({verdict})")
    return Verdict(True, "Possible", f"function and location clear ({verdict}), level unstated")
