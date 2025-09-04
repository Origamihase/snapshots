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
from typing import Any, Dict, Iterable, List

OUTPUT_HTML_FILE = "public/calendar/index.html"


# ---------- Hilfen für Zeit & ICS ----------

def to_utc_from_prop(dt_raw: date | datetime, local_tz: ZoneInfo) -> datetime:
    """Normalisiert ICS-Datums-/Zeitwerte zuverlässig nach UTC."""
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        # All-day -> lokale Mitternacht annehmen, dann nach UTC
        return datetime.combine(dt_raw, time.min, tzinfo=local_tz).astimezone(timezone.utc)
    if getattr(dt_raw, "tzinfo", None):
        return dt_raw.astimezone(timezone.utc)
    # Naive Datetimes als lokale Zeit interpretieren
    return dt_raw.replace(tzinfo=local_tz).astimezone(timezone.utc)


def _iter_prop_dates(component, prop_name: str) -> Iterable[date | datetime]:
    """Liest EXDATE/RDATE robust aus (einzeln, Liste oder vDDDLists)."""
    prop = component.get(prop_name)
    if not prop:
        return []
    items = prop if isinstance(prop, list) else [prop]
    out: List[date | datetime] = []
    for item in items:
        # vDDDLists haben .dts; einzelne vDatetime haben .dt
        if hasattr(item, "dts"):
            for d in item.dts:
                out.append(d.dt)
        elif hasattr(item, "dt"):
            out.append(item.dt)
    return out


# ---------- Terminverteilung auf Wochentage ----------

def add_event_to_week(
    week_events: Dict[date, List[Dict[str, Any]]],
    component,
    start_dt_utc: datetime,
    end_dt_utc: datetime,
    summary_html: str,
    view_tz: ZoneInfo,
    week_start_date: date,
    week_end_date: date,
) -> None:
    """Zerlegt ein Event in Tages-Kacheln und hängt es in week_events ein."""
    start_local = start_dt_utc.astimezone(view_tz)
    end_local = end_dt_utc.astimezone(view_tz)

    is_all_day = (
        isinstance(component.get("dtstart").dt, date)
        and not isinstance(component.get("dtstart").dt, datetime)
    )

    # DTEND ist exklusiv; bei All-day (oder 00:00-Ende) einen Tag abziehen
    loop_end_date = end_local.date()
    if is_all_day or (end_local.time() == time.min and end_local > start_local):
        loop_end_date -= timedelta(days=1)

    same_day = (start_local.date() == end_local.date()) or (loop_end_date == start_local.date())

    current = start_local.date()
    while current <= loop_end_date:
        if week_start_date <= current <= week_end_date:
            if is_all_day:
                time_str = "Ganztägig"
            elif same_day:
                # eintägig mit Uhrzeitspanne
                time_str = (
                    f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                    if end_local > start_local else start_local.strftime("%H:%M")
                )
            elif current == start_local.date():
                time_str = f"Start: {start_local.strftime('%H:%M')}"
            elif current == loop_end_date and end_local.time() > time.min:
                time_str = f"Ende: {end_local.strftime('%H:%M')}"
            else:
                time_str = "Ganztägig"

            week_events[current].append(
                {
                    "summary": summary_html,
                    "time": time_str,
                    "is_all_day": is_all_day or time_str == "Ganztägig",
                    "start_time": start_dt_utc,
                }
            )
        current += timedelta(days=1)


# ---------- HTML Ausgabe ----------

