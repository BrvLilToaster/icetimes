"""Daily collector: reads public booking lists in a headless browser and writes the real,
dated sessions into index.html (the LIVE block), so one-off changes and cancellations show.

Read-only: it only loads public pages. It never signs in, registers, adds to a cart or joins a waitlist.
Canlan is read through its normal public page (never its JSON API directly).

Sources (v1):
  Surrey  - PerfectMind "Drop In Hockey" list: hockey + stick & puck at all six Surrey rinks
  Canlan  - DaySmart drop-in list for Scotia Barn, Langley Twin Rinks and North Shore

Each source that loads correctly "covers" its rinks and types for the dates it checked; the site then
shows the dated sessions there instead of the weekly pattern. A source that fails covers nothing,
so the site falls back to the weekly pattern for it.

Run:  python3 tools/collect.py            (needs: pip install playwright; playwright install chromium)
"""
import datetime as dt, json, os, re, sys, zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
TZ = zoneinfo.ZoneInfo("America/Vancouver")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36 icetimes.ca-collector (+https://icetimes.ca)"
CANLAN_DAYS = 10
DEBUG = Path(os.environ["COLLECT_DEBUG"]) if os.environ.get("COLLECT_DEBUG") else None


def dump(page, name):
    """Debug runs: keep what the page looked like (text + screenshot) so parsing can be checked."""
    if not DEBUG:
        return
    DEBUG.mkdir(parents=True, exist_ok=True)
    try:
        txt = page.locator("body").inner_text()
        (DEBUG / f"{name}.txt").write_text(txt, encoding="utf-8")
        i = max(txt.find("Showing"), 0) if name.startswith("canlan") else 0
        print(f"===== DUMP {name} =====\n" + txt[i:i + 1800].replace("\n", " ⏎ ") + "\n===== END =====")
        page.screenshot(path=str(DEBUG / f"{name}.png"), full_page=False)
    except Exception as e:
        print(f"  (debug dump {name} failed: {e})", file=sys.stderr)

SURREY_URL = ("https://cityofsurrey.perfectmind.com/23615/Clients/BookMe4BookingPages/Classes?"
              "calendarId=7333623a-774c-4e63-aaac-b85a2cfbd17d&widgetId=b4059e75-9755-401f-a7b5-d7c75361420d&embed=False")
SURREY_RINKS = [("South Surrey Arena", "South Surrey Arena"), ("Cloverdale Sport and Ice Complex", "Cloverdale Sport & Ice Complex"),
                ("Cloverdale Arena", "Cloverdale Arena"), ("North Surrey Sport and Ice Complex", "North Surrey Sport & Ice Complex"),
                ("Surrey Sport and Leisure Complex", "Surrey Sport & Leisure Complex"), ("Newton Arena", "Newton Arena")]
CANLAN = {"1": "Canlan Sports Scotia Barn", "2": "Canlan Sports Langley Twin Rinks", "8": "Canlan Ice Sports North Shore"}
ICE_TYPES = ["Public Skate", "Adult Public Skate", "Family Skate", "Youth Skate", "Stick & Puck", "Drop-in Hockey", "Figure Skating"]


def mins(t):
    m = re.match(r"(\d{1,2}):(\d{2})\s*([ap])m", t.strip().lower())
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "p" else 0)
    return h * 60 + int(m.group(2))


def load_snapshot():
    s = INDEX.read_text(encoding="utf-8")
    return s, json.loads(re.search(r"const SNAPSHOT = (\[.*?\]);", s, re.S).group(1))


def template_for(snap, rink, typ, day, start, name):
    """Copy details (cost, booking, ages, notes...) from the weekly row this session belongs to."""
    same = [r for r in snap if r["rink"] == rink and r["type"] == typ]
    for r in same:
        if r["day"] == day and r["start"] == start:
            return r, True
    norm = lambda x: re.sub(r"[^a-z0-9+]+", " ", x.lower()).strip()
    for r in same:
        if norm(r["session"]) == norm(name):
            return r, False
    any_rink = [r for r in snap if r["rink"] == rink]
    return (same or any_rink or [None])[0], False


