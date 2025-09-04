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
from typing import Any, Dict, List

OUTPUT_HTML_FILE = "public/calendar/index.html"


# ----------------------------- Zeit & ICS Helfer -----------------------------

def to_utc(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """
    Normalisiert ICS-Zeitwerte zuverlässig nach UTC.

    - VALUE=DATE -> als lokale Mitternacht interpretieren und nach UTC konvertieren
    - Naive datetime -> als lokal interpretieren
    - Aware datetime -> direkt nach UTC
    """
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        return datetime.combine(dt_raw, time.min, tzinfo=tz_local).astimezone(timezone.utc)
    if getattr(dt_raw, "tzinfo", None):
        return dt_raw.astimezone(timezone.utc)
    return dt_raw.replace(tzinfo=tz_local).astimezone(timezone.utc)


def iter_exdates(component, tz_local: ZoneInfo) -> set[datetime]:
    exdates: set[datetime] = set()
    ex_prop = component.get("exdate")
    if not ex_prop:
        return exdates
    items = ex_prop if isinstance(ex_prop, list) else [ex_prop]
    for ex in items:
        for d in ex.dts:
            exdates.add(to_utc(d.dt, tz_local))
    return exdates


def iter_rdates(component, tz_local: ZoneInfo) -> List[datetime]:
    rdates: List[datetime] = []
    r_prop = component.get("rdate")
    if not r_prop:
        return rdates
    items = r_prop if isinstance(r_prop, list) else [r_prop]
    for r in items:
        for d in r.dts:
            rdates.append(to_utc(d.dt, tz_local))
    return rdates


# ----------------------------- Rendering Logik -------------------------------

def add_event_to_week(
    week_events: Dict[date, List[Dict[str, Any]]],
    component,
    start_utc: datetime,
    end_utc: datetime,
    summary: str,
    tz_local: ZoneInfo,
    week_start_local: date,
) -> None:
    """
    Fügt ein (ggf. mehrtägiges) Ereignis allen betroffenen lokalen Tagen der Woche hinzu.
    """
    start_local = start_utc.astimezone(tz_local)
    end_local = end_utc.astimezone(tz_local)

    is_all_day_src = (
        isinstance(component.get("dtstart").dt, date)
        and not isinstance(component.get("dtstart").dt, datetime)
    )

    # DTEND-Exklusivität korrekt behandeln (auch für Zeit-Termine bei Mitternacht)
    loop_end_date = end_local.date()
    if is_all_day_src:
        loop_end_date -= timedelta(days=1)
    elif end_local.time() == time.min and end_utc > start_utc:
        loop_end_date -= timedelta(days=1)

    week_end_local = week_start_local + timedelta(days=4)

    current_date = start_local.date()
    while current_date <= loop_end_date:
        if week_start_local <= current_date <= week_end_local:
            # Badge-Text je Tag bestimmen
            if is_all_day_src:
                time_str = "Ganztägig"
                is_all_day_flag = True
            else:
                same_day = (start_local.date() == end_local.date())
                ends_midnight_next = (
                    end_local.time() == time.min
                    and end_local.date() > start_local.date()
                    and end_utc > start_utc
                )

                if same_day:
                    # 1-Tages-Termin
                    time_str = (
                        f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                        if end_utc > start_utc else start_local.strftime("%H:%M")
                    )
                    is_all_day_flag = False
                elif current_date == start_local.date():
                    # erster Tag eines mehrtägigen Zeit-Termins
                    if ends_midnight_next:
                        # z.B. 13:00–00:00
                        time_str = f"{start_local.strftime('%H:%M')}–00:00" if start_local.time() != time.min else "Ganztägig"
                    else:
                        time_str = f"Start: {start_local.strftime('%H:%M')}"
                    is_all_day_flag = time_str == "Ganztägig"
                elif current_date == loop_end_date and end_local.time() > time.min:
                    # letzter Tag, falls nicht Mitternacht
                    time_str = f"Ende: {end_local.strftime('%H:%M')}"
                    is_all_day_flag = False
                else:
                    # Zwischentage mehrtägiger Zeit-Termin
                    time_str = "Ganztägig"
                    is_all_day_flag = True

            week_events[current_date].append({
                "summary": summary,
                "time": time_str,
                "is_all_day": is_all_day_flag,
                "start_time": start_utc,
            })

        current_date += timedelta(days=1)


def generate_html(
    week_events: Dict[date, List[Dict[str, Any]]],
    start_of_week_local: datetime,
    now_local: datetime,
    tz_local: ZoneInfo,
) -> None:
    calendar_week = start_of_week_local.isocalendar()[1]
    monday_local = start_of_week_local.date()
    friday_local = (start_of_week_local + timedelta(days=4)).date()
    timestamp_local = datetime.now(tz_local).strftime("%d.%m.%Y um %H:%M:%S Uhr")

    def fmt_short(d: date) -> str:
        return d.strftime("%d.%m.")

    date_range_str = f"{fmt_short(monday_local)}–{fmt_short(friday_local)}"

    html_parts: List[str] = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1920, initial-scale=1">
<title>Wochenplan</title>
<style>
:root {{
  --bg:#f5f6f8; --card:#fff; --text:#1f2937; --muted:#6b7280; --border:#e5e7eb; --radius:12px;
  --brand:#3f6f3a; --brand2:#3f6f3a; --accent:#4f9f5a; --accent-soft:#eaf6ee;
}}
*{{box-sizing:border-box;}}
html,body{{height:100%;}}
body{{
  margin:0; background:var(--bg); color:var(--text);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial;
  display:flex; flex-direction:column; min-height:100vh;
}}
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

    days_de = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    today_local = now_local.date()

    for i, day_name in enumerate(days_de):
        current_date_local = monday_local + timedelta(days=i)
        day_events = week_events.get(current_date_local, [])
        day_events.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))
        is_today_cls = " today" if current_date_local == today_local else ""

        html_parts.append(
            f'<article class="day{is_today_cls}" aria-labelledby="d{i}-label">'
            f'<div class="day-header"><div id="d{i}-label" class="day-name">{day_name}</div>'
            f'<div class="day-date">{current_date_local.strftime("%d.%m.")}</div></div>'
            f'<div class="events">'
        )

        if not day_events:
            html_parts.append('<div class="no-events">–</div>')
        else:
            for ev in day_events:
                badge_cls = "badge all" if ev["is_all_day"] else "badge"
                html_parts.append(
                    f'<div class="event"><div class="{badge_cls}">{ev["time"]}</div>'
                    f'<div class="summary">{ev["summary"]}</div></div>'
                )

        html_parts.append("</div></article>")

    html_parts.append(
        f"""</section></main>
<footer class="foot" role="contentinfo">Kalender zuletzt aktualisiert am {timestamp_local}</footer>
</body></html>"""
    )

    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))


