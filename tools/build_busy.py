"""Turns the sign-up counts in data/busy_log.csv into "how busy" labels on icetimes.ca.

    python3 tools/build_busy.py

data/busy_log.csv has one row per reading of one session:
  date        YYYY-MM-DD the session runs
  day         Mon..Sun
  start       start time in minutes after midnight (same as SNAPSHOT)
  rink, type  exactly as in SNAPSHOT (type uses the seven site types)
  spots_left  number shown by Surrey ("17 spots left"); blank if not shown
  registered  number shown by Canlan ("3/24 Registered" -> 3); blank if not shown
  capacity    total spots if shown (Canlan "/24" -> 24); blank if not shown
  mins_before minutes between the reading and the session start
  source      surrey | canlan

Only readings taken 0-240 minutes before the start count (that is close to the final turnout).
For each session date the latest such reading is used. Capacity for Surrey sessions, which only show
spots left, is the most spots-left ever seen for that weekly slot (registration opens with every spot free).
A weekly slot (rink + day + start + type) gets a label once it has readings from 3 different dates:
  under 40% full -> quiet, 40-79% -> moderate, 80%+ -> busy.
Readings taken earlier (any time before the start) count too, for one thing: if a slot was already FULL
(0 spots left, or registered >= capacity) before the start on 2+ different dates, it is labelled "fills"
("Often fills up · book early"), which overrides the level above.
source: surrey | richmond | delta | portmoody | canlan | ... (any booking list that shows spots left)
The result replaces the `const BUSY_AUTO = [...];` line in index.html.
"""
import csv, json, os, re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "data", "busy_log.csv")
MIN_DATES = 3


def num(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def main():
    rows = list(csv.DictReader(open(LOG, encoding="utf-8"))) if os.path.exists(LOG) else []
    slot_cap = defaultdict(int)          # most spots-left / capacity ever seen per slot
    best = {}                            # (slot, date) -> latest close-to-start reading
    full_dates = defaultdict(set)        # slot -> dates it was seen full before the start
    for r in rows:
        slot = (r["rink"], r["day"], num(r["start"]), r["type"])
        if None in slot:
            continue
        cap = num(r.get("capacity")) or 0
        left = num(r.get("spots_left"))
        slot_cap[slot] = max(slot_cap[slot], cap, left or 0)
        mb = num(r.get("mins_before"))
        reg0, cap0 = num(r.get("registered")), num(r.get("capacity"))
        if mb is not None and mb >= 0 and (left == 0 or (reg0 is not None and cap0 and reg0 >= cap0)):
            full_dates[slot].add(r["date"])
        if mb is None or not 0 <= mb <= 240:
            continue
        key = (slot, r["date"])
        if key not in best or mb < num(best[key]["mins_before"]):
            best[key] = r
    fills = defaultdict(list)
    for (slot, date), r in best.items():
        cap = num(r.get("capacity")) or slot_cap[slot]
        if not cap:
            continue
        reg = num(r.get("registered"))
        if reg is None:
            left = num(r.get("spots_left"))
            if left is None:
                continue
            reg = cap - left
        fills[slot].append(max(0.0, min(1.0, reg / cap)))
    out = []
    for slot in sorted(set(fills) | set(full_dates), key=str):
        fs, nfull = fills.get(slot, []), len(full_dates.get(slot, ()))
        if nfull >= 2:
            avg = sum(fs) / len(fs) if fs else 1.0
            out.append([*slot, "fills", round(avg * 100), nfull])
            continue
        if len(fs) < MIN_DATES:
            continue
        avg = sum(fs) / len(fs)
        level = "quiet" if avg < 0.4 else "moderate" if avg < 0.8 else "busy"
        out.append([*slot, level, round(avg * 100), len(fs)])
    path = os.path.join(ROOT, "index.html")
    s = open(path, encoding="utf-8").read()
    s2, n = re.subn(r"const BUSY_AUTO = \[.*?\];", lambda m: "const BUSY_AUTO = " + json.dumps(out, ensure_ascii=False) + ";", s, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("BUSY_AUTO line not found in index.html")
    if s2 != s:
        open(path, "w", encoding="utf-8").write(s2)
    print(f"{len(rows)} readings, {len(fills)} slots with close-to-start data, {len(full_dates)} seen full, {len(out)} labelled")


if __name__ == "__main__":
    main()
