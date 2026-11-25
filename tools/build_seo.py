"""Builds the search-friendly pages of icetimes.ca from the schedule inside index.html.

Run from the repository root after index.html's SNAPSHOT changes:
    python3 tools/build_seo.py

It writes:
  <city>/index.html      one page per city   (e.g. burnaby/index.html)
  <type>/index.html      one page per type   (e.g. stick-and-puck/index.html)
  sitemap.xml, robots.txt
and refreshes the "Browse by city / type" links between the SEO-LINKS markers in index.html.
"""
import datetime, html, json, os, re, shutil, zoneinfo
from collections import Counter, defaultdict

SITE = "https://icetimes.ca"
GTM = "GTM-PTJW8J7X"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAME = dict(zip(DAYS, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]))
# type -> (url slug, page heading noun, short plural for descriptions)
TYPES = {
    "Public Skate": ("public-skating", "Public Skating", "public skates"),
    "Adult Public Skate": ("adult-skating", "Adult Public Skating", "adult-only skates"),
    "Family Skate": ("family-skating", "Family & Parent-and-Tot Skating", "family skates"),
    "Youth Skate": ("youth-skating", "Youth & Teen Skating", "youth skates"),
    "Stick & Puck": ("stick-and-puck", "Stick & Puck", "stick & puck sessions"),
    "Drop-in Hockey": ("drop-in-hockey", "Drop-in Hockey & Shinny", "drop-in hockey sessions"),
    "Figure Skating": ("figure-skating", "Figure Skating Practice Ice", "figure skating sessions"),
}
TYPE_COLOR = {"Public Skate": "#2563a8", "Adult Public Skate": "#6d3fb5", "Family Skate": "#1f7a4a", "Youth Skate": "#0f766e",
              "Stick & Puck": "#b45309", "Drop-in Hockey": "#b42318", "Figure Skating": "#a3247a"}

e = lambda s: html.escape(str(s), quote=True)
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fmt(m):
    h, mm = divmod(m % 1440, 60)
    ap = "am" if h < 12 else "pm"
    h = h % 12 or 12
    return f"{h}{ap}" if mm == 0 else f"{h}:{mm:02d}{ap}"


def load():
    s = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    rows = json.loads(re.search(r"const SNAPSHOT = (\[.*?\]);\n", s).group(1))
    m = re.search(r"Last updated <b>([^<]+)</b>", s)
    v = re.search(r"const VALID_TO = (\{.*?\});", s, re.S)
    VALID_TO.update(json.loads(v.group(1)) if v else {})
    return s, rows, (m.group(1) if m else "")


VALID_TO = {}          # city -> last date its published ice schedule covers (from index.html)
UPD = {"ice": None, "gym": None}   # datetime.date of the last ice / gym data refresh
TZ = zoneinfo.ZoneInfo("America/Vancouver")
WD = {d: i for i, d in enumerate(DAYS)}  # Mon=0


def parse_upd(txt):
    try:
        return datetime.datetime.strptime(txt.strip(), "%b %d, %Y").date()
    except Exception:
        return None


def upd_line(d):
    """Visible freshness line under each page's heading."""
    if not d:
        return '<p class="upd">Refreshed weekly from official schedules</p>'
    nxt = d + datetime.timedelta(days=7)
    return (f'<p class="upd">Updated <time datetime="{d.isoformat()}">{d.strftime("%b")} {d.day}, {d.year}</time>'
            f' · next update by {nxt.strftime("%b")} {nxt.day} · times copied from official city and rink schedules</p>')


def price_of(cost):
    m = re.search(r"\$(\d+(?:\.\d\d)?)", cost or "")
    if m:
        return m.group(1)
    return "0" if re.search(r"\bfree\b", cost or "", re.I) else None


