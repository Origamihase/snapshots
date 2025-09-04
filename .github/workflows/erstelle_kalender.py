#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erstellt eine statische Wochenübersicht (Mo–Fr) als HTML aus einer ICS-Quelle.

- Zielauflösung: 1920×1080 (Full-HD TV)
- Reines HTML + CSS, kein JavaScript
- Performance: ein eingebetteter CSS-Block, Systemschriften
- Aktueller Tag: dezente grüne Umrandung
- Fußzeile: steht immer am Seitenende (Sticky-Footer)
- Branding: Grüntöne im CSS

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
from datetime import datetime, date, time, timezone, timedelta
from typing import Any, Dict, List, Set, Union

OUTPUT_HTML_FILE = "public/calendar/index.html"


def to_utc_from_prop(dt_raw: Union[date, datetime], tz_local: ZoneInfo) -> datetime:
    """
    Normalisiert ICS-Zeitwerte zuverlässig nach UTC.
    - Reines Datum (Ganztägig) wird als lokale Mitternacht interpretiert.
    - Naive Datetimes gelten als lokale Zeit.
    - Aware Datetimes werden direkt nach UTC umgerechnet.
    """
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        return datetime.combine(dt_raw, time.min, tzinfo=tz_local).astimezone(timezone.utc)
    if getattr(dt_raw, "tzinfo", None):
        return dt_raw.astimezone(timezone.utc)
    return dt_raw.replace(tzinfo=tz_local).astimezone(timezone.utc)


def add_event_to_week(
    week_events: Dict[date, List[Dict[str, Any]]],
    component: Any,
    start_dt: datetime,
    end_dt: datetime,
    summary: str,
    tz_vienna: ZoneInfo,
    week_start_date: date,
) -> None:
    """
    Fügt ein Ereignis in die Wochentage (Mo–Fr) ein, mit korrekter Darstellung:
    - Ein-Tages-Zeittermin: "HH:MM–HH:MM" (oder "HH:MM" wenn Dauer 0)
    - Mehrtägig (Zeit): erster Tag "Start: HH:MM" (oder "HH:MM–00:00" falls Mitternacht-Fall),
                        Mitteltage "Ganztägig",
                        letzter Tag "Ende: HH:MM" (nur wenn Endzeit > 00:00)
    - Ganztägig: auf allen betroffenen Tagen "Ganztägig"
    """
    start_local = start_dt.astimezone(tz_vienna)
    end_local = end_dt.astimezone(tz_vienna)

    is_all_day = isinstance(component.get("dtstart").dt, date) and not isinstance(component.get("dtstart").dt, datetime)

    # DTEND-Exklusivität berücksichtigen:
    # - Für Ganztägig ist dtend gewöhnlich EXKLUSIV; letzter angezeigter Tag ist end_local - 1 Tag.
    # - Für Zeit-Events, die exakt um 00:00 am Folgetag enden, ebenso einen Tag abziehen.
    loop_end_date = end_local.date()
    if is_all_day or (end_local.time() == time.min and end_local.date() > start_local.date()):
        loop_end_date -= timedelta(days=1)

    same_day = (start_local.date() == end_local.date())
    ends_midnight_next = (end_local.time() == time.min and end_local.date() > start_local.date())

    current_date = start_local.date()
    week_end_date = week_start_date + timedelta(days=4)  # Freitag

    while current_date <= loop_end_date:
        if week_start_date <= current_date <= week_end_date:
            if is_all_day:
                time_str = "Ganztägig"
                mark_all_day = True
            elif same_day:
                # Ein-Tages-Zeittermin
                if start_local == end_local:
                    time_str = start_local.strftime("%H:%M")  # Punkttermin
                else:
                    time_str = f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                mark_all_day = False
            elif current_date == start_local.date():
                if ends_midnight_next:
                    # z.B. 10:00 bis exakt 00:00 Folgetag -> "HH:MM–00:00"
                    # Falls auch Start 00:00: ganzer Tag
                    if start_local.time() == time.min:
                        time_str = "Ganztägig"
                        mark_all_day = True
                    else:
                        time_str = f"{start_local.strftime('%H:%M')}–00:00"
                        mark_all_day = False
                else:
                    time_str = f"Start: {start_local.strftime('%H:%M')}"
                    mark_all_day = False
            elif current_date == loop_end_date and end_local.time() > time.min:
                time_str = f"Ende: {end_local.strftime('%H:%M')}"
                mark_all_day = False
            else:
                time_str = "Ganztägig"
                mark_all_day = True

            week_events[current_date].append({
                "summary": summary,
                "time": time_str,
                "is_all_day": mark_all_day,
                "start_time": start_dt,
            })

        current_date += timedelta(days=1)