def make_row(snap, date, start, end, typ, name, rink, extra_notes=""):
    day = DAYS[date.weekday()]
    tpl, exact = template_for(snap, rink, typ, day, start, name)
    row = {k: (tpl or {}).get(k, "") for k in ["city", "ages", "cost", "booking", "address", "priv", "link"]}
    row["priv"] = bool(row["priv"])
    notes = "" if not tpl else tpl.get("notes", "")
    notes = "" if re.search(r"cancel|time change|only|runs to", notes, re.I) else notes
    if tpl and not exact and tpl["type"] == typ and tpl["session"] != name and re.sub(r"\W", "", tpl["session"].lower()) != re.sub(r"\W", "", name.lower()):
        row["ages"] = ""   # different session at the same rink: don't borrow its ages
    row.update(date=date.isoformat(), day=day, start=start, end=end, type=typ,
               session=(tpl["session"] if tpl and tpl["type"] == typ and re.sub(r"\W", "", tpl["session"].lower()) == re.sub(r"\W", "", name.lower()) else name),
               rink=rink, notes="; ".join(x for x in [notes, extra_notes] if x))
    return row


# ---------------------------------------------------------------- Surrey
def surrey_name(raw):
    if re.search(r"goalie", raw, re.I):
        return None, None
    name = re.sub(r"^Drop In\s+", "", raw.strip())
    name = name.replace("(Player) ", "").replace(" (Player)", "")
    name = re.sub(r"\s+-\s+", " ", name).strip()
    typ = "Stick & Puck" if re.search(r"stick", name, re.I) else "Drop-in Hockey" if re.search(r"hockey", name, re.I) else None
    return name, typ


def surrey_rink(loc):
    for prefix, rink in SURREY_RINKS:
        if loc.startswith(prefix):
            return rink
    return None


