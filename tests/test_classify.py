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



def test_go_to_market_roles_are_not_data_roles():
    """FUNCTION_RX matches a bare "ai", so an AI PRODUCT being sold or deployed was
    satisfying the function rule on behalf of a commercial role.

    Measured 2026-10-01 on live boards: "Account Executive, AI Startups - Grower",
    "Strategic Accounts Sales Leader, AI GTM", two "AI Engagement Manager" postings (both
    graded STRONG) and "AI Deployments PM" all reached the candidate stage. The AI is the
    product being sold or deployed, not the work.
    """
    for title in ("Account Executive, AI Startups - Grower",
                  "Strategic Accounts Sales Leader, AI GTM",
                  "AI Engagement Manager | Housing",
                  "AI Engagement Manager, Institutional Owners | Housing",
                  "Customer Success Manager, AI",
                  "Client Success Lead, Machine Learning",
                  "Partnerships Manager, Data Products",
                  "Revenue Operations Manager, AI",
                  "Pre-Sales Engineer, Machine Learning"):
        check(f"gtm drops {title}", not classify(title, NYC, tech_firm=True).keep)

    # "PM" is as common as the spelled-out words and must read as product manager.
    check("an AI PM is still a product manager",
          not classify("AI Deployments PM - Future Platforms | Housing",
                       NYC, tech_firm=True).keep)
    check("a TPM is still a programme manager",
          not classify("TPM, Data Platform", NYC, tech_firm=True).keep)

    # AI ADVISORY / CONSULTING IS IN THE CRITERIA and must survive this rule.
    for title in ("AI Solutions Consultant", "AI Advisory Lead", "AI Strategy Advisor"):
        check(f"advisory survives: {title}", classify(title, NYC).keep)

    # A genuine data function in a commercial DOMAIN still reaches the other axes: the
    # sales pattern is deliberately narrowed to a commercial ROLE NOUN.
    check("sales analytics is still analytics",
          classify("Sales Analytics Manager", NYC).keep)
    check("data science manager in a finance org survives",
          classify("Data Science Manager, Finance and Strategy", NYC).keep)
    check("analytics manager survives",
          classify("Analytics Manager - Research & Client Strategy", NYC).keep)
    check("account-level data engineering survives",
          classify("Data Engineer, Account Platform", NYC).keep)



def test_application_development_and_product_delivery_are_not_data_roles():
    """A stack-described application-development manager and a product-delivery manager
    are not data roles, even with data/AI words in the title."""
    check("drops application development manager",
          not classify("Senior Manager, Application Development (Java, Microservices)", NYC).keep)
    check("drops product delivery manager",
          not classify("Product Delivery Manager - Data Governance", NYC).keep)
    check("keeps data science manager", classify("Data Science Manager", NYC).keep)

def test_legal_and_capture_roles_are_not_data_roles():
    check("drops AI counsel", not classify("Senior Counsel, AI and Data", NYC).keep)
    check("drops paralegal", not classify("Paralegal - Data Privacy", NYC).keep)
    check("drops capture manager", not classify("AI Capture Manager", NYC).keep)
    check("drops sales capture", not classify("Data & AI Sales Capture Lead", NYC).keep)
    check("drops video production", not classify("AI Video Production Specialist", NYC).keep)
    check("still keeps data scientist", classify("Senior Data Scientist", NYC).keep)

def test_spelled_out_ux_research_is_not_a_data_role():
    check("drops experience researcher", not classify("Senior Experience Researcher", NYC).keep)
    check("drops user experience researcher", not classify("User Experience Researcher", NYC).keep)
    check("still keeps research scientist", classify("Research Scientist, Personalization", NYC).keep)

