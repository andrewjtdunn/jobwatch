"""Tests for privacy_audit.py.

A clean run proves nothing on its own: an audit that never fires and an audit that
cannot fire look identical from the outside. So these tests PLANT leaks of each shape
and assert they are caught, then assert the known false-positive shapes are not.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS = []


def check(name, cond):
    PASS.append((name, bool(cond)))


TARGETS = [
    {"Company": "Zorptek Analytics", "Active": "__YES__",
     "Fetch Endpoint": "https://boards-api.greenhouse.io/v1/boards/zorptek/jobs"},
    {"Company": "Quimbly", "Active": "__YES__",
     "Fetch Endpoint": "https://apply.quimbly.com/careers/search"},
    {"Company": "Current", "Active": "__YES__",
     "Fetch Endpoint": "https://api.ashbyhq.com/posting-api/job-board/currentco"},
]


def run_audit(files, targets=TARGETS):
    """Write a throwaway repo, run the audit over it, return (exit code, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        for name, body in files.items():
            path = os.path.join(repo, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(body)
        tpath = os.path.join(tmp, "targets.json")
        with open(tpath, "w") as fh:
            json.dump(targets, fh)
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "privacy_audit.py"),
             "--targets", tpath, "--repo", repo],
            capture_output=True, text=True)
        return proc.returncode, proc.stdout


def test_it_catches_every_leak_shape():
    cases = {
        "full name in a comment": "# tuned for Zorptek Analytics\n",
        "name in snake_case": "ZORPTEK_ANALYTICS_LIMIT = 5\n",
        "slug": 'CFG = {"slug": "zorptek-analytics"}\n',
        "distinctive single token": "# the Zorptek board paginates oddly\n",
        "employer host": 'URL = "https://apply.quimbly.com/careers/search"\n',
        "employer host label": "# quimbly needs a POST, not a GET\n",
        "platform tenant id": 'EP = "https://boards-api.greenhouse.io/v1/boards/zorptek/jobs"\n',
        "leak in a test fixture": '{"absolute_url": "https://apply.quimbly.com/jobs/1"}\n',
    }
    for label, body in cases.items():
        name = "fixtures/f.json" if "fixture" in label else "mod.py"
        code, out = run_audit({name: body})
        check(f"catches {label}", code >= 1 and "LEAK" in out)


def test_it_does_not_cry_wolf():
    """Every one of these fired on the first real run and had to be fixed. A noisy audit
    is an ignored audit, so these are regression tests on the NOISE."""
    quiet = {
        "shared platform host": '("boards-api.greenhouse.io", "greenhouse"),\n',
        "another platform host": 'BASE = "https://jobs.jobvite.com"\n',
        "generic subdomain label": 'W = "https://apply.workable.com/x"\n',
        "the word board": "# per board, write a status file\n",
        "the word data": "# data roles only\n",
        "the word union": "# union the results by req id\n",
        "the word current": "# current listing pages emit a different shape\n",
        "the word block": "block = LOC_BLOCK_RX.search(html)\n",
        "placeholder host": 'U = "https://example.com/job/1"\n',
    }
    for label, body in quiet.items():
        code, out = run_audit({"mod.py": body})
        check(f"quiet on {label}", code == 0)


def test_private_files_are_not_scanned_as_repo_content():
    """boards.json and the targets file are private inputs; a copy sitting in the tree
    is not a code leak and must not drown the real findings."""
    code, _ = run_audit({"boards.json": json.dumps([{"company": "Zorptek Analytics"}])})
    check("boards.json is skipped", code == 0)


def test_unauditable_names_are_declared_not_hidden():
    """A one-word employer named after an ordinary word cannot be grepped for. The audit
    must SAY so rather than pass in silence."""
    code, out = run_audit({"mod.py": "# nothing here\n"})
    check("exits clean", code == 0)
    check("names what it could not check", "CANNOT be checked" in out and "Current" in out)


def test_exit_code_is_the_finding_count():
    code, out = run_audit({"a.py": "# Zorptek Analytics\n", "b.py": "# Zorptek Analytics\n"})
    check("exit code counts findings", code == out.count("LEAK") and code >= 2)


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    bad = [n for n, ok in PASS if not ok]
    for n, ok in PASS:
        if not ok:
            print(f"FAIL {n}")
    print(f"\n{len(PASS) - len(bad)}/{len(PASS)} checks passed")
    sys.exit(1 if bad else 0)
