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
from typing import Any, Dict, List
from datetime import datetime, date, time, timezone, timedelta

import requests
from icalendar import Calendar
from dateutil.rrule import rrulestr
from zoneinfo import ZoneInfo

OUTPUT_HTML_FILE = "public/calendar/index.html"


# ----------------------------- Zeit-Helfer ---------------------------------- #

def to_utc(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """
    Normalisiert ICS-Zeitwerte nach UTC.
    - VALUE=DATE (reines Datum): als lokale Mitternacht interpretieren
    - naive datetime: als lokale Zeit interpretieren
    - timezone-aware datetime: nach UTC konvertieren
    """
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        return datetime.combine(dt_raw, time.min, tzinfo=tz_local).astimezone(timezone.utc)
    if getattr(dt_raw, "tzinfo", None):
        return dt_raw.astimezone(timezone.utc)
    return dt_raw.replace(tzinfo=tz_local).astimezone(timezone.utc)


# ---------------------------- Rendering-Logik -------------------------------- #

def add_event_to_week(
    week_events: Dict[date, List[Dict[str, Any]]],
    component: Any,
    start_dt_utc: datetime,
    end_dt_utc: datetime,
    summary: str,
    tz_vienna: ZoneInfo,
    min_week_local: date,
    max_week_local: date,
) -> None:
    """
    Fügt ein (ggf. mehrtägiges) Ereignis den betroffenen Tagen in week_events hinzu.
    week_events ist nach lokalen (Wien) Datumswerten indexiert.
    """
    start_local = start_dt_utc.astimezone(tz_vienna)
    end_local = end_dt_utc.astimezone(tz_vienna)
    duration = end_dt_utc - start_dt_utc

    # All-Day erkennen (VALUE=DATE bei DTSTART)
    is_all_day_event = (
        isinstance(component.get("dtstart").dt, date)
        and not isinstance(component.get("dtstart").dt, datetime)
    )

    # DTEND ist exklusiv -> bei 00:00 und Dauer > 0 letzten Tag um 1 zurück
    loop_end_date = end_local.date()
    if is_all_day_event:
        loop_end_date -= timedelta(days=1)
    elif end_local.time() == time.min and duration > timedelta(0):
        loop_end_date -= timedelta(days=1)

    same_day = (start_local.date() == end_local.date())
    ends_midnight_next = (
        end_local.time() == time.min
        and duration > timedelta(0)
        and end_local.date() > start_local.date()
    )

    current_date = start_local.date()
    while current_date <= loop_end_date:
        if min_week_local <= current_date <= max_week_local:
            # Badge-Text bestimmen
            if is_all_day_event:
                time_str = "Ganztägig"
            elif same_day:
                time_str = f"{start_local:%H:%M}–{end_local:%H:%M}"
            elif ends_midnight_next and current_date == start_local.date():
                # z. B. 20:00–00:00 auf dem Starttag anzeigen
                time_str = f"{start_local:%H:%M}–00:00"
            elif current_date == start_local.date():
                time_str = f"Start: {start_local:%H:%M}"
            elif current_date == loop_end_date and end_local.time() > time.min:
                time_str = f"Ende: {end_local:%H:%M}"
            else:
                time_str = "Ganztägig"

            week_events[current_date].append({
                "summary": summary,
                "time": time_str,
                "is_all_day": (time_str == "Ganztägig"),
                "start_time": start_dt_utc,   # für Sortierung
            })
        current_date += timedelta(days=1)


# --------------------------------- Main ------------------------------------- #

def erstelle_kalender_html() -> None:
    """Liest die ICS-URL aus der Umgebung und schreibt die Wochenübersicht als HTML-Datei."""
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")

    try:
        response = requests.get(ics_url, timeout=30)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)  # Bytes statt Text -> stabiler
    except Exception as e:
        print(f"Fehler beim Herunterladen/Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    tz_vienna = ZoneInfo("Europe/Vienna")
    now_vienna = datetime.now(tz_vienna)

    # Wochenfenster in Wiener Lokalzeit bestimmen
    start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_vienna.weekday())
    end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)
    start_of_week_dt = start_of_week_local.astimezone(timezone.utc)
    end_of_week_dt = end_of_week_local.astimezone(timezone.utc)

    monday_vie = start_of_week_local.date()
    friday_vie = end_of_week_local.date()

    # week_events nach lokalem Datum (Wien) indexieren
    week_events: Dict[date, List[Dict[str, Any]]] = {
        (monday_vie + timedelta(days=i)): [] for i in range(5)
    }
    min_week_local = monday_vie
    max_week_local = friday_vie

    # ------------------------------ ICS verarbeiten -------------------------- #

    for component in cal.walk("VEVENT"):
        summary_raw = component.get("summary")
        summary_str = html.escape(str(summary_raw) if summary_raw is not None else "Ohne Titel")

        # DTSTART/DTEND normalisieren
        dtstart_raw = component.get("dtstart").dt
        dtend_prop = component.get("dtend")
        dtend_raw = dtend_prop.dt if dtend_prop else dtstart_raw

        dtstart = to_utc(dtstart_raw, tz_vienna)
        dtend = to_utc(dtend_raw, tz_vienna)
        duration = dtend - dtstart

        # Wiederholungen (RRULE) + Ausnahmen (EXDATE)
        rrule_prop = component.get("rrule")
        if rrule_prop:
            # EXDATE kann mehrfach vorkommen, Liste oder Einzelwert
            exdates: set[datetime] = set()
            ex_prop = component.get("exdate")
            ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
            for ex in ex_list:
                for d in ex.dts:
                    exdates.add(to_utc(d.dt, tz_vienna))

            rrule = rrulestr(rrule_prop.to_ical().decode(), dtstart=dtstart)

            # leicht erweitertes Suchfenster (Padding = Dauer), um Randtreffer mitzunehmen
            pad = duration if duration > timedelta(0) else timedelta(0)
            search_start = start_of_week_dt - pad
            search_end = end_of_week_dt

            for occ_start in rrule.between(search_start, search_end, inc=True):
                if occ_start in exdates:
                    continue
                add_event_to_week(
                    week_events,
                    component,
                    occ_start,
                    occ_start + duration,
                    summary_str,
                    tz_vienna,
                    min_week_local,
                    max_week_local,
                )
        else:
            # Einzeltermin
            add_event_to_week(
                week_events,
                component,
                dtstart,
                dtend,
                summary_str,
                tz_vienna,
                min_week_local,
                max_week_local,
            )

        # Zusätzliche Einzel-Vorkommen (RDATE)
        rdate_prop = component.get("rdate")
        rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
        for r in rdate_list:
            for d in r.dts:
                r_dt = to_utc(d.dt, tz_vienna)
                add_event_to_week(
                    week_events,
                    component,
                    r_dt,
                    r_dt + duration,
                    summary_str,
                    tz_vienna,
                    min_week_local,
                    max_week_local,
                )

    # ----------------------------- HTML schreiben ---------------------------- #

    calendar_week = start_of_week_local.isocalendar()[1]
    timestamp_vienna = now_vienna.strftime("%d.%m.%Y um %H:%M:%S Uhr")

    def fmt_short(d: date) -> str:
        return d.strftime("%d.%m.")

    date_range_str = f"{fmt_short(monday_vie)}–{fmt_short(friday_vie)}"

    html_parts: List[str] = []
    html_parts.append(f"""<!DOCTYPE html>
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

  --brand: #3f6f3a;      /* festes Kopfzeilen-Grün */
  --brand2: #3f6f3a;     /* identisch -> kein sichtbarer Verlauf */
  --accent: #4f9f5a;     /* Akzentgrün für Badges/Hervorhebung */
  --accent-soft: #eaf6ee;
}}

* {{ box-sizing: border-box; }}
html, body {{ height: 100%; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial;
  display: flex;                 /* Sticky-Footer */
  flex-direction: column;
  min-height: 100vh;
}}

header.topbar {{
  background: linear-gradient(135deg, var(--brand), var(--brand2));
  color: #fff;
  padding: 12px 20px;
}}
.topbar-inner {{ display: flex; align-items: center; gap: 14px; }}
.logo {{
  background: #fff;
  border-radius: 10px;
  padding: 6px;
  display: flex; align-items: center; justify-content: center;
}}
.logo img {{ width: 28px; height: 28px; display: block; }}
.title {{ font-weight: 700; font-size: 22px; letter-spacing: .2px; }}
.sub {{ font-size: 13px; opacity: .95; }}

main.container {{ padding: 16px 20px 8px; flex: 1; }}  /* füllt den verfügbaren Raum */

.grid {{
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}}

.day {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 6px 18px rgba(0,0,0,.06);
  min-height: 160px;
  display: flex; flex-direction: column;
}}
.day-header {{
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: baseline; justify-content: space-between;
  background: linear-gradient(180deg, rgba(0,0,0,.02), transparent);
}}
.day-name {{ font-weight: 700; }}
.day-date {{ color: var(--muted); font-size: 13px; }}

/* HEUTE: grüne Umrandung + subtiler „Ring“ */
.day.today {{
  border-color: rgba(79,159,90,.55);
  box-shadow: 0 0 0 3px rgba(79,159,90,.14), 0 6px 18px rgba(0,0,0,.06);
}}
.day.today .day-header {{
  background: linear-gradient(180deg, var(--accent-soft), transparent);
  border-bottom-color: rgba(79,159,90,.35);
}}

.events {{ padding: 10px 12px 12px; display: grid; gap: 10px; }}
.event {{ display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; }}

.badge {{
  font-weight: 700; font-size: 12px; padding: 4px 8px; border-radius: 999px;
  border: 1px solid rgba(79,159,90,.35); background: var(--accent-soft);
  white-space: nowrap;
}}
.badge.all {{ border-style: dashed; }}
.summary {{ font-size: 15px; line-height: 1.35; }}

.no-events {{ color: var(--muted); text-align: center; padding: 18px 10px 22px; font-style: italic; }}

footer.foot {{
  color: #6b7280; font-size: 13px; text-align: center; padding: 6px 0 12px;
  margin-top: auto;             /* garantiert: Fußzeile unten */
}}
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
  <section class="grid" aria-label="Wochentage">
""")

    day_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    for i, day_name in enumerate(day_names):
        current_date_local = monday_vie + timedelta(days=i)
        events_for_day = week_events.get(current_date_local, [])

        # Sortierung: Ganztägig zuerst, dann Startzeit, dann Titel
        events_for_day.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))

        is_today_cls = " today" if current_date_local == now_vienna.date() else ""

        html_parts.append(
            f'<article class="day{is_today_cls}" aria-labelledby="d{i}-label">'
            f'<div class="day-header"><div id="d{i}-label" class="day-name">{day_name}</div>'
            f'<div class="day-date">{current_date_local.strftime("%d.%m.")}</div></div>'
            f'<div class="events">'
        )

        if not events_for_day:
            html_parts.append('<div class="no-events">–</div>')
        else:
            for ev in events_for_day:
                badge_cls = "badge all" if ev["is_all_day"] else "badge"
                html_parts.append(
                    f'<div class="event"><div class="{badge_cls}">{ev["time"]}</div>'
                    f'<div class="summary">{ev["summary"]}</div></div>'
                )

        html_parts.append("</div></article>")

    html_parts.append(
        f"""  </section>
</main>

<footer class="foot" role="contentinfo">
  Kalender zuletzt aktualisiert am {timestamp_vienna}
</footer>
</body>
</html>"""
    )

    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

    print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")


if __name__ == "__main__":
    erstelle_kalender_html()