# --------------------------------- Main --------------------------------------

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
    except Exception as e:
        print(f"Fehler beim Laden/Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    tz_vienna = ZoneInfo("Europe/Vienna")
    now_vienna = datetime.now(tz_vienna)

    # Wochenfenster (lokal Mo 00:00:00 bis Fr 23:59:59)
    start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_vienna.weekday())
    end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)
    start_of_week_utc = start_of_week_local.astimezone(timezone.utc)
    end_of_week_utc = end_of_week_local.astimezone(timezone.utc)

    # Sammlung für Mo–Fr (Keys = lokale Datumsobjekte)
    week_events: Dict[date, List[Dict[str, Any]]] = {
        (start_of_week_local.date() + timedelta(days=i)): [] for i in range(5)
    }

    # RECURRENCE-ID Overrides einsammeln (pro UID)
    overrides: Dict[str, Dict[datetime, Any]] = {}
    for component in cal.walk("VEVENT"):
        uid = str(component.get("uid", ""))
        rid_prop = component.get("recurrence-id")
        if uid and rid_prop:
            overrides.setdefault(uid, {})[to_utc(rid_prop.dt, tz_vienna)] = component

    # Events verarbeiten
    for component in cal.walk("VEVENT"):
        # Overrides werden separat über 'overrides' angewendet
        if component.get("recurrence-id"):
            continue

        try:
            # Unschöne Organizer-Altlasten optional filtern
            if "Ehemaliger Benutzer (Deleted)" in str(component.get("organizer", "")):
                continue

            summary = html.escape(str(component.get("summary") or "Ohne Titel"))

            dtstart_raw = component.get("dtstart").dt
            dtstart_utc = to_utc(dtstart_raw, tz_vienna)

            dtend_prop = component.get("dtend")
            duration_prop = component.get("duration")
            if not dtend_prop and duration_prop:
                dtend_utc = dtstart_utc + duration_prop.dt
            else:
                dtend_raw = (dtend_prop.dt if dtend_prop else dtstart_raw)
                dtend_utc = to_utc(dtend_raw, tz_vienna)

            duration = dtend_utc - dtstart_utc

            rrule_prop = component.get("rrule")
            if rrule_prop:
                # EXDATE / RDATE
                exdates = iter_exdates(component, tz_vienna)
                rdates = iter_rdates(component, tz_vienna)

                # RRULE-Instanzen im Suchfenster (mit Puffer um Dauer)
                pad = duration if duration > timedelta(0) else timedelta(0)
                rrule = rrulestr(rrule_prop.to_ical().decode(), dtstart=dtstart_utc)
                for occ_start_utc in rrule.between(start_of_week_utc - pad, end_of_week_utc, inc=True):
                    if occ_start_utc in exdates:
                        continue
                    uid = str(component.get("uid", ""))
                    effective = overrides.get(uid, {}).get(occ_start_utc, component)

                    eff_summary = html.escape(str(effective.get("summary") or "Ohne Titel"))
                    eff_dtstart_raw = effective.get("dtstart").dt
                    eff_dtstart_utc = to_utc(eff_dtstart_raw, tz_vienna)

                    eff_dtend_prop = effective.get("dtend")
                    eff_duration_prop = effective.get("duration")
                    if not eff_dtend_prop and eff_duration_prop:
                        eff_dtend_utc = eff_dtstart_utc + eff_duration_prop.dt
                    else:
                        eff_dtend_raw = (eff_dtend_prop.dt if eff_dtend_prop else eff_dtstart_raw)
                        eff_dtend_utc = to_utc(eff_dtend_raw, tz_vienna)

                    add_event_to_week(week_events, effective, eff_dtstart_utc, eff_dtend_utc, eff_summary, tz_vienna, start_of_week_local.date())

                # Zusätzliche Einzeltermine via RDATE
                for r_dt in rdates:
                    add_event_to_week(week_events, component, r_dt, r_dt + duration, summary, tz_vienna, start_of_week_local.date())

            else:
                # Einfache Einzeltermine
                add_event_to_week(week_events, component, dtstart_utc, dtend_utc, summary, tz_vienna, start_of_week_local.date())

        except Exception as e:
            print(f"Fehler beim Verarbeiten eines Termins ('{summary}'): {e}", file=sys.stderr)

    # HTML schreiben
    generate_html(week_events, start_of_week_local, now_vienna, tz_vienna)
    print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")


if __name__ == "__main__":
    erstelle_kalender_html()
