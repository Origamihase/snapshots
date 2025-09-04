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

import html
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List

import requests
from dateutil.rrule import rrulestr
from icalendar import Calendar
from zoneinfo import ZoneInfo

OUTPUT_HTML_FILE = "public/calendar/index.html"


# ------------------------ Zeit/ICS-Helfer ------------------------ #

def to_utc_from_prop(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """
    Normalisiert ICS-Datums-/Zeitwerte zuverlässig nach UTC.

    - VALUE=DATE (reines Datum) -> lokale Mitternacht (tz_local) -> UTC
    - Aware datetime -> direkt nach UTC
    - Naive datetime -> als lokale Zeit (tz_local) interpretieren -> UTC
    """
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        # All-day interpretiert als lokale Mitternacht
        return datetime.combine(dt_raw, time.min, tzinfo=tz_local).astimezone(timezone.utc)
    if getattr(dt_raw, "tzinfo", None):
        return dt_raw.astimezone(timezone.utc)
    return dt_raw.replace(tzinfo=tz_local).astimezone(timezone.utc)


def is_all_day_component(component) -> bool:
    """True, wenn DTSTART ein reines Datum ist (VALUE=DATE)."""
    v = component.get("dtstart")
    if not v:
        return False
    d = v.dt
    return isinstance(d, date) and not isinstance(d, datetime)


# ------------------------ Event-Aufbereitung ------------------------ #

def add_event_to_week(
    week_events: Dict[date, List[Dict[str, Any]]],
    component,
    start_dt_utc: datetime,
    end_dt_utc: datetime,
    summary: str,
    tz_display: ZoneInfo,
    week_monday_local: date,
) -> None:
    """Zerlegt ein Event in Tages-Scheiben Mo–Fr, baut Anzeigen-Strings und hängt in week_events ein."""
    start_local = start_dt_utc.astimezone(tz_display)
    end_local = end_dt_utc.astimezone(tz_display)

    is_all_day = is_all_day_component(component)

    # ICS: DTEND ist exklusiv. Für All-Day (VALUE=DATE) steht dtend auf den Tag *nach* dem letzten Tag.
    # Für zeitbasierte Events mit Ende 00:00 am Folgetag gilt ebenso: letzter angezeigter Tag ist der Vortag.
    loop_end_date = end_local.date()
    if is_all_day or (end_local.time() == time.min and end_local.date() > start_local.date()):
        loop_end_date -= timedelta(days=1)

    same_day = (start_local.date() == end_local.date())

    # Grenzen der Anzeige-Woche
    week_start = week_monday_local
    week_end = week_monday_local + timedelta(days=4)

    current = start_local.date()
    while current <= loop_end_date:
        if week_start <= current <= week_end:
            if is_all_day:
                time_str = "Ganztägig"
            else:
                if same_day:
                    # klassischer Ein-Tages-Termin
                    time_str = f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                else:
                    # Mehrtägiger Zeit-Termin
                    if current == start_local.date():
                        # spezieller Fall: 24h-Block von 00:00 bis 00:00 am Folgetag -> 'Ganztägig'
                        if (start_local.time() == time.min
                                and end_local.time() == time.min
                                and (end_local.date() == start_local.date() + timedelta(days=1))):
                            time_str = "Ganztägig"
                        else:
                            time_str = f"Start: {start_local.strftime('%H:%M')}"
                    elif current == loop_end_date and end_local.time() > time.min:
                        time_str = f"Ende: {end_local.strftime('%H:%M')}"
                    else:
                        time_str = "Ganztägig"

            week_events[current].append(
                {
                    "summary": summary,
                    "time": time_str,
                    "is_all_day": (time_str == "Ganztägig"),
                    "start_time": start_dt_utc,
                }
            )

        current += timedelta(days=1)


# ------------------------ HTML-Ausgabe ------------------------ #

def render_html(
    week_events: Dict[date, List[Dict[str, Any]]],
    week_monday_local: datetime,
    now_local: datetime,
) -> str:
    calendar_week = week_monday_local.isocalendar()[1]
    monday = week_monday_local.date()
    friday = (week_monday_local + timedelta(days=4)).date()

    def dshort(d: date) -> str:
        return d.strftime("%d.%m.")

    date_range_str = f"{dshort(monday)}–{friday.strftime('%d.%m.%Y')}"
    timestamp_str = now_local.strftime("%d.%m.%Y um %H:%M:%S Uhr")

    # Modernes, schnelles CSS mit Topbar & Logo
    css = """
:root{
 --bg:#f5f6f8;--card:#fff;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;
 --radius:12px;--brand:#3f6f3a;--brand2:#3f6f3a;--accent:#4f9f5a;--accent-soft:#eaf6ee;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);
     font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial;
     display:flex;flex-direction:column;min-height:100vh}
header.topbar{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;padding:12px 20px}
.topbar-inner{display:flex;align-items:center;gap:14px}
.logo{background:#fff;border-radius:10px;padding:6px;display:flex;align-items:center;justify-content:center}
.logo img{width:28px;height:28px;display:block}
.title{font-weight:700;font-size:22px;letter-spacing:.2px}
.sub{font-size:13px;opacity:.95}
main.container{padding:16px 20px 8px;flex:1}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.day{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
     box-shadow:0 6px 18px rgba(0,0,0,.06);min-height:160px;display:flex;flex-direction:column}
.day-header{padding:10px 12px;border-bottom:1px solid var(--border);
           display:flex;align-items:baseline;justify-content:space-between;
           background:linear-gradient(180deg,rgba(0,0,0,.02),transparent)}
.day-name{font-weight:700}
.day-date{color:var(--muted);font-size:13px}
.day.today{border-color:rgba(79,159,90,.55);
           box-shadow:0 0 0 3px rgba(79,159,90,.14),0 6px 18px rgba(0,0,0,.06)}
.day.today .day-header{background:linear-gradient(180deg,var(--accent-soft),transparent);
                      border-bottom-color:rgba(79,159,90,.35)}
.events{padding:10px 12px 12px;display:grid;gap:10px}
.event{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:start}
.badge{font-weight:700;font-size:12px;padding:4px 8px;border-radius:999px;
       border:1px solid rgba(79,159,90,.35);background:var(--accent-soft);white-space:nowrap}
.badge.all{border-style:dashed}
.summary{font-size:15px;line-height:1.35}
.no-events{color:var(--muted);text-align:center;padding:18px 10px 22px;font-style:italic}
footer.foot{color:#6b7280;font-size:13px;text-align:center;padding:6px 0 12px;margin-top:auto}
"""

    parts: List[str] = []
    parts.append(
        f'<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=1920, initial-scale=1">'
        f'<title>Wochenplan</title><style>{css}</style></head><body>'
        f'<header class="topbar" role="banner"><div class="topbar-inner">'
        f'<div class="logo" aria-hidden="true"><img src="https://cdn.riverty.design/logo/riverty-logomark-green.svg" alt=""></div>'
        f'<div><div class="title">Wochenplan (KW {calendar_week})</div>'
        f'<div class="sub">{date_range_str}</div></div></div></header>'
        f'<main class="container" role="main"><section class="grid" aria-label="Wochentage">'
    )

    day_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    for i, name in enumerate(day_names):
        the_date = monday + timedelta(days=i)
        is_today_cls = " today" if the_date == now_local.date() else ""
        items = week_events.get(the_date, [])
        items.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))

        parts.append(
            f'<article class="day{is_today_cls}" aria-labelledby="d{i}-label">'
            f'<div class="day-header"><div id="d{i}-label" class="day-name">{name}</div>'
            f'<div class="day-date">{the_date.strftime("%d.%m.")}</div></div>'
            f'<div class="events">'
        )

        if not items:
            parts.append('<div class="no-events">–</div>')
        else:
            for ev in items:
                cls = "badge all" if ev["is_all_day"] else "badge"
                parts.append(
                    f'<div class="event"><div class="{cls}">{ev["time"]}</div>'
                    f'<div class="summary">{ev["summary"]}</div></div>'
                )
        parts.append("</div></article>")

    parts.append(
        f'</section></main><footer class="foot" role="contentinfo">'
        f'Kalender zuletzt aktualisiert am {timestamp_str}'
        f'</footer></body></html>'
    )
    return "".join(parts)


