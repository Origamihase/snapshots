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
from datetime import datetime, date, time, timezone, timedelta
from typing import Any

OUTPUT_HTML_FILE = "public/calendar/index.html"


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
        cal = Calendar.from_ical(response.content)

        tz_vienna = ZoneInfo("Europe/Vienna")
        now_vienna = datetime.now(tz_vienna)

        # Woche lokal (Wien) bestimmen und dann UTC-Fenster für die Suche ableiten
        start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_vienna.weekday())
        end_of_week_local   = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)
        start_of_week_dt = start_of_week_local.astimezone(timezone.utc)
        end_of_week_dt   = end_of_week_local.astimezone(timezone.utc)

        monday_vie = start_of_week_local.date()
        friday_vie = (start_of_week_local + timedelta(days=4)).date()

        # Buckets auf Basis lokaler (Wien) Datums-Keys
        week_events: dict[date, list[dict[str, Any]]] = {
            (start_of_week_local.date() + timedelta(days=i)): [] for i in range(5)
        }
        min_week_local = start_of_week_local.date()
        max_week_local = (start_of_week_local + timedelta(days=4)).date()

        def add_event_to_week(component, start_dt: datetime, end_dt: datetime,
                              summary: str, duration: timedelta) -> None:
            """Fügt ein Ereignis allen betroffenen lokalen Tagen in week_events hinzu."""
            start_local = start_dt.astimezone(tz_vienna)
            end_local   = end_dt.astimezone(tz_vienna)

            is_all_day_event = (
                isinstance(component.get("dtstart").dt, date)
                and not isinstance(component.get("dtstart").dt, datetime)
            )

            # DTEND-Exklusivität korrekt behandeln:
            loop_end_date = end_local.date()
            if is_all_day_event:
                # DATE-basiert: letzter voller Tag ist der Vortag (lokal), unabhängig von DST/00:00
                loop_end_date -= timedelta(days=1)
            elif end_local.time() == time.min and duration > timedelta(0):
                # Zeitbasierter Termin, der exakt 00:00 endet -> letzter voller Tag ist Vortag
                loop_end_date -= timedelta(days=1)

            current_date = start_local.date()
            while current_date <= loop_end_date:
                if min_week_local <= current_date <= max_week_local:
                    # Vereinfachte, gut lesbare Zeit-Badge-Logik
                    if is_all_day_event:
                        time_str = "Ganztägig"
                    elif current_date == start_local.date():
                        time_str = start_local.strftime("%H:%M")
                    elif current_date == loop_end_date and end_local.time() > time.min:
                        time_str = f"bis {end_local.strftime('%H:%M')}"
                    else:
                        time_str = "–"

                    week_events[current_date].append({
                        "summary": summary,
                        "time": time_str,
                        "is_all_day": is_all_day_event,
                        "start_time": start_dt,  # für Sortierung stabil (UTC)
                    })
                current_date += timedelta(days=1)

        # Termine verarbeiten
        for component in cal.walk("VEVENT"):
            summary_str = ""
            try:
                # Robuster Summary-Fallback
                summary_raw = component.get("summary")
                summary_str = html.escape(str(summary_raw) if summary_raw is not None else "Ohne Titel")

                # DTSTART normalisieren -> UTC
                dtstart_raw = component.get("dtstart").dt
                if isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime):
                    # All-Day: auf 00:00 UTC (Anzeige/Zuordnung erfolgt später lokal korrekt)
                    dtstart = datetime.combine(dtstart_raw, time.min, tzinfo=timezone.utc)
                else:
                    if getattr(dtstart_raw, "tzinfo", None):
                        dtstart = dtstart_raw.astimezone(timezone.utc)
                    else:
                        # Naive Datetimes als Wien interpretieren
                        dtstart = dtstart_raw.replace(tzinfo=tz_vienna).astimezone(timezone.utc)

                # DTEND bzw. DURATION
                dtend_prop = component.get("dtend")
                duration_prop = component.get("duration")
                if not dtend_prop and duration_prop:
                    dtend = dtstart + duration_prop.dt
                else:
                    dtend_raw = dtend_prop.dt if dtend_prop else dtstart_raw
                    if isinstance(dtend_raw, date) and not isinstance(dtend_raw, datetime):
                        dtend = datetime.combine(dtend_raw, time.min, tzinfo=timezone.utc)
                    else:
                        if getattr(dtend_raw, "tzinfo", None):
                            dtend = dtend_raw.astimezone(timezone.utc)
                        else:
                            dtend = dtend_raw.replace(tzinfo=tz_vienna).astimezone(timezone.utc)

                duration = dtend - dtstart

                # Wiederholungen (RRULE) + Ausnahmen (EXDATE)
                rrule_prop = component.get("rrule")
                if rrule_prop:
                    exdates = set()
                    ex_prop = component.get("exdate")
                    ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
                    for ex in ex_list:
                        for d in ex.dts:
                            ex_dt_raw = d.dt
                            if isinstance(ex_dt_raw, date) and not isinstance(ex_dt_raw, datetime):
                                ex_dt = datetime.combine(ex_dt_raw, time.min, tzinfo=timezone.utc)
                            else:
                                ex_dt = (ex_dt_raw.astimezone(timezone.utc) if getattr(ex_dt_raw, "tzinfo", None)
                                         else ex_dt_raw.replace(tzinfo=tz_vienna).astimezone(timezone.utc))
                            exdates.add(ex_dt)

                    rrule = rrulestr(rrule_prop.to_ical().decode(), dtstart=dtstart)

                    # Suchfenster für „Überhänger“: nach vorne um Dauer erweitern
                    pad = duration if duration > timedelta(0) else timedelta(0)
                    search_start_dt = start_of_week_dt - pad
                    search_end_dt   = end_of_week_dt

                    for occ_start in rrule.between(search_start_dt, search_end_dt, inc=True):
                        if occ_start in exdates:
                            continue
                        add_event_to_week(component, occ_start, occ_start + duration, summary_str, duration)
                else:
                    add_event_to_week(component, dtstart, dtend, summary_str, duration)

                # Zusätzliche Einzelvorkommen (RDATE)
                rdate_prop = component.get("rdate")
                rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
                for r in rdate_list:
                    for d in r.dts:
                        r_dt_raw = d.dt
                        if isinstance(r_dt_raw, date) and not isinstance(r_dt_raw, datetime):
                            r_dt = datetime.combine(r_dt_raw, time.min, tzinfo=timezone.utc)
                        else:
                            r_dt = (r_dt_raw.astimezone(timezone.utc) if getattr(r_dt_raw, "tzinfo", None)
                                    else r_dt_raw.replace(tzinfo=tz_vienna).astimezone(timezone.utc))
                        add_event_to_week(component, r_dt, r_dt + duration, summary_str, duration)

            except Exception as e:
                print(f"Fehler beim Verarbeiten eines Termins ('{summary_str}'): {e}", file=sys.stderr)

        # Meta-Daten
        calendar_week = start_of_week_local.isocalendar()[1]
        timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")

        def fmt_short(d: date) -> str:
            return d.strftime("%d.%m.")

        date_range_str = f"{fmt_short(monday_vie)}–{fmt_short(friday_vie)}"

        # HTML (minifiziert, TV-optimiert, Sticky-Footer)
        html_parts: list[str] = []
        html_parts.append(
            f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">
<meta name="viewport" content="width=1920, initial-scale=1"><title>Wochenplan</title>
<style>:root{{--bg:#f5f6f8;--card:#fff;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;--radius:12px;--brand:#3f6f3a;--brand2:#3f6f3a;--accent:#4f9f5a;--accent-soft:#eaf6ee;}}*{{box-sizing:border-box;}}html,body{{height:100%;}}
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
footer.foot{{color:#6b7280;font-size:13px;text-align:center;padding:6px 0 12px;margin-top:auto;}}</style></head>
<body><header class="topbar" role="banner"><div class="topbar-inner">
<div class="logo" aria-hidden="true"><img src="https://cdn.riverty.design/logo/riverty-logomark-green.svg" alt="Riverty Logo"></div>
<div><div class="title">Wochenplan (KW {calendar_week})</div><div class="sub">{date_range_str}</div></div>
</div></header><main class="container" role="main"><section class="grid" aria-label="Wochentage">"""
        )

        # Render (lokale Daten als Schlüssel)
        for i, day_name in enumerate(["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]):
            current_date_local = monday_vie + timedelta(days=i)
            events_for_day = week_events.get(current_date_local, [])
            events_for_day.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))
            is_today_cls = " today" if current_date_local == now_vienna.date() else ""

            html_parts.append(
                f"""<article class="day{is_today_cls}" aria-labelledby="d{i}-label"><div class="day-header"><div id="d{i}-label" class="day-name">{day_name}</div><div class="day-date">{current_date_local.strftime('%d.%m.')}</div></div><div class="events">"""
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
            f"""</section></main><footer class="foot" role="contentinfo">Kalender zuletzt aktualisiert am {timestamp_vienna}</footer></body></html>"""
        )

        os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
        with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
            f.write("".join(html_parts))

        print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")

    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Herunterladen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    erstelle_kalender_html()