def collect_surrey(page, snap, today):
    page.goto(SURREY_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("text=/\\d{2}:\\d{2} [ap]m - /", timeout=60000)
    finally:
        dump(page, "surrey_first")
    for _ in range(12):
        btn = page.locator("button:has-text('Load More')")
        if not btn.count() or not btn.first.is_visible():
            break
        btn.first.click()
        page.wait_for_timeout(2500)
    lines = [l.strip() for l in page.locator("main").inner_text().splitlines() if l.strip()]
    rows, cur, last = [], None, None
    tre = re.compile(r"^(\d{1,2}:\d{2} [ap]m) - (\d{1,2}:\d{2} [ap]m)$", re.I)
    for i, l in enumerate(lines):
        m = re.match(r"^(?:Events for )?\w{3}, (\w+) (\d+)\w*, (\d{4})$", l)
        if m:
            cur = dt.datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
            last = cur
            continue
        m = tre.match(l)
        if not (m and cur):
            continue
        j = i - 1
        while j >= 0 and (re.match(r"^#\d+$", lines[j]) or lines[j].lower() in ("register", "waitlist")):
            j -= 1
        name, typ = surrey_name(re.sub(r"\s+#\d+$", "", lines[j]))
        rink = surrey_rink(lines[i + 1]) if i + 1 < len(lines) else None
        if not (typ and rink) or cur < today:
            continue
        spots = next((x for x in lines[i + 2:i + 5] if re.search(r"spots? left|FULL", x, re.I)), "")
        r = make_row(snap, cur, mins(m.group(1)), mins(m.group(2)), typ, name, rink)
        if re.search(r"FULL", spots):
            r["full"] = True
        rows.append(r)
    if len(rows) < 10 or not last:
        raise RuntimeError(f"Surrey: only {len(rows)} sessions parsed; not trusting it")
    cover = [{"rink": rk, "types": ["Stick & Puck", "Drop-in Hockey"], "from": today.isoformat(), "to": last.isoformat()}
             for _, rk in SURREY_RINKS]
    return rows, cover


# ---------------------------------------------------------------- Canlan
def canlan_type(name):
    n = name.lower()
    if "goalie" in n:
        return None
    if "stick" in n:
        return "Stick & Puck"
    if "figure" in n or "freestyle" in n:
        return "Figure Skating"
    if "hockey" in n or "shinny" in n or "pick" in n:
        return "Drop-in Hockey"
    if "skat" in n:
        return "Family Skate" if "family" in n else "Public Skate"
    return None


def collect_canlan(page, snap, today):
    rows, cover = [], []
    tre = re.compile(r"^(\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(\d{1,2}:\d{2}\s*[ap]m)$", re.I)
    for fac, rink in CANLAN.items():
        ok_days = []
        for k in range(CANLAN_DAYS):
            d = today + dt.timedelta(days=k)
            url = f"https://apps.daysmartrecreation.com/dash/x/canlan/event-registration?date={d.isoformat()}&facility_ids={fac}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector("text=/\\d+ EVENTS?/i", timeout=45000)
                try:
                    page.wait_for_selector("text=/Showing all results|Registered/", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                if page.locator("text=Loading...").count() and page.locator("text=Loading...").first.is_visible():
                    page.wait_for_timeout(4000)
                text = page.locator("body").inner_text()
                if k in (2, 3):
                    dump(page, f"canlan_{fac}_{d.isoformat()}")
            except Exception as e:
                print(f"  Canlan {rink} {d}: {e.__class__.__name__}", file=sys.stderr)
                continue
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if "Showing all results" not in text and not re.search(r"no (events|results)", text, re.I):
                # an empty day shows no list; make sure the selected day's tile really says 0
                pass
            for i, l in enumerate(lines):
                m = tre.match(l)
                if not m or i == 0:
                    continue
                name = lines[i - 1]
                typ = canlan_type(name)
                if not typ:
                    continue
                reg = next((x for x in lines[i + 1:i + 6] if re.search(r"\d+/\d+ Registered", x)), "")
                r = make_row(snap, d, mins(m.group(1)), mins(m.group(2)), typ, name, rink)
                mm = re.search(r"(\d+)/(\d+) Registered", reg)
                if mm and int(mm.group(1)) >= int(mm.group(2)):
                    r["full"] = True
                rows.append(r)
            ok_days.append(d)
        # cover only the unbroken run of days that loaded, starting today, and only if something was found
        if not any(r["rink"] == rink for r in rows):
            print(f"  Canlan {rink}: no sessions recognised in {len(ok_days)} days; not covering it", file=sys.stderr)
            continue
        run = 0
        while run < len(ok_days) and ok_days[run] == today + dt.timedelta(days=run):
            run += 1
        if run:
            cover.append({"rink": rink, "types": ICE_TYPES, "from": today.isoformat(), "to": (today + dt.timedelta(days=run - 1)).isoformat()})
        print(f"  Canlan {rink}: {run}/{CANLAN_DAYS} days read")
    return rows, cover


# ---------------------------------------------------------------- write
def write_live(src, rows, cover, checked):
    rows.sort(key=lambda r: (r["date"], r["start"], r["rink"]))
    live = {"checked": checked, "cover": cover, "rows": rows}
    block = "/*LIVE*/const LIVE = " + json.dumps(live, ensure_ascii=False, separators=(",", ":")) + ";/*/LIVE*/"
    if "/*LIVE*/" in src:
        out = re.sub(r"/\*LIVE\*/.*?/\*/LIVE\*/", lambda m: block, src, flags=re.S)
    else:
        out = src.replace("let DATA = SNAPSHOT;", block + "\nlet DATA = SNAPSHOT;", 1)
    INDEX.write_text(out, encoding="utf-8")


def main():
    from playwright.sync_api import sync_playwright
    now = dt.datetime.now(TZ)
    today = now.date()
    src, snap = load_snapshot()
    rows, cover, failed = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(user_agent=UA, viewport={"width": 1280, "height": 1000}, timezone_id="America/Vancouver")
        for name, fn in [("Surrey", collect_surrey), ("Canlan", collect_canlan)]:
            try:
                r, c = fn(page, snap, today)
                rows += r; cover += c
                print(f"{name}: {len(r)} sessions, {len(c)} rinks covered")
            except Exception as e:
                failed.append(name)
                print(f"{name}: FAILED ({e})", file=sys.stderr)
        b.close()
    if not cover:
        print("Nothing collected; leaving the site unchanged.", file=sys.stderr)
        sys.exit(1)
    write_live(src, rows, cover, now.strftime("%Y-%m-%dT%H:%M"))
    print(f"Wrote {len(rows)} dated sessions. Failed sources: {failed or 'none'}")


if __name__ == "__main__":
    main()