# ------------------------ Hauptlogik ------------------------ #

def erstelle_kalender_html() -> None:
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    try:
        resp = requests.get(ics_url, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Herunterladen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        cal = Calendar.from_ical(resp.content)
    except Exception as e:
        print(f"Fehler beim Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    tz_vienna = ZoneInfo("Europe/Vienna")
    now_local = datetime.now(tz_vienna)

    # Wochenfenster (Mo 00:00 – Fr 23:59:59 lokal)
    monday_local_dt = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_local.weekday())
    friday_local_dt = monday_local_dt + timedelta(days=4, hours=23, minutes=59, seconds=59)
    monday_utc = monday_local_dt.astimezone(timezone.utc)
    friday_utc = friday_local_dt.astimezone(timezone.utc)

    # Zielcontainer: Mo–Fr
    week_events: Dict[date, List[Dict[str, Any]]] = { (monday_local_dt.date() + timedelta(days=i)): [] for i in range(5) }

    # RECURRENCE-ID Overrides sammeln
    overrides: Dict[str, Dict[datetime, Any]] = {}
    for comp in cal.walk("VEVENT"):
        uid = str(comp.get("uid") or "")
        rid = comp.get("recurrence-id")
        if uid and rid:
            overrides.setdefault(uid, {})[to_utc_from_prop(rid.dt, tz_vienna)] = comp

    # Events iterieren (Basisevents; Overrides werden beim Expandieren berücksichtigt)
    for comp in cal.walk("VEVENT"):
        if comp.get("recurrence-id"):
            continue  # nur Basiseinträge expandieren

        # Organizer-Filter (optional, wie besprochen)
        organizer_str = str(comp.get("organizer", ""))
        if "Ehemaliger Benutzer (Deleted)" in organizer_str:
            continue

        summary = html.escape(str(comp.get("summary") or "Ohne Titel"))

        dtstart_raw = comp.get("dtstart").dt
        dtstart_utc = to_utc_from_prop(dtstart_raw, tz_vienna)

        dtend_prop = comp.get("dtend")
        duration_prop = comp.get("duration")

        if not dtend_prop and duration_prop:
            dtend_utc = dtstart_utc + duration_prop.dt
        else:
            dtend_raw = (dtend_prop.dt if dtend_prop else dtstart_raw)
            dtend_utc = to_utc_from_prop(dtend_raw, tz_vienna)

        duration = dtend_utc - dtstart_utc

        # EXDATE einsammeln (kann Liste oder einzelnes Feld sein)
        ex_prop = comp.get("exdate")
        ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
        exdates = {to_utc_from_prop(d.dt, tz_vienna) for ex in ex_list for d in getattr(ex, "dts", [])}

        # RDATE (zusätzliche Einzeltermine)
        rdate_prop = comp.get("rdate")
        rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])

        if comp.get("rrule"):
            rule = rrulestr(comp.get("rrule").to_ical().decode("utf-8"), dtstart=dtstart_utc)
            # Suchfenster leicht nach hinten erweitern, damit Events knapp vorm Wochenstart, die in die Woche hineinragen, erfasst werden
            pad = duration if duration > timedelta(0) else timedelta(0)
            search_start = monday_utc - pad
            for occ_start in rule.between(search_start, friday_utc, inc=True):
                if occ_start in exdates:
                    continue
                eff = overrides.get(str(comp.get("uid") or ""), {}).get(occ_start, comp)

                # Effektive Daten ermitteln (Override kann andere Zeiten/Titel haben)
                eff_summary = html.escape(str(eff.get("summary") or "Ohne Titel"))
                eff_dtstart_raw = eff.get("dtstart").dt
                eff_dtstart_utc = to_utc_from_prop(eff_dtstart_raw, tz_vienna)

                eff_dtend_prop = eff.get("dtend")
                eff_duration_prop = eff.get("duration")
                if not eff_dtend_prop and eff_duration_prop:
                    eff_dtend_utc = eff_dtstart_utc + eff_duration_prop.dt
                else:
                    eff_dtend_raw = (eff_dtend_prop.dt if eff_dtend_prop else eff_dtstart_raw)
                    eff_dtend_utc = to_utc_from_prop(eff_dtend_raw, tz_vienna)

                add_event_to_week(week_events, eff, eff_dtstart_utc, eff_dtend_utc, eff_summary, tz_vienna, monday_local_dt.date())
        else:
            # kein RRULE -> Einzeltermin
            add_event_to_week(week_events, comp, dtstart_utc, dtend_utc, summary, tz_vienna, monday_local_dt.date())

        # RDATE-Occurrences (zusätzliche Termine) anfügen
        for r in rdate_list:
            for d in getattr(r, "dts", []):
                r_dt_raw = d.dt
                r_dt_utc = to_utc_from_prop(r_dt_raw, tz_vienna)
                add_event_to_week(week_events, comp, r_dt_utc, r_dt_utc + duration, summary, tz_vienna, monday_local_dt.date())

    # HTML erzeugen & schreiben
    html_str = render_html(week_events, monday_local_dt, now_local)

    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_str)

    print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")


if __name__ == "__main__":
    erstelle_kalender_html()
