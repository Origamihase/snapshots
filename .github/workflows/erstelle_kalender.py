#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erstellt eine statische Wochenübersicht (Mo–Fr) als HTML aus einer ICS-Quelle.

- Zielauflösung: 1920×1080 (Full-HD TV)
- Reines HTML + CSS, kein JavaScript
- Performance: ein eingebetteter CSS-Block, Systemschriften
- Aktueller Tag: dezente grüne Umrandung
- Fußzeile: steht immer am Seitenende (Sticky-Footer)
- Branding: Kopfzeilen-Grün fest im Code

Voraussetzung: Environment-Variable ICS_URL mit der öffentlich erreichbaren ICS-Datei.
Ausgabe: public/calendar/index.html
"""

from __future__ import annotations

import os
import sys
import html
import requests
from icalendar import Calendar
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List, Set

OUTPUT_HTML_FILE = "public/calendar/index.html"


# ----------------------------- Zeit-Helfer -----------------------------

def to_local(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """Normalisiert ICS-Daten nach lokaler Zeit (Europe/Vienna)."""
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        return datetime.combine(dt_raw, time.min, tzinfo=tz_local)
    if isinstance(dt_raw, datetime):
        if dt_raw.tzinfo is None:
            return dt_raw.replace(tzinfo=tz_local).astimezone(tz_local)
        return dt_raw.astimezone(tz_local)
    return datetime.now(tz_local)


def is_all_day_component(component) -> bool:
    dtstart = component.get("dtstart")
    if not dtstart:
        return False
    v = dtstart.dt
    return isinstance(v, date) and not isinstance(v, datetime)


# ----------------------- Event in Wochenstruktur schreiben -----------------------

def add_event_local(
    week_events: Dict[date, List[Dict[str, Any]]],
    component,
    start_local: datetime,
    end_local: datetime,
    summary: str,
    week_days_local: Set[date],
) -> None:
    """Fügt ein (ggf. mehrtägiges) Ereignis pro betroffenen Tag ein."""
    all_day = is_all_day_component(component)

    # DTEND exklusiv: 00:00 + Dauer > 0 -> letzter voller Tag ist der Vortag
    loop_end_date = end_local.date()
    if (all_day or end_local.time() == time.min) and end_local > start_local:
        loop_end_date -= timedelta(days=1)

    same_day = (start_local.date() == end_local.date())
    ends_midnight_next = (end_local.time() == time.min and end_local.date() > start_local.date())

    current = start_local.date()
    while current <= loop_end_date:
        if current in week_days_local:
            if all_day:
                time_str = "Ganztägig"
                is_all = True
            else:
                if same_day:
                    time_str = f"{start_local:%H:%M}–{end_local:%H:%M}"
                elif ends_midnight_next and current == start_local.date():
                    time_str = "Ganztägig" if start_local.time() == time.min else f"{start_local:%H:%M}–00:00"
                elif current == start_local.date():
                    time_str = f"Start: {start_local:%H:%M}"
                elif current == loop_end_date and end_local.time() > time.min:
                    time_str = f"Ende: {end_local:%H:%M}"
                else:
                    time_str = "Ganztägig"
                is_all = (time_str == "Ganztägig")

            week_events[current].append({
                "summary": summary,
                "time": time_str,
                "is_all_day": is_all,
                "start_time": start_local,
            })
        current += timedelta(days=1)


# ------------------------------- HTML-Rendering -------------------------------

def render_html(
    week_events: Dict[date, List[Dict[str, Any]]],
    monday_local: date,
    friday_local: date,
    now_local_dt: datetime,
) -> str:
    calendar_week = now_local_dt.isocalendar()[1]
    tz_vienna = now_local_dt.tzinfo  # type: ignore
    timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")  # type: ignore

    def fmt_short(d: date) -> str:
        return d.strftime("%d.%m.")

    date_range_str = f"{fmt_short(monday_local)}–{fmt_short(friday_local)}"
    today_local_date = now_local_dt.date()
    days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]

    parts: List[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1920, initial-scale=1">
<title>Wochenplan</title>
<style>
:root {{
  --bg: #f5f6f8;
  --card: #ffffff;
  --text: #1f2937;
  --muted: #6b7280;
  --border: #e5e7eb;
  --radius: 12px;
  --brand: #3f6f3a; --brand2: #3f6f3a;
  --accent: #4f9f5a; --accent-soft: #eaf6ee;
}}
* {{ box-sizing: border-box; }}
html, body {{ height: 100%; }}
body {{ margin:0; background:var(--bg); color:var(--text);
       font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial;
       display:flex; flex-direction:column; min-height:100vh; }}
header.topbar {{ background:linear-gradient(135deg,var(--brand),var(--brand2)); color:#fff; padding:12px 20px; }}
.topbar-inner {{ display:flex; align-items:center; gap:14px; }}
.logo {{ background:#fff; border-radius:10px; padding:6px; display:flex; align-items:center; justify-content:center; }}
.logo img {{ width:28px; height:28px; display:block; }}
.title {{ font-weight:700; font-size:22px; letter-spacing:.2px; }}
.sub {{ font-size:13px; opacity:.95; }}
main.container {{ padding:16px 20px 8px; flex:1; }}
.grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; }}
.day {{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
       box-shadow:0 6px 18px rgba(0,0,0,.06); min-height:160px; display:flex; flex-direction:column; }}
.day-header {{ padding:10px 12px; border-bottom:1px solid var(--border);
              display:flex; align-items:baseline; justify-content:space-between;
              background:linear-gradient(180deg,rgba(0,0,0,.02),transparent); }}
.day-name {{ font-weight:700; }}
.day-date {{ color:var(--muted); font-size:13px; }}
.day.today {{ border-color:rgba(79,159,90,.55); box-shadow:0 0 0 3px rgba(79,159,90,.14),0 6px 18px rgba(0,0,0,.06); }}
.day.today .day-header {{ background:linear-gradient(180deg,var(--accent-soft),transparent);
                         border-bottom-color:rgba(79,159,90,.35); }}
.events {{ padding:10px 12px 12px; display:grid; gap:10px; }}
.event {{ display:grid; grid-template-columns:auto 1fr; gap:10px; align-items:start; }}
.badge {{ font-weight:700; font-size:12px; padding:4px 8px; border-radius:999px;
         border:1px solid rgba(79,159,90,.35); background:var(--accent-soft); white-space:nowrap; }}
.badge.all {{ border-style:dashed; }}
.summary {{ font-size:15px; line-height:1.35; }}
.no-events {{ color:var(--muted); text-align:center; padding:18px 10px 22px; font-style:italic; }}
footer.foot {{ color:#6b7280; font-size:13px; text-align:center; padding:6px 0 12px; margin-top:auto; }}
</style>
</head>
<body>
<header class="topbar" role="banner">
  <div class="topbar-inner">
    <div class="logo" aria-hidden="true">
      <img src="https://cdn.riverty.design/logo/riverty-logomark-green.svg" alt="Riverty Logo">
    </div>
    <div>
      <div class="title">Wochenplan (KW {calendar_week})</div>
      <div class="sub">{date_range_str}</div>
    </div>
  </div>
</header>
<main class="container" role="main">
  <section class="grid" aria-label="Wochentage">""")

    for i, day_name in enumerate(days):
        current_date = monday_local + timedelta(days=i)
        events = week_events.get(current_date, [])
        events.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))
        is_today_cls = " today" if current_date == today_local_date else ""
        parts.append(
            f'<article class="day{is_today_cls}" aria-labelledby="d{i}-label">'
            f'<div class="day-header"><div id="d{i}-label" class="day-name">{day_name}</div>'
            f'<div class="day-date">{current_date.strftime("%d.%m.")}</div></div>'
            f'<div class="events">'
        )
        if not events:
            parts.append('<div class="no-events">–</div>')
        else:
            for ev in events:
                badge_cls = "badge all" if ev["is_all_day"] else "badge"
                parts.append(
                    f'<div class="event"><div class="{badge_cls}">{ev["time"]}</div>'
                    f'<div class="summary">{ev["summary"]}</div></div>'
                )
        parts.append("</div></article>")

    parts.append(f"</section></main><footer class=\"foot\" role=\"contentinfo\">Kalender zuletzt aktualisiert am {timestamp_vienna}</footer></body></html>")
    return "".join(parts)


