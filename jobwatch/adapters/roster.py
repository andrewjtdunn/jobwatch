"""One Targets row that is really N boards on platforms already supported here.

A roster -- an alliance, a coalition, a staffing vehicle -- publishes no feed of its own
worth reading. The useful thing is its member list, and every member sits on a platform
with an adapter in this package. So fan out over the members and union the results,
rather than sending the whole row down the model-agent path where a different set of
firms can quietly get read each run.

Three things a naive fan-out gets wrong, each of which loses postings silently:

  * **A member with no open roles is normal, not a failure.** Members run with no record
    floor of their own; the floor belongs to the roster as a whole, via `min_records`.
  * **Member id spaces collide** -- two firms both numbering from 1 -- so ids are
    namespaced `<adapter>:<member>:<id>`. Without that, dedupe drops one firm's postings
    as though they were the other's.
  * **One dead member must not take the roster down**, and equally must not pass
    unnoticed. A partial read is reported on every record as `_partial`; only an
    all-members failure raises.

Each record carries its own `company`, because the employer -- not the roster -- is what
belongs on the posting.

Config (private, in the params file, since it names firms):

    "some-roster": {"adapter": "roster", "min_records": 40, "members": [
        {"adapter": "greenhouse", "member": "<board-slug>", "company": "<Firm>",
         "endpoint": "https://boards-api.greenhouse.io/v1/boards/<board-slug>/jobs"}
    ]}

`member` is the namespace and the label used in errors; `company` is what lands on the
posting. Member slugs can be case-sensitive on some platforms -- copy them exactly.
"""
from ..common import BoardError, assert_records


def fetch(cfg):
    from . import get                    # late: the package __init__ imports this module

    members = cfg.get("members") or []
    if not members:
        raise BoardError(f"{cfg['slug']}: roster has no members configured")

    records, errors = [], []
    for spec in members:
        name = spec.get("member") or spec.get("company") or spec.get("adapter") or "?"
        try:
            child = dict(spec)
            child["slug"] = f"{cfg['slug']}:{name}"
            child["min_records"] = 0      # an empty member is normal
            for rec in get(spec["adapter"]).fetch(child):
                rec["id"] = f"{spec['adapter']}:{name}:{rec.get('id', '')}"
                rec.setdefault("company", spec.get("company") or name)
                records.append(rec)
        except Exception as exc:          # noqa: BLE001 - one member must not end the walk
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    if errors and len(errors) == len(members):
        raise BoardError(f"{cfg['slug']}: every member failed - {'; '.join(errors)}")
    assert_records(cfg["slug"], records, minimum=cfg.get("min_records", 1))
    if errors:
        note = f"{len(errors)}/{len(members)} members failed: " + "; ".join(errors)
        for rec in records:
            rec["_partial"] = note
    return records
