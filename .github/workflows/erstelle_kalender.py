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

Benötigte Pakete: requests, icalendar, python-dateutil (rrule); Python >= 3.9 (zoneinfo).
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
from typing import Any, Dict, List, Set, Tuple

OUTPUT_HTML_FILE = "public/calendar/index.html"


def erstelle_kalender_html() -> None:
    """Liest die ICS-URL aus der Umgebung und schreibt die Wochenübersicht als HTML-Datei."""
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")

    # 1) ICS laden
    try:
        response = requests.get(ics_url, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Herunterladen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    # 2) ICS parsen
    try:
        cal = Calendar.from_ical(response.content)
    except Exception as e:
        print(f"Fehler beim Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    # 3) Verarbeitung + HTML-Erzeugung
    try:
        tz_vienna = ZoneInfo("Europe/Vienna")
        now_vienna = datetime.now(tz_vienna)

        # Woche in lokaler Zeit bestimmen (Montag 00:00 bis Freitag 23:59:59)
        start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=now_vienna.weekday()
        )
        end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)

        # Für Wiederholungs-Suche in UTC umrechnen
        start_of_week_dt = start_of_week_local.astimezone(timezone.utc)
        end_of_week_dt = end_of_week_local.astimezone(timezone.utc)

        monday_vie = start_of_week_local.date()
        friday_vie = (start_of_week_local + timedelta(days=4)).date()

        # Buckets pro lokalem Datum
        week_events: Dict[date, List[Dict[str, Any]]] = {
            (start_of_week_local.date() + timedelta(days=i)): [] for i in range(5)
        }
        # Deduplizierung pro Tag (z. B. bei RRULE + RDATE)
        seen_per_day: Dict[date, Set[Tuple[str, str, datetime]]] = {d: set() for d in week_events}

        min_week_local = start_of_week_local.date()
        max_week_local = (start_of_week_local + timedelta(days=4)).date()

        def to_utc_from_prop(dt_raw: date | datetime) -> datetime:
            """
            Normalisiert ICS-Zeitwerte nach UTC:
              - DATE → in Wien (00:00) kombinieren, dann nach UTC
              - DATETIME mit TZ → nach UTC
              - DATETIME ohne TZ → Wien annehmen, dann nach UTC
            """
            if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
                return datetime.combine(dt_raw, time.min, tzinfo=tz_vienna).astimezone(timezone.utc)
            if getattr(dt_raw, "tzinfo", None):
                return dt_raw.astimezone(timezone.utc)
            return dt_raw.replace(tzinfo=tz_vienna).astimezone(timezone.utc)

        def add_event_to_week(component, start_dt: datetime, end_dt: datetime,
                              summary: str, duration: timedelta) -> None:
            """
            Fügt ein Ereignis allen betroffenen lokalen Tagen in week_events hinzu.
            start_dt/end_dt sind UTC; Anzeige- und Tageslogik erfolgen in Wien-Zeit.
            """
            start_local = start_dt.astimezone(tz_vienna)
            end_local = end_dt.astimezone(tz_vienna)

            # Erkennen, ob das Original-Event ganztägig (DATE) ist
            is_all_day_event = (
                isinstance(component.get("dtstart").dt, date)
                and not isinstance(component.get("dtstart").dt, datetime)
            )

            # DTEND ist exklusiv:
            # - Ganztägig: EXKLUSIV → letzten angezeigten Tag um 1 reduzieren
            # - Zeitbasiert: endet exakt 00:00 und Dauer > 0 → ebenfalls -1 Tag
            loop_end_date = end_local.date()
            if is_all_day_event or (end_local.time() == time.min and duration > timedelta(0)):
                loop_end_date -= timedelta(days=1)

            same_day = (start_local.date() == end_local.date())
            ends_midnight_next = (
                end_local.time() == time.min and duration > timedelta(0) and end_local.date() > start_local.date()
            )

            current_date = start_local.date()
            while current_date <= loop_end_date:
                if min_week_local <= current_date <= max_week_local:
                    # Zeit-Badge-Logik
                    if is_all_day_event:
                        time_str = "Ganztägig"
                        mark_all_day = True
                    elif same_day:
                        # Zeitspanne oder Punkttermin am selben Tag
                        if duration > timedelta(0):
                            time_str = f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                        else:
                            time_str = start_local.strftime("%H:%M")
                        mark_all_day = False
                    elif ends_midnight_next and current_date == start_local.date():
                        # Endet exakt 00:00 am Folgetag
                        if start_local.time() == time.min:
                            time_str = "Ganztägig"
                            mark_all_day = True
                        else:
                            time_str = f"{start_local.strftime('%H:%M')}–00:00"
                            mark_all_day = False
                    elif current_date == start_local.date():
                        time_str = f"Start: {start_local.strftime('%H:%M')}"
                        mark_all_day = False
                    elif current_date == loop_end_date and end_local.time() > time.min:
                        time_str = f"Ende: {end_local.strftime('%H:%M')}"
                        mark_all_day = False
                    else:
                        # Mitteltage von Zeit-Terminen
                        time_str = "Ganztägig"
                        mark_all_day = True

                    # Deduplizierung (z. B. falls dieselbe Instanz über RRULE/RDATE doppelt kommt)
                    key = (summary, time_str, start_dt)
                    if key not in seen_per_day[current_date]:
                        seen_per_day[current_date].add(key)
                        week_events[current_date].append({
                            "summary": summary,
                            "time": time_str,
                            "is_all_day": mark_all_day,
                            "start_time": start_dt,  # für Sortierung
                        })
                current_date += timedelta(days=1)

        # VEVENTs durchlaufen
        for component in cal.walk("VEVENT"):
            summary_str = ""
            try:
                summary_raw = component.get("summary")
                summary_str = html.escape(str(summary_raw) if summary_raw is not None else "Ohne Titel")

                dtstart_prop = component.get("dtstart")
                if dtstart_prop is None:
                    print(f"Warnung: VEVENT ohne DTSTART (summary={summary_str})", file=sys.stderr)
                    continue

                dtstart_raw = dtstart_prop.dt
                dtstart = to_utc_from_prop(dtstart_raw)

                dtend_prop = component.get("dtend")
                duration_prop = component.get("duration")

                if not dtend_prop and duration_prop:
                    dtend = dtstart + duration_prop.dt
                elif not dtend_prop and not duration_prop:
                    # RFC-konform: DATE ohne DTEND/DURATION → 1 Tag; sonst punktuell ohne Dauer
                    if isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime):
                        dtend = dtstart + timedelta(days=1)
                    else:
                        dtend = dtstart
                else:
                    dtend = to_utc_from_prop(dtend_prop.dt)

                duration = dtend - dtstart

                # EXDATE sammeln (UTC)
                exdates: Set[datetime] = set()
                ex_prop = component.get("exdate")
                ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
                for ex in ex_list:
                    for d in ex.dts:
                        ex_dt = to_utc_from_prop(d.dt)
                        exdates.add(ex_dt)

                # RRULE-Verarbeitung
                rrule_prop = component.get("rrule")
                if rrule_prop:
                    rrule = rrulestr(rrule_prop.to_ical().decode(), dtstart=dtstart)
                    pad = duration if duration > timedelta(0) else timedelta(0)
                    search_start_dt = start_of_week_dt - pad
                    search_end_dt = end_of_week_dt

                    for occ_start in rrule.between(search_start_dt, search_end_dt, inc=True):
                        if occ_start in exdates:
                            continue
                        add_event_to_week(component, occ_start, occ_start + duration, summary_str, duration)
                else:
                    add_event_to_week(component, dtstart, dtend, summary_str, duration)

                # RDATE (zusätzliche Vorkommnisse)
                rdate_prop = component.get("rdate")
                rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
                for r in rdate_list:
                    for d in r.dts:
                        r_dt = to_utc_from_prop(d.dt)
                        if r_dt in exdates:
                            continue
                        add_event_to_week(component, r_dt, r_dt + duration, summary_str, duration)

            except Exception as e:
                print(f"Fehler beim Verarbeiten eines Termins ('{summary_str}'): {e}", file=sys.stderr)

        # Kopf-/Fußzeileninfos
        calendar_week = start_of_week_local.isocalendar()[1]
        timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")

        def fmt_short(d: date) -> str:
            return d.strftime("%d.%m.")

        date_range_str = f"{fmt_short(monday_vie)}–{fmt_short(friday_vie)}"

        # HTML erzeugen
        html_parts: List[str] = []
        html_parts.append(
            f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=1920, initial-scale=1"><title>Wochenplan</title><style>
:root{{--bg:#f5f6f8;--card:#fff;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;--radius:12px;--brand:#3f6f3a;--brand2:#3f6f3a;--accent:#4f9f5a;--accent-soft:#eaf6ee;}}
*{{box-sizing:border-box;}}
html,body{{height:100%;}}
body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial;display:flex;flex-direction:column;min-height:100vh;}}
header.topbar{{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;padding:12px 20px;}}
.topbar-inner{{display:flex;align-items:center;gap:14px;}}
.logo{{background:#fff;border-radius:10px;padding:6px;display:flex;align-items:center;justify-content:center;}}
.logo img{{width:28px;height:28px;display:block;}}
.title{{font-weight:700;font-size:22px;letter-spacing:.2px;}}
.sub{{font-size:13px;opacity:.95;}}
main.container{{padding:16px 20px 8px;flex:1;}}
.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;}}
.day{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:0 6px 18px rgba(0,0,0,.06);min-height:160px;display:flex;flex-direction:column;}}
.day-header{{padding:10px 12px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;justify-content:space-between;background:linear-gradient(180deg,rgba(0,0,0,.02),transparent);}}
.day-name{{font-weight:700;}}
.day-date{{color:var(--muted);font-size:13px;}}
.day.today{{border-color:rgba(79,159,90,.55);box-shadow:0 0 0 3px rgba(79,159,90,.14),0 6px 18px rgba(0,0,0,.06);}}
.day.today .day-header{{background:linear-gradient(180deg,var(--accent-soft),transparent);border-bottom-color:rgba(79,159,90,.35);}}
.events{{padding:10px 12px 12px;display:grid;gap:10px;}}
.event{{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:start;}}
.badge{{font-weight:700;font-size:12px;padding:4px 8px;border-radius:999px;border:1px solid rgba(79,159,90,.35);background:var(--accent-soft);white-space:nowrap;}}
.badge.all{{border-style:dashed;}}
.summary{{font-size:15px;line-height:1.35;}}
.no-events{{color:var(--muted);text-align:center;padding:18px 10px 22px;font-style:italic;}}
footer.foot{{color:#6b7280;font-size:13px;text-align:center;padding:6px 0 12px;margin-top:auto;}}
</style></head>
<body>
<header class="topbar" role="banner">
  <div class="topbar-inner">
    <div class="logo" aria-hidden="true"><img src="https://cdn.riverty.design/logo/riverty-logomark-green.svg" alt="Riverty Logo"></div>
    <div>
      <div class="title">Wochenplan (KW {calendar_week})</div>
      <div class="sub">{date_range_str}</div>
    </div>
  </div>
</header>
<main class="container" role="main">
<section class="grid" aria-label="Wochentage">"""
        )

        # Rendering pro Tag (lokale Daten)
        for i, day_name in enumerate(["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]):
            current_date_local = monday_vie + timedelta(days=i)
            events_for_day = week_events.get(current_date_local, [])
            # Sortierung: Ganztägig zuerst, dann nach Startzeit, dann nach Summary
            events_for_day.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))
            is_today_cls = " today" if current_date_local == now_vienna.date() else ""

            html_parts.append(
                f"""<article class="day{is_today_cls}" aria-labelledby="d{i}-label">
  <div class="day-header">
    <div id="d{i}-label" class="day-name">{day_name}</div>
    <div class="day-date">{current_date_local.strftime('%d.%m.')}</div>
  </div>
  <div class="events">"""
            )

            if not events_for_day:
                html_parts.append('<div class="no-events">–</div>')
            else:
                for ev in events_for_day:
                    badge_cls = "badge all" if ev["is_all_day"] else "badge"
                    html_parts.append(
                        f"""<div class="event"><div class="{badge_cls}">{ev['time']}</div><div class="summary">{ev['summary']}</div></div>"""
                    )

            html_parts.append("</div></article>")

        html_parts.append(
            f"""</section></main>
<footer class="foot" role="contentinfo">Kalender zuletzt aktualisiert am {timestamp_vienna}</footer>
</body></html>"""
        )

        # Schreiben
        os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
        with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
            f.write("".join(html_parts))

        print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")

    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    erstelle_kalender_html()