def generate_html(
    week_events: Dict[date, List[Dict[str, Any]]],
    week_start_local: datetime,
    now_local: datetime,
    output_file: str,
) -> None:
    calendar_week = week_start_local.isocalendar()[1]
    monday = week_start_local.date()
    friday = monday + timedelta(days=4)
    date_range_str = f"{monday.strftime('%d.%m.')}–{friday.strftime('%d.%m.%Y')}"
    timestamp_local = now_local.strftime("%d.%m.%Y um %H:%M:%S Uhr")

    html_parts: List[str] = []
    html_parts.append(
        f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">
<meta name="viewport" content="width=1920, initial-scale=1">
<title>Wochenplan</title>
<style>
:root {{
  --bg:#f5f6f8; --card:#fff; --text:#1f2937; --muted:#6b7280; --border:#e5e7eb;
  --radius:12px; --brand:#3f6f3a; --brand2:#3f6f3a; --accent:#4f9f5a; --accent-soft:#eaf6ee;
}}
* {{ box-sizing:border-box; }}
html, body {{ height:100%; }}
body {{
  margin:0; background:var(--bg); color:var(--text);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial;
  display:flex; flex-direction:column; min-height:100vh;
}}
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
.day.today {{ border-color:rgba(79,159,90,.55);
             box-shadow:0 0 0 3px rgba(79,159,90,.14),0 6px 18px rgba(0,0,0,.06); }}
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
</style></head>
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
<section class="grid" aria-label="Wochentage">"""
    )

    weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    for i, day_name in enumerate(weekdays):
        cur_date = monday + timedelta(days=i)
        events_for_day = sorted(
            week_events.get(cur_date, []),
            key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()),
        )
        is_today_cls = " today" if cur_date == now_local.date() else ""

        html_parts.append(
            f'<article class="day{is_today_cls}" aria-labelledby="d{i}-label">'
            f'<div class="day-header"><div id="d{i}-label" class="day-name">{day_name}</div>'
            f'<div class="day-date">{cur_date.strftime("%d.%m.")}</div></div><div class="events">'
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
        f"""</section></main>
<footer class="foot" role="contentinfo">Kalender zuletzt aktualisiert am {timestamp_local}</footer>
</body></html>"""
    )

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))


# ---------- Hauptprogramm ----------

def erstelle_kalender_html() -> None:
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

    tz_view = ZoneInfo("Europe/Vienna")
    now_local = datetime.now(tz_view)

    # Woche Mo–Fr
    start_of_week_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_local.weekday())
    end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)
    start_of_week_utc = start_of_week_local.astimezone(timezone.utc)
    end_of_week_utc = end_of_week_local.astimezone(timezone.utc)

    monday = start_of_week_local.date()
    friday = monday + timedelta(days=4)

    week_events: Dict[date, List[Dict[str, Any]]] = {monday + timedelta(days=i): [] for i in range(5)}

    # OVERRIDES: RECURRENCE-ID
    overrides: Dict[str, Dict[datetime, Any]] = {}
    for comp in cal.walk("VEVENT"):
        uid = str(comp.get("uid") or "")
        rid = comp.get("recurrence-id")
        if uid and rid:
            overrides.setdefault(uid, {})[to_utc_from_prop(rid.dt, tz_view)] = comp

    # Hauptrunde (nur Master-Events)
    for comp in cal.walk("VEVENT"):
        if comp.get("recurrence-id"):
            continue  # override-Instanzen werden oberhalb gemappt

        summary_html = html.escape(str(comp.get("summary") or "Ohne Titel"))

        dtstart_raw = comp.get("dtstart").dt
        dtstart_utc = to_utc_from_prop(dtstart_raw, tz_view)

        dtend_prop = comp.get("dtend")
        duration_prop = comp.get("duration")
        if not dtend_prop and duration_prop:
            dtend_utc = dtstart_utc + duration_prop.dt
        else:
            dtend_raw = (dtend_prop.dt if dtend_prop else dtstart_raw)
            dtend_utc = to_utc_from_prop(dtend_raw, tz_view)

        duration = dtend_utc - dtstart_utc

        # EXDATE
        exdates_utc = {to_utc_from_prop(d, tz_view) for d in _iter_prop_dates(comp, "exdate")}

        if comp.get("rrule"):
            rule = rrulestr(comp.get("rrule").to_ical().decode(), dtstart=dtstart_utc)
            pad = duration if duration > timedelta(0) else timedelta(0)
            search_start = start_of_week_utc - pad

            for occ_start_utc in rule.between(search_start, end_of_week_utc, inc=True):
                if occ_start_utc in exdates_utc:
                    continue

                uid = str(comp.get("uid") or "")
                eff = overrides.get(uid, {}).get(occ_start_utc, comp)

                eff_summary = html.escape(str(eff.get("summary") or "Ohne Titel"))
                eff_dtstart_raw = eff.get("dtstart").dt
                eff_dtstart_utc = to_utc_from_prop(eff_dtstart_raw, tz_view)

                eff_dtend_prop = eff.get("dtend")
                eff_duration_prop = eff.get("duration")
                if not eff_dtend_prop and eff_duration_prop:
                    eff_dtend_utc = eff_dtstart_utc + eff_duration_prop.dt
                else:
                    eff_dtend_raw = (eff_dtend_prop.dt if eff_dtend_prop else eff_dtstart_raw)
                    eff_dtend_utc = to_utc_from_prop(eff_dtend_raw, tz_view)

                add_event_to_week(
                    week_events, eff, eff_dtstart_utc, eff_dtend_utc, eff_summary,
                    tz_view, monday, friday
                )
        else:
            add_event_to_week(
                week_events, comp, dtstart_utc, dtend_utc, summary_html,
                tz_view, monday, friday
            )

        # RDATE (zusätzliche Einzeltermine)
        for rdt in _iter_prop_dates(comp, "rdate"):
            r_dt_utc = to_utc_from_prop(rdt, tz_view)
            add_event_to_week(
                week_events, comp, r_dt_utc, r_dt_utc + duration, summary_html,
                tz_view, monday, friday
            )

    generate_html(week_events, start_of_week_local, now_local, OUTPUT_HTML_FILE)
    print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")


if __name__ == "__main__":
    erstelle_kalender_html()
