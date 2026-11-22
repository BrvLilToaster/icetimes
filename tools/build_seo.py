"""Builds the search-friendly pages of icetimes.ca from the schedule inside index.html.

Run from the repository root after index.html's SNAPSHOT changes:
    python3 tools/build_seo.py

It writes:
  <city>/index.html      one page per city   (e.g. burnaby/index.html)
  <type>/index.html      one page per type   (e.g. stick-and-puck/index.html)
  sitemap.xml, robots.txt
and refreshes the "Browse by city / type" links between the SEO-LINKS markers in index.html.
"""
import datetime, html, json, os, re, shutil
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
    return s, rows, (m.group(1) if m else "")


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
.lead{font-size:17px;max-width:760px}.note{background:#fde9d9;border-left:4px solid #a84300;border-radius:6px;padding:9px 12px;font-size:14px;margin:14px 0}
.cta{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;font:700 18px/1 "Barlow Condensed","Arial Narrow",sans-serif;text-transform:uppercase;letter-spacing:.6px;padding:13px 18px;border-radius:8px;margin:8px 0}
.rinks{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px;padding:0;list-style:none}
.rinks li{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:14px}
.rinks b{display:block;font-size:15px}.muted{color:var(--muted)}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:14px;margin-bottom:6px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);background:#f6f9fb}
td.t{white-space:nowrap;font-weight:600}.ty{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}
.tag{display:inline-block;font-size:11px;background:#e6ebf0;border-radius:4px;padding:1px 6px;margin-left:4px}
h3{font-size:16px;margin:18px 0 6px}.links{display:flex;flex-wrap:wrap;gap:6px 14px;padding:0;list-style:none;font-size:15px}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media(max-width:640px){th.hide,td.hide{display:none}}
"""

PIN = '<svg viewBox="0 0 26 34" aria-hidden="true"><path d="M13 1C6.4 1 1 6.3 1 12.9 1 22 13 33 13 33s12-11 12-20.1C25 6.3 19.6 1 13 1z" fill="#d7262e"/><ellipse cx="13" cy="12.5" rx="6.5" ry="3.4" fill="#0b2d6b"/><ellipse cx="13" cy="11.3" rx="6.5" ry="3.4" fill="#fff"/></svg>'


def page(path, title, desc, h1, crumbs, body, jsonld):
    url = f"{SITE}/{path}"
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
{body}
<footer>
<p><b>Check the rink's website before you go.</b> Times are copied every week from city and rink schedules and can change at short notice (tournaments, holidays, maintenance).</p>
<p>© {datetime.date.today().year} Open Ice Finder · icetimes.ca · Not affiliated with any city or recreation provider. Questions or a wrong time? Email feedback@icetimes.ca.</p>
</footer>
</div>
</body>
</html>
"""


def schedule_tables(rows, show_city):
    out = []
    for d in DAYS:
        day = sorted([r for r in rows if r["day"] == d], key=lambda r: (r["start"], r["rink"]))
        if not day:
            continue
        out.append(f'<h3>{DAY_NAME[d]} <span class="muted">· {len(day)} session{"s" if len(day) != 1 else ""}</span></h3>')
        out.append("<table><thead><tr><th>Time</th><th>Session</th><th>Rink</th>"
                   + ("<th>City</th>" if show_city else "") + '<th class="hide">Cost</th></tr></thead><tbody>')
        for r in day:
            tag = '<span class="tag">Private rink · book online</span>' if r.get("priv") else ""
            ages = f' <span class="muted">· {e(r["ages"])}</span>' if r.get("ages") else ""
            out.append(f'<tr><td class="t">{fmt(r["start"])}–{fmt(r["end"])}</td>'
                       f'<td><span class="ty" style="color:{TYPE_COLOR.get(r["type"], "#333")}">{e(r["type"])}</span><br>{e(r["session"])}{ages}</td>'
                       f'<td>{e(r["rink"])}{tag}</td>' + (f'<td>{e(r["city"])}</td>' if show_city else "")
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
        items.append(f'<li><b>{e(rk)}</b><a href="{e(maps)}" rel="noopener">{e(addr)}</a><br><span class="muted">{len(rs)} sessions this week · {e(types)}{priv}</span></li>')
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


def main():
    idx, rows, updated = load()
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
        open(os.path.join(ROOT, slug(city), "index.html"), "w", encoding="utf-8").write(page(path, title, desc, h1, crumbs(city), body, ld))
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
        open(os.path.join(ROOT, sl, "index.html"), "w", encoding="utf-8").write(page(f"{sl}/", title, desc, h1, crumbs(noun), body, ld))
        paths.append(f"{sl}/")

    # remove pages for cities/types that dropped out of the data
    keep = {p.strip("/") for p in paths}
    for d in os.listdir(ROOT):
        fp = os.path.join(ROOT, d, "index.html")
        if os.path.isdir(os.path.join(ROOT, d)) and os.path.exists(fp) and d not in keep and d not in {"tools", ".git"}:
            if "Open Ice Finder" in open(fp, encoding="utf-8").read(2000):
                shutil.rmtree(os.path.join(ROOT, d))

    # browse links on the main page
    block = (f'<!--SEO-LINKS--><section class="browse" aria-label="Browse ice times by city and type">'
             f'<h2>Browse this week\'s ice times</h2><p>By city:</p><ul>{clinks}</ul><p>By type of ice time:</p><ul>{tlinks}</ul></section><!--/SEO-LINKS-->')
    idx2 = re.sub(r"<!--SEO-LINKS-->.*?<!--/SEO-LINKS-->", lambda m: block, idx, flags=re.S)
    if idx2 != idx:
        open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(idx2)

    today = datetime.date.today().isoformat()
    urls = [SITE + "/"] + [f"{SITE}/{p}" for p in paths]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{u}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq></url>" for u in urls]
    sm.append("</urlset>")
    open(os.path.join(ROOT, "sitemap.xml"), "w").write("\n".join(sm) + "\n")
    open(os.path.join(ROOT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    print(f"{len(paths)} pages + sitemap ({len(urls)} URLs)")


if __name__ == "__main__":
    main()
