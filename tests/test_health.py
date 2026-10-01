#!/usr/bin/env python3
"""health.py: the records-read field, across both status-file schemas."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from health import records_read

CHECKS = 0


def check(got, want, label):
    global CHECKS
    CHECKS += 1
    assert got == want, f"{label}: got {got!r}, want {want!r}"


# The scripted adapters' schema.
check(records_read({"records_read": 714}), 714, "scripted records_read")
check(records_read({"records_read": 0}), 0, "scripted zero is a real zero")

# The agent path's schema. Reading only records_read scored these 0 and raised a false
# under-reading alert on every agent-path board (2026-10-01).
check(records_read({"records": 329}), 329, "agent records")
check(records_read({"records": 0}), 0, "agent zero is a real zero")

# records_read wins when both are present.
check(records_read({"records_read": 58, "records": 30}), 58, "records_read takes priority")

# Last resort: a board that listed its ids has read them.
check(records_read({"seen_ids": ["a", "b", "c"]}), 3, "falls back to seen_ids")
check(records_read({}), 0, "nothing at all is zero")
check(records_read({"records": None, "seen_ids": ["a"]}), 1, "null records falls through")
check(records_read({"records": "329"}), 0, "a non-int is not a count")

print(f"\n{CHECKS}/{CHECKS} checks passed")