def generate_html(
    week_events: Dict[date, List[Dict[str, Any]]],
    start_of_week_local: datetime,
    now_vienna: datetime,
    tz_vienna: ZoneInfo,
) -> None:
    """Erzeugt die HTML-Ausgabe und schreibt sie in OUTPUT_HTML_FILE."""
    calendar_week = start_of_week_local.isocalendar()[1]
    monday = start_of_week_local.date()
    friday = monday + timedelta(days=4)
    date_range_str = f"{monday.strftime('%d.%m.')}–{friday.strftime('%d.%m.%Y')}"

    html_parts: List[str] = [f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=1920, initial-scale=1"><title>Wochenplan</title><style>
:root {{
    --main-green: #4d824d; --light-green: #6aa84f; --dark-green: #386638;
    --text-color: #1f2937; --light-text-color: #fff; --bg-color: #f5f6f8;
    --container-bg: #fff; --border-color: #e5e7eb; --header-bg: #fdfdfd;
}}
* {{ box-sizing: border-box; }}
html, body {{ height: 100%; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; display: flex; flex-direction: column; min-height: 100vh; }}
.top-bar {{ background: linear-gradient(135deg, var(--main-green), var(--dark-green)); padding: 14px 20px; color: var(--light-text-color); text-align: center; font-size: 22px; font-weight: 700; letter-spacing: .2px; }}
.subline {{ font-size: 13px; opacity: .95; }}
.container {{ max-width: 95%; margin: 16px auto; background: var(--container-bg); padding: 16px 20px; box-shadow: 0 6px 18px rgba(0,0,0,.06); border-radius: 8px; flex: 1; }}
.week-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }}
.day-column {{ background-color: var(--header-bg); border: 1px solid var(--border-color); border-radius: 8px; min-height: 150px; display: flex; flex-direction: column; }}
.day-header {{ padding: 10px 12px; border-bottom: 1px solid var(--border-color); display: flex; align-items: baseline; justify-content: space-between; background: linear-gradient(180deg, rgba(0,0,0,.02), transparent); }}
.day-title {{ font-weight: 700; }}
.day-date {{ font-size: 13px; color: #6b7280; }}
.day-column.today {{ border-color: rgba(79,159,90,.55); box-shadow: 0 0 0 3px rgba(79,159,90,.14), 0 6px 18px rgba(0,0,0,.06); }}
.day-column.today .day-header {{ background: linear-gradient(180deg, #eaf6ee, transparent); border-bottom-color: rgba(79,159,90,.35); }}
.events {{ padding: 10px 12px 12px; display: grid; gap: 10px; }}
.event {{ margin: 0; padding: 8px; background: #fff; border-radius: 6px; border: 1px solid var(--border-color); display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; }}
.event.all-day {{ border-left: 4px solid var(--dark-green); }}
.event:not(.all-day) {{ border-left: 4px solid var(--light-green); }}
.event-time {{ font-weight: 700; font-size: 12px; padding: 4px 8px; border-radius: 999px; border: 1px solid rgba(79,159,90,.35); background: #eaf6ee; white-space: nowrap; }}
.event-summary {{ font-size: 15px; line-height: 1.35; }}
.no-events {{ color: #6b7280; text-align: center; padding: 18px 10px 22px; font-style: italic; }}
.footer {{ color: #6b7280; font-size: 13px; text-align: center; padding: 6px 0 12px; margin-top: auto; }}
</style></head><body>
<div class="top-bar">Wochenplan (KW {calendar_week})<div class="subline">{date_range_str}</div></div>
<div class="container">
<div class="week-grid">"""]

    for i, day_name in enumerate(["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]):
        current_date_local = monday + timedelta(days=i)
        events_for_day = sorted(
            week_events.get(current_date_local, []),
            key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower())
        )
        is_today_cls = " today" if current_date_local == now_vienna.date() else ""

        html_parts.append(
            f'<div class="day-column{is_today_cls}">'
            f'<div class="day-header"><div class="day-title">{day_name}</div>'
            f'<div class="day-date">{current_date_local.strftime("%d.%m.")}</div></div>'
            f'<div class="events">'
        )

        if not events_for_day:
            html_parts.append('<div class="no-events">–</div>')
        else:
            for ev in events_for_day:
                event_class = "event all-day" if ev["is_all_day"] else "event"
                html_parts.append(
                    f'<div class="{event_class}"><div class="event-time">{ev["time"]}</div>'
                    f'<div class="event-summary">{ev["summary"]}</div></div>'
                )

        html_parts.append('</div></div>')  # </events></day-column>

    timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")
    html_parts.append(f'</div><div class="footer">Zuletzt aktualisiert am {timestamp_vienna}</div></div></body></html>')

    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))


def erstelle_kalender_html() -> None:
    """Liest die ICS-URL aus der Umgebung, parst die ICS und schreibt die Wochenübersicht als HTML-Datei."""
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")

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

        # Wochenfenster (lokal) bestimmen und in UTC für RRULE-Suche abbilden
        start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_vienna.weekday())
        end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)
        start_of_week_dt = start_of_week_local.astimezone(timezone.utc)
        end_of_week_dt = end_of_week_local.astimezone(timezone.utc)

        # Buckets für Mo–Fr (lokale Daten als Schlüssel)
        week_events: Dict[date, List[Dict[str, Any]]] = {
            (start_of_week_local.date() + timedelta(days=i)): [] for i in range(5)
        }

        # RECURRENCE-ID Overrides vorbereiten (Ausnahmen einzelner Vorkommen)
        overrides: Dict[str, Dict[datetime, Any]] = {}
        for component in cal.walk("VEVENT"):
            uid = str(component.get("uid"))
            recurrence_id_prop = component.get("recurrence-id")
            if uid and recurrence_id_prop:
                overrides.setdefault(uid, {})
                recurrence_id_utc = to_utc_from_prop(recurrence_id_prop.dt, tz_vienna)
                overrides[uid][recurrence_id_utc] = component

        # Alle Events verarbeiten (Master und Einzeltermine)
        for component in cal.walk("VEVENT"):
            # Übersprung: Override selbst wird im jeweiligen Master beim Auftreten ersetzt
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

            rrule_prop = component.get("rrule")
            if rrule_prop:
                # EXDATE robust einlesen (kann Liste oder einzelnes Element sein)
                exdates: Set[datetime] = set()
                ex_prop = component.get("exdate")
                ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
                for ex in ex_list:
                    for d in ex.dts:
                        exdates.add(to_utc_from_prop(d.dt, tz_vienna))

                # RRULE auswerten (dtstart=UTC)
                rrule = rrulestr(rrule_prop.to_ical().decode("utf-8"), dtstart=dtstart_utc)

                # Suchtoleranz: bei >0 Dauer nach links erweitern (Overnights)
                pad = duration if duration > timedelta(0) else timedelta(0)
                search_start_dt = start_of_week_dt - pad

                for occ_start in rrule.between(search_start_dt, end_of_week_dt, inc=True):
                    if occ_start in exdates:
                        continue

                    # RECURRENCE-ID Override?
                    uid = str(component.get("uid"))
                    effective_component = overrides.get(uid, {}).get(occ_start, component)

                    # (Optional) Filter für "gelöschte" Organisatoren – domain-spezifisch
                    if "Ehemaliger Benutzer (Deleted)" in str(effective_component.get("organizer", "")):
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
                # Einzeltermin (ohne RRULE)
                add_event_to_week(week_events, component, dtstart_utc, dtend_utc, summary_str, tz_vienna, start_of_week_local.date())

            # RDATE (zusätzliche Einzelvorkommen) verarbeiten
            rdate_prop = component.get("rdate")
            rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
            for r in rdate_list:
                for d in r.dts:
                    r_dt_utc = to_utc_from_prop(d.dt, tz_vienna)
                    add_event_to_week(week_events, component, r_dt_utc, r_dt_utc + duration, summary_str, tz_vienna, start_of_week_local.date())

        # HTML erzeugen
        generate_html(week_events, start_of_week_local, now_vienna, tz_vienna)
        print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")

    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    erstelle_kalender_html()