# ------------------------------------ Hauptlogik -------------------------------------

def erstelle_kalender_html() -> None:
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")

    try:
        response = requests.get(ics_url, timeout=30)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)  # Bytes, nicht .text
    except Exception as e:
        print(f"Fehler beim Herunterladen/Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    tz_vienna = ZoneInfo("Europe/Vienna")
    now_local = datetime.now(tz_vienna)

    # Woche in lokaler Zeit (Mo 00:00 – Fr 23:59:59)
    start_of_week_local_dt = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_local.weekday())
    end_of_week_local_dt = start_of_week_local_dt + timedelta(days=4, hours=23, minutes=59, seconds=59)

    monday_local = start_of_week_local_dt.date()
    friday_local = (start_of_week_local_dt + timedelta(days=4)).date()

    # Zielstruktur
    week_days_local: Set[date] = {monday_local + timedelta(days=i) for i in range(5)}
    week_events: Dict[date, List[Dict[str, Any]]] = {d: [] for d in week_days_local}

    # Verarbeitung
    for component in cal.walk("VEVENT"):
        # Abgesagte Events optional ignorieren
        if str(component.get("status", "")).upper() == "CANCELLED":
            continue

        summary_str = ""
        try:
            summary_str = html.escape(str(component.get("summary") or "Ohne Titel"))

            # Start/Ende (lokal)
            dtstart_raw = component.get("dtstart").dt
            start_local = to_local(dtstart_raw, tz_vienna)

            dtend_prop = component.get("dtend")
            duration_prop = component.get("duration")

            if not dtend_prop and duration_prop:
                end_local = start_local + duration_prop.dt
            else:
                dtend_raw = dtend_prop.dt if dtend_prop else dtstart_raw
                end_local = to_local(dtend_raw, tz_vienna)

            duration = end_local - start_local
            pad = duration if duration > timedelta(0) else timedelta(0)

            # Wiederholungen (RRULE)
            rrule_prop = component.get("rrule")
            if rrule_prop:
                # EXDATE sammeln
                exdates_local: Set[datetime] = set()
                ex_prop = component.get("exdate")
                ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
                for ex in ex_list:
                    for d in ex.dts:
                        exdates_local.add(to_local(d.dt, tz_vienna))

                rule = rrulestr(rrule_prop.to_ical().decode(), dtstart=start_local)

                search_start = start_of_week_local_dt - pad
                search_end = end_of_week_local_dt

                for occ_start_local in rule.between(search_start, search_end, inc=True):
                    if occ_start_local in exdates_local:
                        continue
                    add_event_local(week_events, component, occ_start_local, occ_start_local + duration, summary_str, week_days_local)
            else:
                # Einzeltermin
                add_event_local(week_events, component, start_local, end_local, summary_str, week_days_local)

            # RDATE (zusätzliche Einzeltermine)
            rdate_prop = component.get("rdate")
            rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
            for r in rdate_list:
                for d in r.dts:
                    r_local = to_local(d.dt, tz_vienna)
                    add_event_local(week_events, component, r_local, r_local + duration, summary_str, week_days_local)

        except Exception as e:
            print(f"Fehler beim Verarbeiten eines Termins ('{summary_str}'): {e}", file=sys.stderr)

    # HTML schreiben
    html_str = render_html(week_events, monday_local, friday_local, now_local)
    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_str)

    print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")


if __name__ == "__main__":
    erstelle_kalender_html()
