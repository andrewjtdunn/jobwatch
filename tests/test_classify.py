"""Tests for jobwatch.classify.

Every string below is one that a real run got WRONG, or one a real run must keep
getting right. The dates name the run that found it. A rule with no test here is a rule
that will be silently rewritten the next time someone reaches for the regex.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobwatch.classify import classify

NYC = ["New York, NY"]
REMOTE_US = ["Remote - US"]
PASS = []


def check(name, cond):
    PASS.append((name, bool(cond)))


# --------------------------------------------------------------- function, positive
def test_function_rule_matches_real_data_titles():
    """2026-09-24: "\\b(data scien|analy)\\b" matched NOTHING -- a trailing \\b after an
    alternation of PREFIXES never matches. It dropped real Data Science Manager roles."""
    for t in ["Data Scientist", "Data Science Manager", "Senior Data Science Manager",
              "Machine Learning Engineer", "Applied Scientist II", "Data Analyst",
              "Analytics Engineer", "Senior Quantitative Analyst", "Research Scientist",
              "Senior Decision Scientist", "AI Data Scientist Lead", "Biostatistician",
              "Senior Analyst, Data Analytics", "Applied Researcher 5",
              "Quant Analytics Senior Associate", "Bioinformatics Scientist"]:
        check(f"function keeps {t!r}", classify(t, NYC).keep)


# --------------------------------------------------------------- function, negative
def test_borderline_titles_already_accepted_in_postings_stay_accepted():
    """Guard against tightening past the existing data. "Budget Research Analyst" is a
    live row in Postings on a civil-service board, so the rule must not start dropping
    it: a research-analyst title is in scope even when the domain is budgeting."""
    check("budget research analyst kept",
          classify("Budget Research Analyst", ["Manhattan"], gov=True).keep)


def test_bare_analyst_in_a_non_data_domain_is_dropped():
    """2026-09-29: a bare \\banalyst\\b produced 97 false keeps in one run."""
    for t in ["Financial Analyst", "Senior Financial Analyst", "Analyst-Marketing",
              "Senior Analyst - Control Management", "Analyst-Control Mgmt",
              "Risk Analysis Specialist III", "Senior Analyst - Risk Management",
              "Equity Research Associate", "Dental Network Relations Senior Analyst",
              "Business Analyst",
              "Finance & Business Management - Public Cloud & AI Infrastructure",
              "Customer Service Researcher",
              "Director Records Management Bureau of Vital Statistics",
              "X-Day Offensive Research (XOR) Vulnerability Researcher",
              "Staff Quantitative Researcher (Market Research)"]:
        check(f"non-data drops {t!r}", not classify(t, NYC).keep)

    for t in ["Recruiter", "Registered Nurse", "Warehouse Associate", "Temporary Attorney",
              "Paralegal Assistant", "Machinist (Mechanic)", "Invoice Processing Assistant"]:
        check(f"non-function drops {t!r}", not classify(t, NYC).keep)


# ------------------------------------------------------------------------------ SWE
def test_ai_in_a_software_engineering_title_is_still_software_engineering():
    """2026-09-29: letting "AI" override the SWE exclusion admitted ~40 SWE postings
    from a single large board, 20 of them labelled Strong."""
    for t in ["Lead Software Engineer - Agentic AI, Java/Python",
              "Senior Lead Software Engineer - Python/AWS/AI/LLM",
              "Senior Software Engineer - AI Tooling",
              "Senior Full Stack Engineer, Agentic AI Platform",
              "Senior Lead Site Reliability Engineer - Manager-AI/ML",
              "Sr Software Development Engineer - AI Engineering",
              "Software Engineer III - Agentic AI, Java/Python",
              "Full-stack Engineer 5 (AI Platform & Knowledge Library)",
              "Lead ML Ops/DevOps Engineer - AI Engineering",
              "AI Web Framework Lead Software Engineer",
              # 2026-09-30 replay: a data/ML word AFTER "software engineer" is the domain
              # the engineer works in, not a different role.
              "Lead Software Engineer - Data Engineer",
              "Lead Software Engineer - Data & AI Platform Engineering",
              "Software Engineer, Machine Learning Platform"]:
        check(f"SWE drops {t!r}", not classify(t, NYC).keep)

    # ...but an explicit ML/DS role-noun survives the SWE exclusion.
    for t in ["Machine Learning Engineer 4", "Senior Analytics Engineer",
              "Data Engineer 4 (Python, AWS, Spark)", "AI/ML Engineer"]:
        check(f"ML role survives SWE {t!r}", classify(t, NYC).keep)


def test_product_and_design_are_not_data_functions():
    for t in ["Staff Product Manager Buyer ML", "UX Researcher / Designer",
              "Director Project Management AI", "Lead Technical Program Manager - Payment Data and AI",
              "Salesforce Sr. Product Owner (AI, CX, & Revenue)",
              "Senior AI-Native Product Engineer, Mobile", "Director, Marketing AI & Automation"]:
        check(f"product drops {t!r}", not classify(t, NYC).keep)


# ---------------------------------------------------------------------------- level
def test_level_ceiling_and_floor():
    for t in ["VP, Data Science", "Vice President Analytics", "Chief Data Officer",
              "Head of Analytics", "Managing Director, Data Science",
              "Executive Director - Data Science", "SVP Analytics"]:
        check(f"VP+ drops {t!r}", not classify(t, NYC).keep)

    for t in ["Data Science Intern", "Summer Analyst Program", "AI Politics Fellow",
              "Campus Undergraduate Summer Internship Program - 2027 Data Analytics",
              "Data Analytics Trainee", "Coach/Ops Mgr Trainee"]:
        check(f"below level I drops {t!r}", not classify(t, NYC).keep)

    for t in ["Resume Bank", "Future Opportunities", "General Application", "Talent Community"]:
        check(f"evergreen drops {t!r}", not classify(t, NYC).keep)

    check("clearance drops", not classify("Data Scientist - TS/SCI required", NYC).keep)


def test_lead_principal_staff_only_too_senior_at_a_tech_firm():
    t = "Lead Data Scientist"
    check("LPS dropped at a tech firm", not classify(t, NYC, tech_firm=True).keep)
    check("LPS kept elsewhere", classify(t, NYC, tech_firm=False).keep)


def test_director_is_manager_tier_in_civil_service_only():
    """A corporate Director is above the manager ceiling -> Stretch, never a silent drop.
    On a government board Director IS the manager tier."""
    corp = classify("Director of Data Science", NYC, gov=False)
    check("corporate Director is Stretch", corp.keep and corp.match == "Stretch")
    gov = classify("Deputy Director, Data Systems and Analytics", ["Manhattan"], gov=True)
    check("gov Director is not downgraded", gov.keep and gov.match != "Stretch")


# ------------------------------------------------------------------------- location
def test_location_is_a_hard_axis_not_a_tiebreaker():
    """2026-09-23: 16 rows in Kuala Lumpur, Prague, Palo Alto and San Francisco were
    written as matches, six of them Strong."""
    for locs in (["MYS - Kuala Lumpur"], ["CZE - Prague"], ["Palo Alto, CA"],
                 ["San Francisco, CA"], ["Remote"] + ["London"], ["Chicago, Illinois"]):
        check(f"location drops {locs}", not classify("Senior Data Scientist", locs).keep)

    check("US-scoped remote qualifies", classify("Senior Data Scientist", REMOTE_US).match == "Strong")
    check("bare remote, no office, qualifies", classify("Senior Data Scientist", ["Remote"]).keep)
    check("NYC anywhere in the list qualifies",
          classify("Senior Data Scientist", ["Chicago", "Reston", "White Plains, New York"]).keep)
    amb = classify("Senior Data Insights Specialist", ["AZ - Work from home"])
    check("state-anchored WFH is Possible at best", amb.keep and amb.match in ("Possible", "Stretch"))


def test_remote_stated_in_the_description_not_the_location_list():
    """2026-09-30: a board with no NYC office listed "Virtual Office" alongside 22 named
    offices, so the location list said "not remote", while the description said the role
    may be filled remotely and carried #LI-Remote. Two genuine data roles had been
    excluded since 2026-09-23 because only the list was ever read."""
    offices = ["Multiple Locations", "Austin", "Boston", "Chicago", "Virtual Office"]
    check("list alone still drops it", not classify("Enterprise Data Analyst", offices).keep)

    tied = ("This position may be filled remotely or in a hybrid capacity in any of our "
            "Central and Eastern Time locations. #LI-Remote")
    v = classify("Enterprise Data Analyst", offices, text=tied)
    check("description rescues it", v.keep)
    check("but region-tied remote is not Strong", v.match in ("Possible", "Stretch"))

    flat = "This position will work fully remote. #LI-Remote"
    check("flatly remote qualifies", classify("Senior Data Scientist", offices, text=flat).match == "Strong")

    for bad in ["This is not a remote position.", "On-site only.",
                "Remote work is not available for this role.",
                "Candidates must report on-site five days a week."]:
        check(f"negation is not remote evidence: {bad!r}",
              not classify("Senior Data Scientist", offices, text=bad).keep)

    check("an NYC office in the list outranks any wording",
          classify("Senior Data Scientist", ["New York, NY"] + offices,
                   text="On-site only.").match == "Strong")
    check("description cannot rescue a wrong-function title",
          not classify("Software Developer", offices, text=flat).keep)


# --------------------------------------------------------------------- match levels
def test_match_levels():
    check("senior+nyc is Strong", classify("Senior Data Scientist", NYC).match == "Strong")
    check("manager+nyc is Strong", classify("Manager, Data Analysis", NYC).match == "Strong")
    check("unstated level is Possible", classify("Data Scientist", NYC).match == "Possible")
    check("numbered IC ladder is Possible",
          classify("Machine Learning Engineer 4", NYC).match == "Possible")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    bad = [n for n, ok in PASS if not ok]
    for n, ok in PASS:
        if not ok:
            print(f"FAIL {n}")
    print(f"\n{len(PASS) - len(bad)}/{len(PASS)} checks passed")
    sys.exit(1 if bad else 0)
