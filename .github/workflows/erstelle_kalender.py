#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erstellt eine statische Wochenübersicht (Mo–Fr) als HTML aus einer ICS-Quelle.

- Zielauflösung: 1920×1080 (Full-HD TV)
- Reines HTML + CSS, kein JavaScript
- Performance: ein eingebetteter CSS-Block, Systemschriften
- Aktueller Tag: dezente grüne Umrandung
- Fußzeile: Sticky-Footer
- Branding: Kopfzeilen-Grün fest im Code

Voraussetzung: Environment-Variable ICS_URL mit der öffentlich erreichbaren ICS-Datei.
Ausgabe: public/calendar/index.html
"""

from __future__ import annotations

import os
import sys
import html
import requests
from typing import Any, Dict, List, Set

from icalendar import Calendar
from dateutil.rrule import rrulestr
from zoneinfo import ZoneInfo
from datetime import datetime, date, time, timedelta


OUTPUT_HTML_FILE = "public/calendar/index.html"


# ---------- Zeit-Helfer (alles in Europe/Vienna) ----------

def to_local(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """
    Normalisiert ICS-Zeitwerte zuverlässig in die lokale Zone (Europe/Vienna):

    - DATE (ganztägig/floating): als lokale Mitternacht interpretieren
    - naive datetime: lokale TZ annehmen
    - tz-aware datetime: in lokale Zone konvertieren
    """
    if hasattr(dt_raw, "tzinfo"):
        # datetime
        if dt_raw.tzinfo is None:
            return dt_raw.replace(tzinfo=tz_local).astimezone(tz_local)
        return dt_raw.astimezone(tz_local)
    # date (ganztägig)
    return datetime.combine(dt_raw, time.min, tzinfo=tz_local)


def is_all_day_component(component) -> bool:
    """True, wenn dtstart ein reines DATE ist (klassisches All-Day-Event)."""
    dtstart = component.get("dtstart")
    if not dtstart:
        return False
    val = dtstart.dt
    return isinstance(val, date) and not isinstance(val, datetime)


def split_event_across_days(
    week_events: Dict[date, List[Dict[str, Any]]],
    component,
    start_local: datetime,
    end_local: datetime,
    summary: str,
    valid_days_local: Set[date],
) -> None:
    """
    Teilt ein Event auf lokale Kalendertage auf und erzeugt passende Zeit-Badges.

    Regeln:
    - All-Day: „Ganztägig“ an allen betroffenen Tagen
    - Ein-Tages-Zeit-Termin: „HH:MM–HH:MM“
    - Mehrtägige Zeit-Termine:
        * erster Tag: „Start: HH:MM“ (bzw. „HH:MM–00:00“, wenn bis Mitternacht)
        * Zwischentage: „Ganztägig“
        * letzter Tag: „Ende: HH:MM“ (falls > 00:00)
    - DTEND ist exklusiv: endet ein Termin exakt 00:00 und hat Dauer > 0, zählt der Vortag als letzter voller Tag
    """
    all_day = is_all_day_component(component)

    loop_end_date = end_local.date()
    if (all_day and end_local.time() == time.min) or (
        not all_day and end_local.time() == time.min and end_local.date() > start_local.date()
    ):
        loop_end_date -= timedelta(days=1)

    same_day = start_local.date() == end_local.date()

    current = start_local.date()
    while current <= loop_end_date:
        if current in valid_days_local:
            if all_day:
                time_str = "Ganztägig"
            elif same_day:
                time_str = f"{start_local:%H:%M}–{end_local:%H:%M}"
            elif current == start_local.date():
                if end_local.time() == time.min and end_local.date() > start_local.date():
                    time_str = "Ganztägig" if start_local.time() == time.min else f"{start_local:%H:%M}–00:00"
                else:
                    time_str = f"Start: {start_local:%H:%M}"
            elif current == loop_end_date:
                time_str = f"Ende: {end_local:%H:%M}" if end_local.time() > time.min else "Ganztägig"
            else:
                time_str = "Ganztägig"

            week_events[current].append(
                {
                    "summary": summary,
                    "time": time_str,
                    "is_all_day": all_day or time_str == "Ganztägig",
                    "start_time": start_local,
                }
            )
        current += timedelta(days=1)


# ---------- Hauptlogik ----------

def erstelle_kalender_html() -> None:
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")

    try:
        response = requests.get(ics_url, timeout=30)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)  # Bytes sind robust
    except Exception as e:
        print(f"Fehler beim Laden/Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    tz_vienna = ZoneInfo("Europe/Vienna")
    now_vienna = datetime.now(tz_vienna)

    # Wochenfenster lokal (Mo 00:00 – Fr 23:59:59)
    start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=now_vienna.weekday()
    )
    end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)

    week_days_local: List[date] = [(start_of_week_local + timedelta(days=i)).date() for i in range(5)]
    valid_day_set = set(week_days_local)

    week_events: Dict[date, List[Dict[str, Any]]] = {d: [] for d in week_days_local}

    # RECURRENCE-ID Overrides (lokale Zeit als Schlüssel)
    overrides: Dict[str, Dict[datetime, Any]] = {}
    for comp in cal.walk("VEVENT"):
        rec_id = comp.get("recurrence-id")
        if rec_id:
            uid = str(comp.get("uid") or "")
            if not uid:
                continue
            rec_id_local = to_local(rec_id.dt, tz_vienna)
            overrides.setdefault(uid, {})[rec_id_local] = comp

    # Dubletten-Filter: pro UID die bereits hinzugefügten lokalen Startzeiten
    occurrences_seen: Dict[str, Set[datetime]] = {}

    def add_occurrence(component, s_local: datetime, e_local: datetime, summary: str) -> None:
        uid = str(component.get("uid") or "")
        if uid:
            seen = occurrences_seen.setdefault(uid, set())
            if s_local in seen:
                return
            seen.add(s_local)
        split_event_across_days(week_events, component, s_local, e_local, summary, valid_day_set)

    def summary_of(component) -> str:
        raw = component.get("summary")
        return html.escape(str(raw) if raw is not None else "Ohne Titel")

    # Termine verarbeiten
    for component in cal.walk("VEVENT"):
        # Overrides wurden schon erfasst; Basis-Events hier verarbeiten
        if component.get("recurrence-id"):
            continue

        try:
            status = str(component.get("status") or "").upper()
            if status == "CANCELLED":
                continue

            summary_str = summary_of(component)

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

            # EXDATE -> lokal
            exdates: Set[datetime] = set()
            ex_prop = component.get("exdate")
            ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
            for ex in ex_list:
                for d in ex.dts:
                    exdates.add(to_local(d.dt, tz_vienna))

            uid = str(component.get("uid") or "")

            # RRULE (mit Overrides) expandieren – alles in lokaler Zeit
            rrule_prop = component.get("rrule")
            if rrule_prop:
                rule = rrulestr(rrule_prop.to_ical().decode("utf-8"), dtstart=start_local)

                # Suchfenster leicht erweitern (Dauer-Puffer), damit über die Wochenkante ragende Events gefunden werden
                pad = duration if duration > timedelta(0) else timedelta(0)
                search_start = start_of_week_local - pad
                search_end = end_of_week_local

                for occ_start_local in rule.between(search_start, search_end, inc=True):
                    if occ_start_local in exdates:
                        continue

                    eff_component = overrides.get(uid, {}).get(occ_start_local, component)
                    eff_summary = summary_of(eff_component)

                    eff_dtstart_raw = eff_component.get("dtstart").dt
                    eff_start_local = to_local(eff_dtstart_raw, tz_vienna)

                    eff_dtend_prop = eff_component.get("dtend")
                    eff_duration_prop = eff_component.get("duration")
                    if not eff_dtend_prop and eff_duration_prop:
                        eff_end_local = eff_start_local + eff_duration_prop.dt
                    else:
                        eff_dtend_raw = eff_dtend_prop.dt if eff_dtend_prop else eff_dtstart_raw
                        eff_end_local = to_local(eff_dtend_raw, tz_vienna)

                    add_occurrence(eff_component, eff_start_local, eff_end_local, eff_summary)
            else:
                # Einzeltermin
                add_occurrence(component, start_local, end_local, summary_str)

            # RDATE (zusätzliche Vorkommen)
            rdate_prop = component.get("rdate")
            rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
            for r in rdate_list:
                for d in r.dts:
                    r_start_local = to_local(d.dt, tz_vienna)
                    if r_start_local in exdates:
                        continue
                    r_end_local = r_start_local + duration
                    add_occurrence(component, r_start_local, r_end_local, summary_str)

        except Exception as e:
            print(f"Fehler beim Verarbeiten eines Termins ('{summary_of(component)}'): {e}", file=sys.stderr)

    # ---------- HTML-Ausgabe ----------
    calendar_week = start_of_week_local.isocalendar()[1]
    monday_vie = start_of_week_local.date()
    friday_vie = (start_of_week_local + timedelta(days=4)).date()

    def fmt_short(d: date) -> str:
        return d.strftime("%d.%m.")

    date_range_str = f"{fmt_short(monday_vie)}–{fmt_short(friday_vie)}"
    today_vie_date = now_vienna.date()
    timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")

    html_parts: List[str] = []
    html_parts.append(
        f"""<!DOCTYPE html>
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
  --brand: #3f6f3a;
  --brand2: #3f6f3a;
  --accent: #4f9f5a;
  --accent-soft: #eaf6ee;
}}
* {{ box-sizing: border-box; }}
html, body {{ height: 100%; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial;
  display: flex;
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
main.container {{ padding: 16px 20px 8px; flex: 1; }}
.grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }}
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
  margin-top: auto;
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
  <section class="grid" aria-label="Wochentage">"""
    )

    days_german = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    for i, day_name in enumerate(days_german):
        current_date_local = week_days_local[i]
        events_for_day = week_events.get(current_date_local, [])
        events_for_day.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))
        is_today_cls = " today" if current_date_local == now_vienna.date() else ""

        html_parts.append(
            f"""
    <article class="day{is_today_cls}" aria-labelledby="d{i}-label">
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
                    f"""
        <div class="event">
          <div class="{badge_cls}">{ev['time']}</div>
          <div class="summary">{ev['summary']}</div>
        </div>"""
                )

        html_parts.append(
            """
      </div>
    </article>"""
        )

    timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")
    html_parts.append(
        f"""
  </section>
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
