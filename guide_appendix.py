#!/usr/bin/env python3
"""Regenerate the Guide's Appendix B (sectors) and C (instruments) from z1_master.db, using the validated
2-digit sector / 4-digit instrument / 3-digit detail split of the nine digits after the prefix.

    python guide_appendix.py [--top 20] [--db z1_master.db]
"""
import argparse
import collections
import re
import sqlite3

NINE = re.compile(r"^[A-Z]{2}(\d{2})(\d{4})(\d{3})\.[AQ]$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="z1_master.db")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    sec_n, ins_n = collections.Counter(), collections.Counter()
    sec_name, ins_desc = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for sid, desc in c.execute("SELECT series_id, description FROM series WHERE description IS NOT NULL"):
        m = NINE.match(sid)
        if not m or ";" not in desc:
            continue
        sec, ins, _ = m.groups()
        who, what = (p.strip() for p in desc.split(";", 1))
        sec_n[sec] += 1; ins_n[ins] += 1
        sec_name[sec][who] += 1; ins_desc[ins][what] += 1
    print(f"## Appendix B, Sector Code Directory\n\n{len(sec_n)} unique 2-digit sector codes. The {a.top} most frequent:\n")
    print("| Code | Series | Sector |\n|---|---|---|")
    for k, n in sec_n.most_common(a.top):
        print(f"| {k} | {n:,} | {sec_name[k].most_common(1)[0][0]} |")
    print(f"\n## Appendix C, Instrument Code Directory\n\n{len(ins_n)} unique 4-digit instrument codes. The {a.top} most frequent:\n")
    print("| Code | Series | Most common description |\n|---|---|---|")
    for k, n in ins_n.most_common(a.top):
        print(f"| {k} | {n:,} | {ins_desc[k].most_common(1)[0][0]} |")
    print(f"\nTotal series parsed: {sum(sec_n.values()):,}")


if __name__ == "__main__":
    main()
