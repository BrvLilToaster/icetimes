# Sign-up counts ("How busy" labels)

Collected once a week during the Monday refresh (cloud browser, read only: never sign in,
register, add to cart or join a waitlist). Each reading is one row in `data/busy_log.csv`;
`python3 tools/build_busy.py` turns them into the labels on icetimes.ca.

## Where the numbers are

Only sessions with a real capacity count. Skip goalie sessions, and skip walk-in skates that
show a placeholder like "500 spots left" (Delta).

| Source (`source` column) | Page | What it shows |
|---|---|---|
| surrey | Drop In Hockey list: calendarId `7333623a-774c-4e63-aaac-b85a2cfbd17d` · Drop In Skating list: `5b599b6d-d54f-43c1-b86a-e962d9bf107b` (cityofsurrey.perfectmind.com/23615, widgetId `b4059e75-9755-401f-a7b5-d7c75361420d`) | "N spots left", FULL / Waitlist = 0 |
| richmond | Richmond Ice Centre: calendarId `8bd697eb-ee1e-4067-b6bb-be1901a7753d` · Minoru Arenas: `5bc32e4a-6607-47f5-8513-53b2dbc4f83e` (richmondcity.perfectmind.com/23650, widgetId `15f6af07-39c5-473e-b053-96653f77a406`) | "N spots left", Full = 0 |
| delta | Arena Drop-In calendar `c9b7ca71-56dc-43e3-aec7-d976239a5660` (hockey sessions only; skates show 500) | "N spots left" |
| portmoody | Drop-in Ice Sports calendar `da287199-756a-422e-8fbc-b2e5063b77f8` | "N spots left" |
| canlan | DaySmart `event-registration?date=YYYY-MM-DD&facility_ids=1|2|8` (no JSON API) | "x/N Registered" |

## How to record

- One row per session that matches a SNAPSHOT row (same rink, day, start): use SNAPSHOT's rink and type.
- `spots_left` for city lists; `registered` + `capacity` for Canlan.
- `mins_before` = minutes from the reading to the session start. Readings of sessions later in the
  week are useful: a session already FULL days ahead counts toward "Often fills up".
- Write with Python's `csv` module.

## Labels (tools/build_busy.py)

- Readings 0–240 min before the start, on 3+ dates → quiet (<40% full) / moderate / busy (80%+).
- Seen full before the start on 2+ dates → "Often fills up · book early".

## Richmond Olympic Oval (added Nov 26, 2026)
- Drop-in ice list: https://richmondoval.ca/drop_ins/drop-in-ice/ (Mindbody widget inside the page; shows 7 days, booking opens 8 pm 7 days ahead).
- Read-only: click each day in the widget and note Drop In Stick and Puck / Drop In Public Skating times. Never press Register or sign in.
- The Oval's times change week to week: each refresh, replace the three-or-so "Richmond Olympic Oval" rows in SNAPSHOT with the coming week's sessions.
