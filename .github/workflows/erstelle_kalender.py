#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erstellt eine statische Wochenübersicht (Mo–Fr) als HTML aus einer ICS-Quelle.
- Logik: Korrekte Verarbeitung von Serienterminen inkl. Ausnahmen und Modifikationen
"""

from __future__ import annotations

import os
import sys
import html
import requests
from icalendar import Calendar
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr
from datetime import datetime, date, time, timezone, timedelta
from typing import Any, Dict, List

OUTPUT_HTML_FILE = "public/calendar/index.html"


def to_utc_from_prop(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """Normalisiert ICS-Zeitwerte zuverlässig nach UTC."""
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        return tz_local.localize(datetime.combine(dt_raw, time.min)).astimezone(timezone.utc)
    if getattr(dt_raw, "tzinfo", None):
        return dt_raw.astimezone(timezone.utc)
    return tz_local.localize(dt_raw).astimezone(timezone.utc)


def erstelle_kalender_html() -> None:
    """Hauptfunktion zur Erstellung des HTML-Kalenders."""
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: ICS_URL nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender...")
    try:
        response = requests.get(ics_url, timeout=30)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)
    except Exception as e:
        print(f"Fehler beim Laden/Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        tz_vienna = ZoneInfo("Europe/Vienna")
        now_vienna = datetime.now(tz_vienna)

        start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_vienna.weekday())
        end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)
        start_of_week_dt = start_of_week_local.astimezone(timezone.utc)
        end_of_week_dt = end_of_week_local.astimezone(timezone.utc)

        week_events: Dict[date, List[Dict[str, Any]]] = {(start_of_week_local.date() + timedelta(days=i)): [] for i in range(5)}

        overrides: Dict[str, Dict[datetime, Any]] = {}
        for component in cal.walk("VEVENT"):
            uid = str(component.get("uid"))
            recurrence_id_prop = component.get("recurrence-id")
            if uid and recurrence_id_prop:
                if uid not in overrides:
                    overrides[uid] = {}
                recurrence_id_utc = to_utc_from_prop(recurrence_id_prop.dt, tz_vienna)
                overrides[uid][recurrence_id_utc] = component

        for component in cal.walk("VEVENT"):
            if component.get("recurrence-id"):
                continue

            summary_str = html.escape(str(component.get("summary", "Ohne Titel")))
            dtstart_raw = component.get("dtstart").dt
            dtstart_utc = to_utc_from_prop(dtstart_raw, tz_vienna)

            dtend_prop = component.get("dtend")
            duration_prop = component.get("duration")
            if not dtend_prop and duration_prop:
                dtend_utc = dtstart_utc + duration_prop.dt
            else:
                dtend_raw = dtend_prop.dt if dtend_prop else dtstart_raw
                dtend_utc = to_utc_from_prop(dtend_raw, tz_vienna)

            duration = dtend_utc - dtstart_utc

            if "rrule" in component:
                rrule = rrulestr(component.get('rrule').to_ical().decode('utf-8'), dtstart=dtstart_utc)
                exdates = {to_utc_from_prop(d.dt, tz_vienna) for ex in component.get("exdate", []) for d in ex.dts}
                pad = duration if duration > timedelta(0) else timedelta(days=1)
                search_start = start_of_week_dt - pad

                for occ_start_utc in rrule.between(search_start, end_of_week_dt, inc=True):
                    if occ_start_utc in exdates:
                        continue

                    uid = str(component.get("uid"))
                    effective_component = overrides.get(uid, {}).get(occ_start_utc, component)

                    if 'Ehemaliger Benutzer (Deleted)' in str(effective_component.get("organizer", "")):
                        continue

                    eff_summary = html.escape(str(effective_component.get("summary", "Ohne Titel")))
                    eff_dtstart_raw = effective_component.get("dtstart").dt
                    eff_dtstart_utc = to_utc_from_prop(eff_dtstart_raw, tz_vienna)

                    eff_dtend_prop = effective_component.get("dtend")
                    eff_duration_prop = effective_component.get("duration")
                    if not eff_dtend_prop and eff_duration_prop:
                        eff_dtend_utc = eff_dtstart_utc + eff_duration_prop.dt
                    else:
                        eff_dtend_raw = eff_dtend_prop.dt if eff_dtend_prop else eff_dtstart_raw
                        eff_dtend_utc = to_utc_from_prop(eff_dtend_raw, tz_vienna)

                    add_event_to_week(week_events, effective_component, eff_dtstart_utc, eff_dtend_utc, eff_summary, tz_vienna, start_of_week_local.date())
            else:
                add_event_to_week(week_events, component, dtstart_utc, dtend_utc, summary_str, tz_vienna, start_of_week_local.date())

        generate_html(week_events, start_of_week_local, now_vienna)
        print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")

    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}", file=sys.stderr)
        sys.exit(3)


def add_event_to_week(week_events, component, start_dt, end_dt, summary, tz_vienna, week_start_date):
    start_local = start_dt.astimezone(tz_vienna)
    end_local = end_dt.astimezone(tz_vienna)
    is_all_day = isinstance(component.get("dtstart").dt, date) and not isinstance(component.get("dtstart").dt, datetime)
    loop_end_date = end_local.date()
    if is_all_day or (end_local.time() == time.min and end_local.date() > start_local.date()):
        loop_end_date -= timedelta(days=1)
    current_date = start_local.date()
    while current_date <= loop_end_date:
        if week_start_date <= current_date < week_start_date + timedelta(days=5):
            time_str = "Ganztägig" if is_all_day else f"{start_local.strftime('%H:%M')} - {end_local.strftime('%H:%M')}"
            week_events[current_date].append({"summary": summary, "time": time_str, "is_all_day": is_all_day, "start_time": start_dt})
        current_date += timedelta(days=1)


def generate_html(week_events, start_of_week_local, now_vienna):
    calendar_week = start_of_week_local.isocalendar()[1]
    date_range_str = f"{start_of_week_local.strftime('%d.%m.')}–{(start_of_week_local + timedelta(days=4)).strftime('%d.%m.%Y')}"
    
    html_parts = [f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=1920, initial-scale=1"><title>Wochenplan</title><style>
:root {{
    --main-green: #4d824d; --light-green: #6aa84f; --dark-green: #386638;
    --text-color: #333; --light-text-color: #fff; --bg-color: #f4f4f9;
    --container-bg: #fff; --border-color: #eee; --header-bg: #fdfdfd;
}}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 0; }}
.top-bar {{ background-color: var(--main-green); padding: 15px 20px; color: var(--light-text-color); text-align: center; font-size: 1.8em; font-weight: bold; margin-bottom: 20px; }}
.container {{ max-width: 95%; margin: 20px auto; background: var(--container-bg); padding: 20px; box-shadow: 0 0 15px rgba(0,0,0,0.1); border-radius: 8px; }}
.week-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
.day-column {{ background-color: var(--header-bg); border: 1px solid var(--border-color); border-radius: 5px; padding: 10px; min-height: 150px; }}
.day-header {{ text-align: center; font-weight: bold; padding-bottom: 10px; border-bottom: 2px solid var(--border-color); margin-bottom: 10px; }}
.day-header .date {{ font-size: 0.9em; color: #666; font-weight: normal; }}
.day.today .day-header {{ background-color: #eaf6ee; }}
.event {{ margin-bottom: 8px; padding: 8px; background: #f9f9f9; border-radius: 3px; }}
.event.all-day {{ border-left: 4px solid var(--dark-green); }}
.event:not(.all-day) {{ border-left: 4px solid var(--light-green); }}
.event-time {{ font-weight: bold; font-size: 0.9em; color: #555; }}
.event-summary {{ font-size: 1em; }}
.no-events {{ color: #999; text-align: center; padding-top: 20px; }}
.footer {{ text-align: center; margin-top: 20px; font-size: 0.8em; color: #777; }}
</style></head><body>
<div class="top-bar">Wochenplan (KW {calendar_week})</div>
<div class="container">
<div class="week-grid">"""]

    for i, day_name in enumerate(["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]):
        current_date_local = start_of_week_local.date() + timedelta(days=i)
        events_for_day = sorted(week_events.get(current_date_local, []), key=lambda x: (not x["is_all_day"], x["start_time"]))
        is_today_cls = " today" if current_date_local == now_vienna.date() else ""
        
        html_parts.append(f'<div class="day-column{is_today_cls}"><div class="day-header">{day_name}<div class="date">{current_date_local.strftime("%d.%m.")}</div></div>')
        if not events_for_day:
            html_parts.append('<div class="no-events">-</div>')
        else:
            for ev in events_for_day:
                event_class = "event all-day" if ev["is_all_day"] else "event"
                html_parts.append(f'<div class="{event_class}"><div class="event-time">{ev["time"]}</div><div class="event-summary">{ev["summary"]}</div></div>')
        html_parts.append('</div>')

    timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")
    html_parts.append(f'</div><div class="footer">Zuletzt aktualisiert am {timestamp_vienna}</div></div></body></html>')
    
    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

if __name__ == "__main__":
    erstelle_kalender_html()
