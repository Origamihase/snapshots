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
from datetime import datetime, date, time, timezone, timedelta

OUTPUT_HTML_FILE = "public/calendar/index.html"


# ----------------------------- Zeit-Helfer -----------------------------

def to_utc(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """
    Normalisiert ICS-Zeitwerte zuverlässig nach UTC.

    - DATE (ganztägig/floating): als lokale Mitternacht interpretieren und nach UTC konvertieren
    - naive datetime: als lokale Zeit interpretieren und nach UTC konvertieren
    - tz-aware datetime: direkt nach UTC konvertieren
    """
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        return datetime.combine(dt_raw, time.min, tzinfo=tz_local).astimezone(timezone.utc)
    if isinstance(dt_raw, datetime):
        if dt_raw.tzinfo is None:
            return dt_raw.replace(tzinfo=tz_local).astimezone(timezone.utc)
        return dt_raw.astimezone(timezone.utc)
    raise TypeError("Unsupported dt type")


def utc_to_local(dt_utc: datetime, tz_local: ZoneInfo) -> datetime:
    return dt_utc.astimezone(tz_local)


def is_all_day_component(component) -> bool:
    dtstart = component.get("dtstart")
    if not dtstart:
        return False
    val = dtstart.dt
    return isinstance(val, date) and not isinstance(val, datetime)


# --------------------------- Rendering-Helfer --------------------------

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
    """
    all_day = is_all_day_component(component)

    loop_end_date = end_local.date()
    # DTEND ist exklusiv: endet exakt 00:00 und Dauer > 0 => letzter voller Tag ist Vortag
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


# ------------------------------- Main ---------------------------------

def erstelle_kalender_html() -> None:
    ics_url = os.getenv("ICS_URL")
    if not ics_url:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")

    try:
        resp = requests.get(ics_url, timeout=30)
        resp.raise_for_status()
        # Viele Confluence/Atlassian-Exports enthalten UTF-8-Text.
        # icalendar kann sowohl Bytes als auch str verarbeiten – hier ist str stabiler für manche Server.
        cal = Calendar.from_ical(resp.text)
    except Exception as e:
        print(f"Fehler beim Laden/Parsen der ICS-Datei: {e}", file=sys.stderr)
        sys.exit(2)

    tz_vienna = ZoneInfo("Europe/Vienna")
    now_vienna = datetime.now(tz_vienna)

    # Wochenfenster lokal bestimmen (Mo 00:00 – Fr 23:59:59), dann auch in UTC bereithalten
    start_of_week_local = now_vienna.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=now_vienna.weekday()
    )
    end_of_week_local = start_of_week_local + timedelta(days=4, hours=23, minutes=59, seconds=59)

    start_of_week_utc = start_of_week_local.astimezone(timezone.utc)
    end_of_week_utc = end_of_week_local.astimezone(timezone.utc)

    week_days_local: List[date] = [(start_of_week_local + timedelta(days=i)).date() for i in range(5)]
    valid_day_set = set(week_days_local)

    week_events: Dict[date, List[Dict[str, Any]]] = {d: [] for d in week_days_local}

    # Dubletten pro Tag vermeiden: (summary_lower, start_utc_iso)
    per_day_seen: Dict[date, Set[tuple]] = {d: set() for d in week_days_local}

    def add_unique(component, start_utc: datetime, end_utc: datetime, summary: str) -> None:
        start_local = utc_to_local(start_utc, tz_vienna)
        end_local = utc_to_local(end_utc, tz_vienna)

        # Wir deduplizieren pro Tag basierend auf (summary, exakter Startzeitpunkt in UTC)
        cur = start_local.date()
        last = end_local.date()
        if end_local.time() == time.min and end_local.date() > start_local.date():
            last -= timedelta(days=1)

        key_tuple = (summary.lower(), start_utc.isoformat())

        while cur <= last:
            if cur in per_day_seen and key_tuple in per_day_seen[cur]:
                # Bereits vorhanden – keine zweite Darstellung
                pass
            else:
                split_event_across_days(week_events, component, start_local, end_local, summary, valid_day_set)
                per_day_seen[cur].add(key_tuple)
                break  # split_event_across_days fügt ohnehin alle Tage hinzu
            cur += timedelta(days=1)

    # RECURRENCE-Overrides (RECURRENCE-ID)
    overrides: Dict[str, Dict[datetime, Any]] = {}
    for comp in cal.walk("VEVENT"):
        rec_id = comp.get("recurrence-id")
        if rec_id:
            uid = str(comp.get("uid") or "")
            if not uid:
                continue
            rec_id_utc = to_utc(rec_id.dt, tz_vienna)
            overrides.setdefault(uid, {})[rec_id_utc] = comp

    # VEVENTS expandieren
    for component in cal.walk("VEVENT"):
        if component.get("recurrence-id"):
            continue  # schon in overrides

        try:
            status = str(component.get("status") or "").upper()
            if status == "CANCELLED":
                continue

            summary_raw = component.get("summary")
            summary_str = html.escape(str(summary_raw) if summary_raw is not None else "Ohne Titel")

            # Start/Ende nach UTC
            dtstart_raw = component.get("dtstart").dt
            start_utc = to_utc(dtstart_raw, tz_vienna)

            dtend_prop = component.get("dtend")
            duration_prop = component.get("duration")
            if not dtend_prop and duration_prop:
                end_utc = start_utc + duration_prop.dt
            else:
                dtend_raw = dtend_prop.dt if dtend_prop else dtstart_raw
                end_utc = to_utc(dtend_raw, tz_vienna)

            duration = end_utc - start_utc

            # EXDATE in UTC
            exdates_utc: Set[datetime] = set()
            ex_prop = component.get("exdate")
            ex_list = ex_prop if isinstance(ex_prop, list) else ([ex_prop] if ex_prop else [])
            for ex in ex_list:
                for d in ex.dts:
                    exdates_utc.add(to_utc(d.dt, tz_vienna))

            uid = str(component.get("uid") or "")

            # RRULE-Expansion (UTC)
            rrule_prop = component.get("rrule")
            if rrule_prop:
                rule = rrulestr(rrule_prop.to_ical().decode("utf-8"), dtstart=start_utc)
                pad = duration if duration > timedelta(0) else timedelta(0)
                search_start = start_of_week_utc - pad
                search_end = end_of_week_utc

                for occ_start_utc in rule.between(search_start, search_end, inc=True):
                    if occ_start_utc in exdates_utc:
                        continue

                    eff_comp = overrides.get(uid, {}).get(occ_start_utc, component)
                    eff_summary = html.escape(str(eff_comp.get("summary") or "Ohne Titel"))

                    eff_dtstart_raw = eff_comp.get("dtstart").dt
                    eff_start_utc = to_utc(eff_dtstart_raw, tz_vienna)

                    eff_dtend_prop = eff_comp.get("dtend")
                    eff_duration_prop = eff_comp.get("duration")
                    if not eff_dtend_prop and eff_duration_prop:
                        eff_end_utc = eff_start_utc + eff_duration_prop.dt
                    else:
                        eff_dtend_raw = eff_dtend_prop.dt if eff_dtend_prop else eff_dtstart_raw
                        eff_end_utc = to_utc(eff_dtend_raw, tz_vienna)

                    add_unique(eff_comp, eff_start_utc, eff_end_utc, eff_summary)
            else:
                # Einzeltermin
                add_unique(component, start_utc, end_utc, summary_str)

            # RDATE (zusätzliche Vorkommen)
            rdate_prop = component.get("rdate")
            rdate_list = rdate_prop if isinstance(rdate_prop, list) else ([rdate_prop] if rdate_prop else [])
            for r in rdate_list:
                for d in r.dts:
                    r_start_utc = to_utc(d.dt, tz_vienna)
                    if r_start_utc in exdates_utc:
                        continue
                    r_end_utc = r_start_utc + duration
                    add_unique(component, r_start_utc, r_end_utc, summary_str)

        except Exception as e:
            # Fehler nicht eskalieren – einzelne defekte Events dürfen die Seite nicht verhindern
            print(f"Fehler beim Verarbeiten eines Termins ('{component.get('summary')}'): {e}", file=sys.stderr)

    # ------------------------------- HTML -------------------------------

    calendar_week = start_of_week_local.isocalendar()[1]
    monday_vie = start_of_week_local.date()
    friday_vie = (start_of_week_local + timedelta(days=4)).date()

    def fmt_short(d: date) -> str:
        return d.strftime("%d.%m.")

    date_range_str = f"{fmt_short(monday_vie)}–{fmt_short(friday_vie)}"
    timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")

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
  <section class="grid" aria-label="Wochentage">""")

    days_german = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
    for i, day_name in enumerate(days_german):
        current_date_local = week_days_local[i]
        events_for_day = week_events.get(current_date_local, [])
        events_for_day.sort(key=lambda x: (not x["is_all_day"], x["start_time"], x["summary"].lower()))
        is_today_cls = " today" if current_date_local == now_vienna.date() else ""

        html_parts.append(f"""
    <article class="day{is_today_cls}" aria-labelledby="d{i}-label">
      <div class="day-header">
        <div id="d{i}-label" class="day-name">{day_name}</div>
        <div class="day-date">{current_date_local.strftime('%d.%m.')}</div>
      </div>
      <div class="events">""")

        if not events_for_day:
            html_parts.append('<div class="no-events">–</div>')
        else:
            for ev in events_for_day:
                badge_cls = "badge all" if ev["is_all_day"] else "badge"
                html_parts.append(f"""
        <div class="event">
          <div class="{badge_cls}">{ev['time']}</div>
          <div class="summary">{ev['summary']}</div>
        </div>""")

        html_parts.append("""
      </div>
    </article>""")

    html_parts.append(f"""
  </section>
</main>
<footer class="foot" role="contentinfo">
  Kalender zuletzt aktualisiert am {timestamp_vienna}
</footer>
</body>
</html>""")

    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

    print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")


if __name__ == "__main__":
    erstelle_kalender_html()