def events_ld(rows, place_id, upd, city, kind):
    """schema.org Events with a weekly Schedule, one per session (days grouped). kind: 'ice' or 'gym'."""
    if not upd:
        return []
    end = VALID_TO.get(city) if kind == "ice" else None
    end = datetime.date.fromisoformat(end) if end else upd + datetime.timedelta(days=13)
    groups = defaultdict(list)
    for r in rows:
        name = r["session"]
        groups[(name, r.get("type") or r.get("sport"), r["start"], r["end"], r.get("cost", ""), r.get("ages", ""))].append(r["day"])
    out = []
    for (name, kd, a, b, cost, ages), days in sorted(groups.items(), key=lambda kv: (min(WD[d] for d in kv[1]), kv[0][2])):
        days = sorted(set(days), key=WD.get)
        # next occurrence on/after the refresh date, with the real UTC offset for that day
        first = min(upd + datetime.timedelta(days=(WD[d] - upd.weekday()) % 7) for d in days)
        st = datetime.datetime.combine(first, datetime.time(a // 60 % 24, a % 60), TZ)
        en = datetime.datetime.combine(first, datetime.time(min(b, 1439) // 60, min(b, 1439) % 60), TZ)
        label = kd if kind == "ice" else SPORT_INFO[kd][1]
        ev = {"@type": "Event", "name": name if label.lower() in name.lower() else f"{name} ({label})",
              "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode", "eventStatus": "https://schema.org/EventScheduled",
              "startDate": st.isoformat(), "endDate": en.isoformat(), "location": {"@id": place_id},
              "eventSchedule": {"@type": "Schedule", "byDay": [f"https://schema.org/{DAY_NAME[d]}" for d in days],
                                "startTime": f"{a // 60 % 24:02d}:{a % 60:02d}", "endTime": f"{min(b, 1439) // 60:02d}:{min(b, 1439) % 60:02d}",
                                "repeatFrequency": "P1W", "scheduleTimezone": "America/Vancouver",
                                "startDate": upd.isoformat(), "endDate": end.isoformat()},
              "description": ", ".join(x for x in [label, f"ages {ages}" if ages and ages[0].isdigit() else ages, cost] if x)}
        pr = price_of(cost)
        if pr is not None:
            ev["isAccessibleForFree"] = pr == "0"
            ev["offers"] = {"@type": "Offer", "price": pr, "priceCurrency": "CAD", "url": f"{SITE}/how-to-book/#{htb_anchor(city)}"}
        out.append(ev)
    return out


GTM_HEAD = f"""<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{GTM}');</script>"""
GTM_BODY = f"""<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={GTM}" height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>"""

CSS = """
:root{--bg:#eef3f7;--surface:#fff;--ink:#12202d;--muted:#5a6b7a;--line:#d5dfe8;--accent:#0b5cad;--red:#d7262e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "IBM Plex Sans","Segoe UI",system-ui,sans-serif}
a{color:var(--accent)}.wrap{max-width:1000px;margin:0 auto;padding:18px 20px 48px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--ink);font:700 28px/1 "Barlow Condensed","Arial Narrow",sans-serif;letter-spacing:.3px}
.brand b{color:#1e5bc6;font-weight:700}.brand svg{width:26px;height:34px}
.crumbs{font-size:14px;color:var(--muted);margin:16px 0 4px}.crumbs a{color:var(--muted)}
h1{font:700 clamp(28px,4.4vw,40px)/1.1 "Barlow Condensed","Arial Narrow",sans-serif;margin:6px 0 10px}
h2{font:700 24px/1.2 "Barlow Condensed","Arial Narrow",sans-serif;margin:30px 0 10px;text-transform:uppercase;letter-spacing:.4px}
.upd{color:#5b6573;font-size:13px;margin:-4px 0 12px}.lead{font-size:17px;max-width:760px}.note{background:#fde9d9;border-left:4px solid #a84300;border-radius:6px;padding:9px 12px;font-size:14px;margin:14px 0}
.cta{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;font:700 18px/1 "Barlow Condensed","Arial Narrow",sans-serif;text-transform:uppercase;letter-spacing:.6px;padding:13px 18px;border-radius:8px;margin:8px 0}
.rinks{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px;padding:0;list-style:none}
.rinks li{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:14px}
.rinks b{display:block;font-size:15px}.rinks b a{color:inherit}.addr{font-size:15px;margin:6px 0}.cta.alt{margin-left:6px}.muted{color:var(--muted)}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:14px;margin-bottom:6px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);background:#f6f9fb}
td.t{white-space:nowrap;font-weight:600}.ty{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}
.tag{display:inline-block;font-size:11px;background:#e6ebf0;border-radius:4px;padding:1px 6px;margin-left:4px}
h3{font-size:16px;margin:18px 0 6px}.links{display:flex;flex-wrap:wrap;gap:6px 14px;padding:0;list-style:none;font-size:15px}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media(max-width:640px){th.hide,td.hide{display:none}}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 4px}.chip{font-size:14px;text-decoration:none;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:5px 11px}
.htb{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:4px 18px 14px;margin:12px 0;scroll-margin-top:12px}
.htb h2{font:600 20px/1.2 "IBM Plex Sans","Segoe UI",system-ui,sans-serif;text-transform:none;letter-spacing:0;margin:14px 0 6px;display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.htb p{margin:6px 0}.htb ul{margin:6px 0 10px;padding-left:20px}.htb li{margin:3px 0}
.htb:target{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}
.need{font:600 12px/1 "IBM Plex Sans",system-ui,sans-serif;border-radius:4px;padding:4px 7px}
.need-yes{background:#fde9d9;color:#a84300}.need-some{background:#e8f0fb;color:#0b5cad}.need-no{background:#e3f4ea;color:#1f7a4a}
.htb-links{display:flex;flex-wrap:wrap;gap:8px}.htb h3{font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin:12px 0 2px}.htb .sp{border-top:1px solid var(--line);margin-top:10px}.cta.alt{background:#fff;color:var(--accent);border:1px solid var(--accent)}.cta.sm{font:600 14px/1 "IBM Plex Sans",system-ui,sans-serif;text-transform:none;letter-spacing:0;padding:10px 14px;margin:4px 0}
"""

PIN = '<svg viewBox="0 0 26 34" aria-hidden="true"><path d="M13 1C6.4 1 1 6.3 1 12.9 1 22 13 33 13 33s12-11 12-20.1C25 6.3 19.6 1 13 1z" fill="#d7262e"/><ellipse cx="13" cy="12.5" rx="6.5" ry="3.4" fill="#0b2d6b"/><ellipse cx="13" cy="11.3" rx="6.5" ry="3.4" fill="#fff"/></svg>'


def page(path, title, desc, h1, crumbs, body, jsonld, modified=None):
    url = f"{SITE}/{path}"
    if modified:
        node = {"@type": "WebPage", "@id": url, "url": url, "name": title, "dateModified": modified.isoformat(),
                "isPartOf": {"@type": "WebSite", "name": "Open Ice Finder", "url": SITE + "/"}}
        jsonld = dict(jsonld)
        ctx = jsonld.pop("@context", "https://schema.org")
        graph = jsonld.pop("@graph", None) or [jsonld]
        jsonld = {"@context": ctx, "@graph": [node] + graph}
    return f"""<!DOCTYPE html>
<html lang="en-CA">
<head>
<meta charset="utf-8">
{GTM_HEAD}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Open Ice Finder">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{url}"><meta property="og:image" content="{SITE}/og-image.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
</head>
<body>
{GTM_BODY}
<div class="wrap">
<header class="top"><a class="brand" href="/">{PIN}<span>OPEN ICE <b>FINDER</b></span></a><a href="/">Search all times →</a></header>
<nav class="crumbs" aria-label="Breadcrumb">{crumbs}</nav>
<h1>{e(h1)}</h1>
{upd_line(modified)}
{body}
<footer>
<p><b>Check the rink's website before you go.</b> Times are copied every week from city and rink schedules and can change at short notice (tournaments, holidays, maintenance).</p>
<p>© {datetime.date.today().year} Open Ice Finder · icetimes.ca · Not affiliated with any city or recreation provider. Questions or a wrong time? Email feedback@icetimes.ca.</p>
</footer>
</div>
</body>
</html>
"""


def schedule_tables(rows, show_city, show_rink=True):
    out = []
    for d in DAYS:
        day = sorted([r for r in rows if r["day"] == d], key=lambda r: (r["start"], r["rink"]))
        if not day:
            continue
        out.append(f'<h3>{DAY_NAME[d]} <span class="muted">· {len(day)} session{"s" if len(day) != 1 else ""}</span></h3>')
        out.append("<table><thead><tr><th>Time</th><th>Session</th>" + ("<th>Rink</th>" if show_rink else "")
                   + ("<th>City</th>" if show_city else "") + '<th class="hide">Cost</th></tr></thead><tbody>')
        for r in day:
            tag = '<span class="tag">Private rink · book online</span>' if r.get("priv") else ""
            ages = f' <span class="muted">· {e(r["ages"])}</span>' if r.get("ages") else ""
            out.append(f'<tr><td class="t">{fmt(r["start"])}–{fmt(r["end"])}</td>'
                       f'<td><span class="ty" style="color:{TYPE_COLOR.get(r["type"], "#333")}">{e(r["type"])}</span><br>{e(r["session"])}{ages}</td>'
                       + (f'<td>{e(r["rink"])}{tag}</td>' if show_rink else "") + (f'<td>{e(r["city"])}</td>' if show_city else "")
                       + f'<td class="hide">{e(r["cost"])}</td></tr>')
        out.append("</tbody></table>")
    return "\n".join(out)


def rink_list(rows):
    by = defaultdict(list)
    for r in rows:
        by[(r["rink"], r["city"], r["address"])].append(r)
    items = []
    for (rk, city, addr), rs in sorted(by.items()):
        types = ", ".join(t for t, _ in Counter(r["type"] for r in rs).most_common())
        maps = "https://www.google.com/maps/search/?api=1&query=" + re.sub(r"\s+", "+", f"{rk}, {addr}, BC")
        priv = " · private rink, book online" if any(r.get("priv") for r in rs) else ""
        items.append(f'<li><b><a href="/places/{slug(rk)}/">{e(rk)}</a></b><a href="{e(maps)}" rel="noopener">{e(addr)}</a><br><span class="muted">{len(rs)} sessions this week · {e(types)}{priv}</span></li>')
    return '<ul class="rinks">' + "".join(items) + "</ul>"


def rink_ld(rows):
    seen, out = set(), []
    for r in rows:
        if r["rink"] in seen:
            continue
        seen.add(r["rink"])
        out.append({"@type": "IceRink", "name": r["rink"], "address": {"@type": "PostalAddress", "streetAddress": r["address"].rsplit(",", 1)[0],
                    "addressLocality": r["city"], "addressRegion": "BC", "addressCountry": "CA"}})
    return out


def crumbs(name):
    return f'<a href="/">Open Ice Finder</a> › {e(name)}'


def links_block(cities, types_present):
    c = " ".join(f'<li><a href="/{slug(x)}/">{e(x)}</a></li>' for x in cities)
    t = " ".join(f'<li><a href="/{TYPES[x][0]}/">{e(TYPES[x][1])}</a></li>' for x in TYPES if x in types_present)
    return c, t


# ---- "How to book" page: one short section per city. Checked against each city's site, Nov 2026. ----
SURREY_HOCKEY = "https://cityofsurrey.perfectmind.com/23615/Clients/BookMe4BookingPages/Classes?calendarId=7333623a-774c-4e63-aaac-b85a2cfbd17d&widgetId=b4059e75-9755-401f-a7b5-d7c75361420d&embed=False"
SURREY_SKATE = "https://cityofsurrey.perfectmind.com/23615/Clients/BookMe4BookingPages/Classes?calendarId=5b599b6d-d54f-43c1-b86a-e962d9bf107b&widgetId=b4059e75-9755-401f-a7b5-d7c75361420d&embed=False"
# (id, name, need: "yes" | "some" | "no", one-line summary, steps, links [(label, url)], phone)
HOW_TO_BOOK = [
    ("surrey", "Surrey", "some", "Hockey, stick & puck and figure skating: sign up 72 hours ahead. Public skating: no sign-up, pay at the door.",
     ["Sign-up opens exactly 72 hours before the session starts.",
      "You need a free City of Surrey recreation account to register.",
      "Hockey and stick & puck are on the Drop In Hockey list; figure skating is on the Drop In Skating list."],
     [("Drop In Hockey (hockey, stick & puck)", SURREY_HOCKEY), ("Drop In Skating (figure skating)", SURREY_SKATE)], "604-501-5100"),
    ("richmond", "Richmond", "some", "Public skates are drop-in. Stick & puck, hockey and figure skating are pre-registered.",
     ["Online booking opens at 6:00 am on Monday, one week before the session (phone from 8:30 am).",
      "You pay when you book. Drop-ins are welcome if there's space left.",
      "Each arena has its own booking list (below), listed as “Registered Visit” sessions."],
     [("Richmond Ice Centre registered visits", "https://richmondcity.perfectmind.com/23650/Clients/BookMe4BookingPages/Classes?calendarId=8bd697eb-ee1e-4067-b6bb-be1901a7753d&widgetId=15f6af07-39c5-473e-b053-96653f77a406&embed=False"), ("Minoru Arenas registered visits", "https://richmondcity.perfectmind.com/23650/Clients/BookMe4BookingPages/Classes?calendarId=5bc32e4a-6607-47f5-8513-53b2dbc4f83e&widgetId=15f6af07-39c5-473e-b053-96653f77a406&embed=False")], "604-276-4300"),
    ("burnaby", "Burnaby", "some", "Most skates are drop-in. Sessions marked “Reserve” can be booked ahead.",
     ["Reserve sessions open 48 hours ahead for Burnaby residents and 24 hours ahead for everyone else.",
      "Book on WebReg with a free Burnaby account."],
     [("Burnaby WebReg", "https://www.burnaby.ca/webreg")], "Bill Copeland 604-297-4521 · Kensington 604-297-4535"),
    ("port-coquitlam", "Port Coquitlam", "yes", "Drop-in skates and hockey are pre-registered.",
     ["Booking opens 48 hours ahead: 8 am for Port Coquitlam residents, 10 am for everyone else.",
      "You need an account. Online booking closes 30 minutes before the start.",
      "Cancel at least 24 hours ahead, or a no-show is charged."],
     [("Port Coquitlam registration", "https://www.portcoquitlam.ca/register")], "604-927-7529"),
    ("coquitlam", "Coquitlam", "some", "Sessions marked pre-register need a spot booked; the rest are drop-in.",
     ["Booking opens 48 hours before the session.",
      "In the registration system, look under “Drop In (Pre-registered)”."],
     [("Coquitlam drop-in booking", "https://www.coquitlam.ca/979")], ""),
    ("port-moody", "Port Moody", "some", "Pre-registration is recommended; you can drop in if there's space.",
     ["Book on the city's drop-in calendar with a free account."],
     [("Port Moody drop-in calendar", "https://cityofportmoody.perfectmind.com/Contacts/BookMe4BookingPages/Classes?calendarId=da287199-756a-422e-8fbc-b2e5063b77f8&widgetId=15f6af07-39c5-473e-b053-96653f77a406&embed=False")], "604-469-4556"),
    ("delta", "Delta", "some", "Hockey and stick & puck: book ahead. Public skates: usually walk-in.",
     ["Drop-ins open for pre-registration 72 hours before the start.",
      "You need a Delta recreation account (free). North Delta Rec Centre asks everyone to register ahead, so book if you can."],
     [("Delta drop-in activities", "https://cityofdelta.perfectmind.com/24140/Clients/BookMe4BookingPages/Classes?calendarId=c9b7ca71-56dc-43e3-aec7-d976239a5660&widgetId=0da93182-93fb-4314-87bd-a8ba4ee9a4c9&embed=False")], "604-952-3000"),
    ("new-westminster", "New Westminster", "some", "Most skates are drop-in. Limited-capacity sessions can be booked ahead.",
     ["Booking opens 72 hours ahead for New Westminster residents and 48 hours ahead for everyone.",
      "You can withdraw up to 3 hours before without a charge."],
     [("New Westminster registration", "https://www.newwestcity.ca/register")], ""),
    ("north-vancouver", "North Vancouver (NVRC)", "some", "Public skates are drop-in. Drop-in hockey is booked as a “book-a-visit” session.",
     ["Sports sessions open for booking at 7 am on Tuesday the week before.",
      "Book with an NVRC account, and cancel if you can't make it so someone else gets the spot."],
     [("NVRC drop-in schedules", "https://www.nvrc.ca/drop-in-schedules")], "604-987-7529"),
    ("vancouver", "Vancouver", "some", "Public skates are drop-in: just show up and pay at the rink (Flexipass accepted). Arena stick & puck, public hockey and figure skating are booked online.",
     ["Booking opens 3 days before the session; spots not booked online go on sale at the rink 30 minutes before.",
      "Check in with the attendant within 5 minutes of the start, or your spot can go to someone waiting.",
      "Cancel online by 11:59 pm the day before for a refund or credit."],
     [("Public Skating & Ice Hockey calendar", "https://anc.ca.apm.activecommunities.com/vancouver/calendars"), ("Vancouver ice rinks", "https://vancouver.ca/parks-recreation-culture/ice-rinks.aspx")], ""),
    ("maple-ridge", "Maple Ridge", "no", "Drop-in only, no booking. Pay at Planet Ice.",
     [], [("Maple Ridge public skating", "https://www.mapleridge.ca/node/1958")], ""),
    ("canlan", "Canlan rinks (private)", "yes", "Scotia Barn, Langley Twin Rinks and North Shore: book and pay online.",
     ["You need a Canlan account. Spots are limited and popular times fill up."],
     [("Scotia Barn (Burnaby)", "https://www.canlansports.com/drop-ins/?facility=1"), ("Langley Twin Rinks", "https://www.canlansports.com/drop-ins/?facility=2"), ("North Shore", "https://www.canlansports.com/drop-ins/?facility=8")], ""),
]
HTB_IDS = {x[0] for x in HOW_TO_BOOK}
# Gym & court sports (basketball, volleyball, badminton, pickleball, etc.) for the /sports/ finder.
SPORTS_BOOK = {
    "surrey": ("Most drop-in sports open for sign-up 72 hours ahead; pickleball opens Sundays at 8:30 pm. If you're not there within 10 minutes of the start, your spot goes to the waitlist.",
               [("Surrey drop-in activities", "https://cityofsurrey.perfectmind.com/23615/Clients/BookMe4?widgetId=b4059e75-9755-401f-a7b5-d7c75361420d")]),
    "richmond": ("Gym and racquet drop-ins are walk-in. A few sessions are registered visits or need a phone call; the finder notes which.",
                 [("Richmond registration", "https://www.richmond.ca/parks-recreation/registration.htm")]),
    "burnaby": ("Drop-in sports: reserving a spot on WebReg is recommended.", [("Burnaby WebReg", "https://www.burnaby.ca/webreg")]),
    "port-coquitlam": ("Sports drop-ins are pre-registered too, opening 2 days ahead.", [("Port Coquitlam registration", "https://www.portcoquitlam.ca/register")]),
    "coquitlam": ("Adult gym sessions: pre-register online 48 hours ahead.", [("Coquitlam drop-in booking", "https://www.coquitlam.ca/979")]),
    "port-moody": ("Book 25 hours ahead online, or by phone.", [("Port Moody registration", "https://www.portmoody.ca/registration")]),
    "delta": ("Pre-register online up to 72 hours ahead.", [("Delta drop-in activities", "https://cityofdelta.perfectmind.com/24140/Clients/BookMe4BookingPages/Classes?calendarId=c9b7ca71-56dc-43e3-aec7-d976239a5660&widgetId=0da93182-93fb-4314-87bd-a8ba4ee9a4c9&embed=False")]),
    "new-westminster": ("Reserve online 72 hours ahead (residents) or 48 hours ahead (everyone).", [("New Westminster registration", "https://www.newwestcity.ca/register")]),
    "north-vancouver": ("Mostly drop-in; some sessions can be booked online.", []),
    "vancouver": ("Mostly drop-in; some community centres let you reserve a spot online.", []),
    "maple-ridge": ("Pickleball and badminton are pre-registered: booking opens 50 hours before each timeslot, and you check in on site. Basketball is pre-registered too.",
                    [("Maple Ridge registration", "https://www.mapleridge.ca/1484/Program-Registration")]),
}
NEED = {"yes": "Booking needed", "some": "Some sessions", "no": "Just show up"}


def how_to_book_body():
    toc = "".join(f'<a class="chip need-{n}" href="#{i}">{e(name)}</a>' for i, name, n, *_ in HOW_TO_BOOK)
    secs = []
    for i, name, n, summary, steps, links, phone in HOW_TO_BOOK:
        st = "".join(f"<li>{e(s)}</li>" for s in steps)
        ln = "".join(f'<a class="cta sm" href="{e(u)}" target="_blank" rel="noopener">{e(l)} ↗</a>' for l, u in links)
        ph = f'<p class="muted">Or call {e(phone)}.</p>' if phone else ""
        sp = SPORTS_BOOK.get(i)
        if sp:
            sl = "".join(f'<a class="cta sm alt" href="{e(u)}" target="_blank" rel="noopener">{e(l)} ↗</a>' for l, u in sp[1])
            ph += f'<div class="sp"><h3>Gym &amp; court sports</h3><p>{e(sp[0])}</p>{f"<div class=htb-links>{sl}</div>" if sl else ""}</div>'
        secs.append(f'<section class="htb" id="{i}"><h2>{e(name)} <span class="need need-{n}">{NEED[n]}</span></h2>'
                    f'<h3>Ice</h3><p>{e(summary)}</p>{f"<ul>{st}</ul>" if st else ""}<div class="htb-links">{ln}</div>{ph}</section>')
    tips = ('<ul><li><b>Make your account first.</b> Each city has its own free account, and setting one up takes a few minutes, so do it before booking opens.</li>'
            '<li><b>Set a reminder</b> for when booking opens. Popular stick &amp; puck, hockey and pickleball times can fill within minutes.</li>'
            '<li><b>Cancel if you can\'t go.</b> Some cities charge for no-shows.</li></ul>')
    return (f'<p class="lead">Many drop-in skates and gym times are walk-in, but most stick &amp; puck, drop-in hockey and a lot of gym sports (pickleball especially) need a spot booked ahead. '
            f'Here\'s how each city does it, for ice and for gym &amp; court sports. In both finders (<a href=\"/\">ice times</a> and <a href=\"/sports/\">drop-in sports</a>), sessions that need booking have a <b>Book</b> button.</p>'
            f'<nav class="toc" aria-label="Cities">{toc}</nav><h2>Before you book</h2>{tips}{"".join(secs)}'
            f'<p class="muted">Booking rules checked November 2026. Cities change them now and then, so trust the city\'s page if it says something different.</p>')


# ---------------------------------------------------------------------------------------------
# Place pages (/places/<venue>/) and sport-by-city pages (/sports/<sport>/<city>/).
# Ice sessions come from index.html's SNAPSHOT (refreshed weekly); gym & court sports come from
# the DATA block inside sports/index.html.
SPORT_INFO = {  # key -> (url slug, name, plural noun for text)
    "basketball": ("basketball", "Basketball", "basketball"), "volleyball": ("volleyball", "Volleyball", "volleyball"),
    "soccer": ("indoor-soccer", "Indoor Soccer", "indoor soccer"), "floorhockey": ("floor-hockey", "Ball & Floor Hockey", "ball & floor hockey"),
    "netball": ("netball", "Netball", "netball"), "badminton": ("badminton", "Badminton", "badminton"),
    "pickleball": ("pickleball", "Pickleball", "pickleball"), "tabletennis": ("table-tennis", "Table Tennis", "table tennis"),
    "tennis": ("tennis", "Tennis", "tennis"), "opengym": ("open-gym", "Open Gym", "open gym"),
}
SPORT_COLOR = {"basketball": "#c2410c", "volleyball": "#7c3aed", "soccer": "#15803d", "floorhockey": "#be123c", "netball": "#0e7490",
               "badminton": "#0f766e", "pickleball": "#4d7c0f", "tabletennis": "#c026d3", "tennis": "#a16207", "opengym": "#475569"}
SPK = ["skate", "sp", "hockey", "basketball", "volleyball", "soccer", "floorhockey", "netball", "badminton", "pickleball", "tabletennis", "tennis", "opengym"]
SDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
MIN_SPORT_CITY = 3
SHORT_ICE = {"Public Skate": "Skating", "Adult Public Skate": "Skating", "Family Skate": "Skating", "Youth Skate": "Skating",
             "Stick & Puck": "Stick & Puck", "Drop-in Hockey": "Hockey", "Figure Skating": "Figure Skating"}   # a sport-by-city page needs at least this many weekly sessions


def load_sports():
    fp = os.path.join(ROOT, "sports", "index.html")
    if not os.path.exists(fp):
        return [], ""
    s = open(fp, encoding="utf-8").read()
    m = re.search(r"const DATA = (\{.*?\});\n", s, re.S)
    if not m:
        return [], ""
    d = json.loads(m.group(1)); S = d["s"]
    rows = [dict(day=SDAYS[a[0]], start=a[1], end=a[2], sport=SPK[a[3]], session=S[a[4]], venue=S[a[5]], city=S[a[6]], room=S[a[7]],
                 cost=S[a[8]], booking=S[a[9]], notes=S[a[10]], address=S[a[11]], ages=S[a[12]], priv=bool(a[13])) for a in d["r"]]
    u = re.search(r'const UPDATED = "([^"]+)"', s)
    return [r for r in rows if r["sport"] in SPORT_INFO], (u.group(1) if u else "")


def gym_tables(rows, show_venue, show_city):
    one = len({r["sport"] for r in rows}) == 1
    out = []
    for d in DAYS:
        day = sorted([r for r in rows if r["day"] == d], key=lambda r: (r["start"], r["venue"]))
        if not day:
            continue
        out.append(f'<h3>{DAY_NAME[d]} <span class="muted">· {len(day)} session{"s" if len(day) != 1 else ""}</span></h3>')
        out.append("<table><thead><tr><th>Time</th><th>Session</th>" + ("<th>Place</th>" if show_venue else "")
                   + ("<th>City</th>" if show_city else "") + '<th class="hide">Cost</th></tr></thead><tbody>')
        for r in day:
            ages = f' <span class="muted">· {e(r["ages"])}</span>' if r.get("ages") else ""
            room = f' <span class="muted">· {e(r["room"])}</span>' if r.get("room") and not show_venue else ""
            label = "" if one else f'<span class="ty" style="color:{SPORT_COLOR[r["sport"]]}">{e(SPORT_INFO[r["sport"]][1])}</span><br>'
            venue = f'<td><a href="/places/{slug(r["venue"])}/">{e(r["venue"])}</a></td>' if show_venue else ""
            out.append(f'<tr><td class="t">{fmt(r["start"])}–{fmt(r["end"])}</td>'
                       f'<td>{label}{e(r["session"])}{ages}{room}</td>'
                       + venue + (f'<td>{e(r["city"])}</td>' if show_city else "") + f'<td class="hide">{e(r["cost"])}</td></tr>')
        out.append("</tbody></table>")
    return "\n".join(out)


def ld_crumbs(*items):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + u} for i, (n, u) in enumerate(items)]}


def htb_anchor(city, priv=False):
    s = slug(city)
    return "canlan" if priv or s not in HTB_IDS else s


def write(path, html_):
    os.makedirs(os.path.join(ROOT, path), exist_ok=True)
    open(os.path.join(ROOT, path, "index.html"), "w", encoding="utf-8").write(html_)


def prune(base, keep):
    """Delete generated sub-pages under base/ that are no longer in keep (relative paths like 'places/x')."""
    top = os.path.join(ROOT, base)
    if not os.path.isdir(top):
        return
    for dirpath, dirnames, filenames in os.walk(top, topdown=False):
        rel = os.path.relpath(dirpath, ROOT).replace(os.sep, "/")
        if rel == base or rel in keep:
            continue
        fp = os.path.join(dirpath, "index.html")
        if os.path.exists(fp) and "Open Ice Finder" in open(fp, encoding="utf-8").read(3000):
            os.remove(fp)
        if not os.listdir(dirpath):
            os.rmdir(dirpath)


def build_places_and_sports(ice, when):
    gym, gym_upd = load_sports()
    UPD["gym"] = parse_upd(gym_upd)
    gym_when = f"Collected {gym_upd}" if gym_upd else when
    paths = []

    # ---------- places ----------
    venues = {}
    for r in ice:
        v = venues.setdefault(r["rink"], {"city": r["city"], "address": r["address"], "ice": [], "gym": [], "priv": False})
        v["ice"].append(r); v["priv"] |= bool(r.get("priv"))
    for r in gym:
        v = venues.setdefault(r["venue"], {"city": r["city"], "address": r["address"], "ice": [], "gym": [], "priv": False})
        v["gym"].append(r)
    by_city = defaultdict(list)
    for name, v in sorted(venues.items()):
        by_city[v["city"]].append(name)
        n_ice, n_gym = len(v["ice"]), len(v["gym"])
        kinds = [TYPES[t][2] for t, _ in Counter(r["type"] for r in v["ice"]).most_common(3)]
        kinds += [SPORT_INFO[k][2] for k, _ in Counter(r["sport"] for r in v["gym"]).most_common(4)]
        kind_txt = ", ".join(kinds[:-1]) + (" and " + kinds[-1] if len(kinds) > 1 else (kinds[0] if kinds else ""))
        ps = slug(name)
        short = [SHORT_ICE[t] for t, _ in Counter(r["type"] for r in v["ice"]).most_common()]
        short = list(dict.fromkeys(short + [SPORT_INFO[k][1] for k, _ in Counter(r["sport"] for r in v["gym"]).most_common()]))
        title = f"{name} Drop-in Times: {', '.join(short[:3])} | Open Ice Finder"
        if len(title) > 95:
            title = f"{name} Drop-in Times: {', '.join(short[:2])} | Open Ice Finder"
        desc = (f"This week's drop-in times at {name}, {v['city']}: {n_ice + n_gym} sessions including {kind_txt}. "
                f"Times, prices, how to book and directions, updated weekly.")
        maps = "https://www.google.com/maps/search/?api=1&query=" + re.sub(r"\s+", "+", f"{name}, {v['address']}, BC")
        book = f'<a href="/how-to-book/#{htb_anchor(v["city"], v["priv"])}">How booking works here →</a>'
        btns = []
        if n_ice:
            btns.append(f'<a class="cta" href="/?city={e(v["city"])}&amp;week=1">Ice times in {e(v["city"])} →</a>')
        if n_gym:
            top = Counter(r["sport"] for r in v["gym"]).most_common(1)[0][0]
            btns.append(f'<a class="cta{" alt" if n_ice else ""}" href="/sports/?city={e(v["city"])}&amp;week=1#{top}">Drop-in sports in {e(v["city"])} →</a>')
        body = (f'<p class="lead"><b>{n_ice + n_gym} drop-in sessions</b> this week at {e(name)}: {e(kind_txt)}.</p>'
                f'<p class="addr">📍 <a href="{e(maps)}" rel="noopener">{e(v["address"])}</a> · {e(v["city"])}'
                + (' · <span class="tag">Private rink · book online</span>' if v["priv"] else "") + f'</p><p class="muted">{book}</p>'
                + "".join(btns))
        if n_ice:
            body += f'<h2>Ice times this week</h2><p class="muted">{e(when)}.</p>{schedule_tables(v["ice"], False, False)}'
        if n_gym:
            body += f'<h2>Gym &amp; court sports this week</h2><p class="muted">{e(gym_when)}.</p>{gym_tables(v["gym"], False, False)}'
        others = sorted(n for n, w in venues.items() if w["city"] == v["city"] and n != name)[:12]
        if others:
            body += f'<h2>Other places in {e(v["city"])}</h2><ul class="links">' + "".join(f'<li><a href="/places/{slug(o)}/">{e(o)}</a></li>' for o in others) + "</ul>"
        pid = f"{SITE}/places/{ps}/#place"
        place = {"@type": "IceRink" if n_ice and not n_gym else "SportsActivityLocation", "@id": pid, "name": name, "url": f"{SITE}/places/{ps}/",
                 "address": {"@type": "PostalAddress", "streetAddress": v["address"].rsplit(",", 1)[0], "addressLocality": v["city"],
                             "addressRegion": "BC", "addressCountry": "CA"}}
        ld = {"@context": "https://schema.org", "@graph": [ld_crumbs(("Open Ice Finder", "/"), (v["city"], f"/{slug(v['city'])}/") if os.path.isdir(os.path.join(ROOT, slug(v["city"]))) else ("Places", "/places/"), (name, f"/places/{ps}/")), place]
              + events_ld(v["ice"], pid, UPD["ice"], v["city"], "ice") + events_ld(v["gym"], pid, UPD["gym"], v["city"], "gym")}
        mod = max([d for d, n in ((UPD["ice"], n_ice), (UPD["gym"], n_gym)) if d and n], default=None)
        cr = f'<a href="/">Open Ice Finder</a> › <a href="/places/">Places</a> › {e(name)}'
        write(f"places/{ps}", page(f"places/{ps}/", title, desc, f"{name}: drop-in times", cr, body, ld, mod))
        paths.append(f"places/{ps}/")

    # places index
    lis = []
    for city in sorted(by_city):
        lis.append(f'<h2>{e(city)}</h2><ul class="links">' + "".join(f'<li><a href="/places/{slug(n)}/">{e(n)}</a></li>' for n in sorted(by_city[city])) + "</ul>")
    write("places", page("places/", "Rinks & Community Centres with Drop-in Times – Metro Vancouver | Open Ice Finder",
                         f"Drop-in skating, hockey and gym sports schedules for {len(venues)} rinks and community centres across the Lower Mainland, updated weekly.",
                         "Rinks & community centres", crumbs("Places"),
                         f'<p class="lead">This week\'s drop-in schedule for each of the {len(venues)} rinks and community centres on Open Ice Finder.</p>' + "".join(lis),
                         {"@context": "https://schema.org", **ld_crumbs(("Open Ice Finder", "/"), ("Places", "/places/"))},
                         max([d for d in UPD.values() if d], default=None)))
    paths.append("places/")

    # ---------- sport hubs + sport-by-city ----------
    hub_links = []
    for k, (sl, name, noun) in SPORT_INFO.items():
        rs = [r for r in gym if r["sport"] == k]
        if not rs:
            continue
        bycity = Counter(r["city"] for r in rs)
        nv = len({r["venue"] for r in rs})
        city_pages = []
        for city, n in sorted(bycity.items()):
            if n < MIN_SPORT_CITY:
                continue
            crs = [r for r in rs if r["city"] == city]
            cv = len({r["venue"] for r in crs})
            path = f"sports/{sl}/{slug(city)}/"
            title = f"Drop-in {name} in {city} – This Week's Times | Open Ice Finder"
            desc = (f"This week's drop-in {noun} in {city}, BC: {n} sessions at {cv} community centre{'s' if cv != 1 else ''}. "
                    f"Times, prices and how to book, updated weekly.")
            body = (f'<p class="lead"><b>{n} drop-in {e(noun)} sessions</b> this week at {cv} place{"s" if cv != 1 else ""} in {e(city)}. {e(gym_when)}, from official schedules.</p>'
                    f'<a class="cta" href="/sports/?city={e(city)}&amp;week=1#{k}">Open {e(noun)} in the finder →</a>'
                    f'<p class="muted"><a href="/how-to-book/#{htb_anchor(city)}">How booking works in {e(city)} →</a></p>'
                    f'<h2>This week\'s {e(noun)} times in {e(city)}</h2>{gym_tables(crs, True, False)}'
                    f'<p class="muted"><a href="/sports/{sl}/">Drop-in {e(noun)} in other cities →</a></p>')
            cr = f'<a href="/">Open Ice Finder</a> › <a href="/sports/{sl}/">{e(name)}</a> › {e(city)}'
            ld = {"@context": "https://schema.org", **ld_crumbs(("Open Ice Finder", "/"), (name, f"/sports/{sl}/"), (city, "/" + path))}
            write(path.rstrip("/"), page(path, title, desc, f"Drop-in {noun} in {city}", cr, body, ld, UPD["gym"]))
            paths.append(path); city_pages.append((city, n))
        path = f"sports/{sl}/"
        nc = len(bycity)
        title = f"Drop-in {name} in Vancouver & the Lower Mainland – This Week | Open Ice Finder"
        desc = (f"Every drop-in {noun} time this week across Metro Vancouver: {len(rs)} sessions at {nv} community centres in {nc} cities. "
                f"Times, prices and how to book, updated weekly.")
        clist = "".join(f'<li><a href="/sports/{sl}/{slug(c)}/">{e(c)}</a> <span class="muted">({n})</span></li>' for c, n in city_pages)
        body = (f'<p class="lead"><b>{len(rs)} drop-in {e(noun)} sessions</b> this week at {nv} places in {nc} cities. {e(gym_when)}, from official schedules.</p>'
                f'<a class="cta" href="/sports/?week=1#{k}">Find {e(noun)} near you →</a>'
                + (f'<h2>By city</h2><ul class="links">{clist}</ul>' if clist else "")
                + f'<h2>This week\'s {e(noun)} times</h2>{gym_tables(rs, True, True)}')
        cr = f'<a href="/">Open Ice Finder</a> › <a href="/sports/">Drop-in sports</a> › {e(name)}'
        ld = {"@context": "https://schema.org", **ld_crumbs(("Open Ice Finder", "/"), ("Drop-in sports", "/sports/"), (name, "/" + path))}
        write(path.rstrip("/"), page(path, title, desc, f"Drop-in {noun} in Vancouver & the Lower Mainland", cr, body, ld, UPD["gym"]))
        paths.append(path); hub_links.append((sl, name, len(rs)))

    prune("places", {p.rstrip("/") for p in paths})
    prune("sports", {p.rstrip("/") for p in paths})
    return paths, hub_links, by_city


GLANCE_GROUPS = [("Stick & puck", ["Stick & Puck"]), ("Drop-in hockey & shinny", ["Drop-in Hockey"]),
                 ("Public, adult, family & youth skating", ["Public Skate", "Adult Public Skate", "Family Skate", "Youth Skate"]),
                 ("Figure skating practice ice", ["Figure Skating"])]


def glance_block(rows, upd):
    """Plain-text copy of the week's ice times on the main page, for readers that don't run JavaScript (search engines, AI assistants)."""
    when = (f'Updated <time datetime="{upd.isoformat()}">{upd.strftime("%b")} {upd.day}, {upd.year}</time>, next update by '
            f'{(upd + datetime.timedelta(days=7)).strftime("%b")} {(upd + datetime.timedelta(days=7)).day}.') if upd else "Updated weekly."
    out = [f'<!--GLANCE--><section class="browse glance" aria-labelledby="glanceH"><details><summary><h2 id="glanceH">This week\'s ice times as a plain list</h2></summary>'
           f'<p>{when} Weekly drop-in times across Metro Vancouver, copied from official city and rink schedules; times repeat each week unless noted. '
           f'Check the rink\'s website before you go. Booking rules: <a href="/how-to-book/">how to book</a>.</p>']
    for title, types in GLANCE_GROUPS:
        rs = [r for r in rows if r["type"] in types]
        if not rs:
            continue
        out.append(f"<h3>{e(title)}</h3>")
        for city in sorted({r["city"] for r in rs}):
            items = []
            for r in sorted((r for r in rs if r["city"] == city), key=lambda r: (WD[r["day"]], r["start"], r["rink"])):
                pr = price_of(r.get("cost"))
                extra = [x for x in [r.get("ages") or "", "free" if pr == "0" else f"${pr}" if pr else "",
                                     "book online" if r.get("priv") else ""] if x]
                nm = "" if r["session"].strip().lower() in (r["type"].lower(), "public skate", "stick & puck") else f' {e(r["session"])},'
                items.append(f'{r["day"]} {fmt(r["start"])}–{fmt(r["end"])}{nm} {e(r["rink"])}' + (f' ({e(", ".join(extra))})' if extra else ""))
            out.append(f'<p><b><a href="/{slug(city)}/">{e(city)}</a>:</b> ' + "; ".join(items) + ".</p>")
    out.append("</details></section><!--/GLANCE-->")
    return "".join(out)


def main():
    idx, rows, updated = load()
    UPD["ice"] = parse_upd(updated)
    cities = sorted({r["city"] for r in rows})
    types_present = {r["type"] for r in rows}
    clinks, tlinks = links_block(cities, types_present)
    more = f'<h2>Other cities</h2><ul class="links">{clinks}</ul><h2>By type of ice time</h2><ul class="links">{tlinks}</ul>'
    when = f"Updated {e(updated)}" if updated else "Updated weekly"
    paths = []

    for city in cities:
        rs = [r for r in rows if r["city"] == city]
        nr = len({r["rink"] for r in rs})
        tc = Counter(r["type"] for r in rs)
        kinds = ", ".join(TYPES[t][2] for t, _ in tc.most_common(4))
        title = f"Public Skating & Drop-in Hockey in {city} – This Week's Times | Open Ice Finder"
        desc = (f"This week's drop-in ice times in {city}, BC: {len(rs)} sessions at {nr} rink{'s' if nr != 1 else ''}, "
                f"including {kinds}. Times, prices and booking rules, updated weekly.")
        h1 = f"Drop-in skating & hockey in {city}"
        body = (f'<p class="lead">This week\'s public skating, stick &amp; puck, drop-in hockey and other drop-in ice times at '
                f'{nr} rink{"s" if nr != 1 else ""} in {e(city)}: <b>{len(rs)} sessions</b>. {when}, collected from official schedules.</p>'
                f'<a class="cta" href="/?city={e(city)}&amp;week=1">Open the finder for {e(city)} →</a>'
                f'<p class="muted"><a href="/how-to-book/#{slug(city) if slug(city) in HTB_IDS else "canlan"}">How booking works in {e(city)} →</a></p>'
                f'<p class="muted">The finder adds filters for time and type, distance from where you are, a map for each session and directions.</p>'
                f'<h2>Rinks in {e(city)}</h2>{rink_list(rs)}<h2>This week\'s ice times in {e(city)}</h2>{schedule_tables(rs, False)}{more}')
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Open Ice Finder", "item": SITE + "/"},
                {"@type": "ListItem", "position": 2, "name": city, "item": f"{SITE}/{slug(city)}/"}]},
            {"@type": "ItemList", "name": f"Ice rinks with drop-in times in {city}", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "item": it} for i, it in enumerate(rink_ld(rs))]}]}
        path = f"{slug(city)}/"
        os.makedirs(os.path.join(ROOT, slug(city)), exist_ok=True)
        open(os.path.join(ROOT, slug(city), "index.html"), "w", encoding="utf-8").write(page(path, title, desc, h1, crumbs(city), body, ld, UPD["ice"]))
        paths.append(path)

    for t, (sl, noun, plural) in TYPES.items():
        rs = [r for r in rows if r["type"] == t]
        if not rs:
            continue
        nc = len({r["city"] for r in rs}); nr = len({r["rink"] for r in rs})
        title = f"{noun} Times in Vancouver & the Lower Mainland – This Week | Open Ice Finder"
        desc = (f"Every drop-in {plural.rstrip('s') if plural.endswith('sessions') else plural} time this week across Metro Vancouver: "
                f"{len(rs)} sessions at {nr} rinks in {nc} cities. Times, prices and booking rules, updated weekly.")
        h1 = f"{noun} in Vancouver & the Lower Mainland"
        bycity = Counter(r["city"] for r in rs)
        citylist = " ".join(f'<li><a href="/{slug(c)}/">{e(c)}</a> <span class="muted">({n})</span></li>' for c, n in sorted(bycity.items()))
        body = (f'<p class="lead">All {e(plural)} on this week\'s schedules across Metro Vancouver: <b>{len(rs)} sessions</b> at {nr} rinks in {nc} cities. '
                f'{when}, collected from official city and rink schedules.</p>'
                f'<a class="cta" href="/?type={e(t)}&amp;week=1">Find {e(noun.lower())} near you →</a>'
                f'<h2>By city</h2><ul class="links">{citylist}</ul>'
                f'<h2>This week\'s {e(noun.lower())} times</h2>{schedule_tables(rs, True)}{more}')
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Open Ice Finder", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": noun, "item": f"{SITE}/{sl}/"}]}
        os.makedirs(os.path.join(ROOT, sl), exist_ok=True)
        open(os.path.join(ROOT, sl, "index.html"), "w", encoding="utf-8").write(page(f"{sl}/", title, desc, h1, crumbs(noun), body, ld, UPD["ice"]))
        paths.append(f"{sl}/")

    # how-to-book guide
    hb_title = "How to Book Drop-in Hockey, Skating, Pickleball & Gym Sports in Metro Vancouver | Open Ice Finder"
    hb_desc = "Which Lower Mainland drop-in ice and gym sports need booking, when booking opens in each city, and direct links to each booking page."
    hb_ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Open Ice Finder", "item": f"{SITE}/"},
        {"@type": "ListItem", "position": 2, "name": "How to book", "item": f"{SITE}/how-to-book/"}]}
    os.makedirs(os.path.join(ROOT, "how-to-book"), exist_ok=True)
    open(os.path.join(ROOT, "how-to-book", "index.html"), "w", encoding="utf-8").write(
        page("how-to-book/", hb_title, hb_desc, "How to book drop-in ice & sports", crumbs("How to book"), how_to_book_body(), hb_ld))
    paths.append("how-to-book/")

    # places + sport pages
    more_paths, hub_links, places_by_city = build_places_and_sports(rows, when)
    paths += more_paths

    # remove pages for cities/types that dropped out of the data
    keep = {p.strip("/") for p in paths} | {"sports", "places"}
    for d in os.listdir(ROOT):
        fp = os.path.join(ROOT, d, "index.html")
        if os.path.isdir(os.path.join(ROOT, d)) and os.path.exists(fp) and d not in keep and d not in {"tools", ".git"}:
            if "Open Ice Finder" in open(fp, encoding="utf-8").read(2000):
                shutil.rmtree(os.path.join(ROOT, d))

    # browse links on the main page
    slinks = " ".join(f'<li><a href="/sports/{sl}/">{e(n)}</a></li>' for sl, n, _ in hub_links)
    block = (f'<!--SEO-LINKS--><section class="browse" aria-label="Browse ice times by city and type">'
             f'<h2>Browse this week\'s ice times</h2><p>By city:</p><ul>{clinks}</ul><p>By type of ice time:</p><ul>{tlinks}</ul>'
             f'<p>Drop-in sports:</p><ul>{slinks}</ul><p><a href="/places/">Every rink &amp; community centre →</a></p></section><!--/SEO-LINKS-->')
    idx2 = re.sub(r"<!--SEO-LINKS-->.*?<!--/SEO-LINKS-->", lambda m: block, idx, flags=re.S)
    glance = glance_block(rows, UPD["ice"])
    if "<!--GLANCE-->" in idx2:
        idx2 = re.sub(r"<!--GLANCE-->.*?<!--/GLANCE-->", lambda m: glance, idx2, flags=re.S)
    else:
        idx2 = idx2.replace("<!--SEO-LINKS-->", glance + "\n<!--SEO-LINKS-->", 1)
    if idx2 != idx:
        open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(idx2)

    today = datetime.date.today().isoformat()
    urls = [SITE + "/", SITE + "/sports/"] + [f"{SITE}/{p}" for p in paths]  # /sports/ is the multi-sport Drop-in Finder
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{u}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq></url>" for u in urls]
    sm.append("</urlset>")
    open(os.path.join(ROOT, "sitemap.xml"), "w").write("\n".join(sm) + "\n")
    open(os.path.join(ROOT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    print(f"{len(paths)} pages + sitemap ({len(urls)} URLs)")


if __name__ == "__main__":
    main()