def test_software_developer_and_product_associate_are_excluded():
    check("drops lead software developer", not classify("Lead Software Developer - Java, Python, AWS & AI Platform", NYC).keep)
    check("drops senior product associate", not classify("Senior Product Associate - Data Governance", NYC).keep)
    check("drops senior associate, product", not classify("Wealth Management - Senior Associate, Product - AI", NYC).keep)
    check("still keeps data product scientist", classify("Applied AI & Data Product Scientist", NYC).keep)
    check("still keeps analytics senior associate", classify("Analytics Solutions, Senior Associate", NYC).keep)

def test_low_code_platform_developers_are_not_data_roles():
    check("drops appian developer", not classify("Appian Developer, Software and Data Management", NYC).keep)
    check("drops appian dev reporting", not classify("Appian Dev, Reporting and Analytics", NYC).keep)
    check("drops low-code developer", not classify("Low-Code Developer - Data Platform", NYC).keep)
    check("still keeps reporting analyst", classify("Reporting and Data Analyst", NYC).keep)

def test_director_of_product_is_a_product_role():
    check("drops director of product, data area", not classify("Director of Product, Member Data Platform", NYC).keep)
    check("drops manager of product", not classify("Manager of Product - Data Platform", NYC).keep)
    check("still keeps manager of product analytics", classify("Manager of Product Analytics", NYC).keep)

def test_ed_abbreviation_is_executive_director():
    check("drops ED, analytics leader", not classify("ED, Business Analytics Transformation Leader", NYC).keep)
    check("still keeps ...ed words", classify("Senior Data Scientist, Regulated Credit Models", NYC).keep)
    check("still keeps Ed-tech analyst", classify("EdTech Data Analyst", NYC).keep)

def test_customer_activation_is_not_a_data_role():
    check("drops customer activation manager", not classify("Customer Activation Manager | AI Platform", NYC).keep)
    check("drops customer onboarding lead", not classify("Customer Onboarding Lead, Data Platform", NYC).keep)
    check("still keeps customer analytics", classify("Senior Data Scientist, Customer Analytics", NYC).keep)

def test_software_sales_and_it_audit_are_not_data_roles():
    check("drops software sales associate director", not classify("Software Sales Associate Director - Marketing Analytics Software", NYC).keep)
    check("drops IT audit manager", not classify("Senior Manager, IT Audit - Data Governance", NYC).keep)
    check("keeps an internal-audit data scientist", classify("Internal Audit, Asset Wealth Management - Senior Associate - Data Scientist", NYC).keep)
    check("still keeps sales analytics manager", classify("Sales Analytics Manager", NYC).keep)
    check("still keeps data governance analyst", classify("Senior Analyst Data Governance & Management - Finance", NYC).keep)
    check("still keeps audit-free data scientist", classify("Data Scientist, Credit Analytics", NYC).keep)

def test_content_developers_are_not_data_roles():
    check("drops technical content developer", not classify("Technical Content Developer Associate Manager, AI POD", NYC).keep)
    check("drops technical writer", not classify("Technical Writer, Data Platform", NYC).keep)
    check("still keeps data developer", classify("Senior Data Analyst, Content Analytics", NYC).keep)

def test_remote_program_boilerplate_is_not_remote_evidence():
    office = ["San Francisco Office"]
    boiler = "Whether you're coming in regularly or are part of our fully remote program, you'll stay engaged."
    check("company remote-program boilerplate does not make a role remote",
          not classify("Senior Data Scientist", office, text=boiler).keep)
    check("a flat statement still does", classify("Senior Data Scientist", office,
          text="Location: This is a fully remote position.").keep)
    check("work from anywhere in the US still does", classify("Senior Data Scientist", office,
          text="(Work from anywhere: This role can be performed from any location in the United States)").keep)
    check("drops content marketing manager", not classify("Content Marketing Manager, SEO & AI Search", ["New York, NY"]).keep)

if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    bad = [n for n, ok in PASS if not ok]
    for n, ok in PASS:
        if not ok:
            print(f"FAIL {n}")
    print(f"\n{len(PASS) - len(bad)}/{len(PASS)} checks passed")
    sys.exit(1 if bad else 0)
