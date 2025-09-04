#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erstellt eine statische Wochenübersicht (Mo–Fr) als HTML aus einer ICS-Quelle.
- Zielauflösung: 1920×1080 (Full-HD TV)
- Design: Dunkel, an Referenz-Screenshot angelehnt
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
from typing import Any, Dict, List, Set, Tuple

OUTPUT_HTML_FILE = "public/calendar/index.html"

def to_utc_from_prop(dt_raw: date | datetime, tz_local: ZoneInfo) -> datetime:
    """Normalisiert ICS-Zeitwerte zuverlässig nach UTC."""
    if isinstance(dt_raw, date) and not isinstance(dt_raw, datetime):
        # All-Day-Events werden als lokale Mitternacht interpretiert und nach UTC konvertiert
        return tz_local.localize(datetime.combine(dt_raw, time.min)).astimezone(timezone.utc)
    if getattr(dt_raw, "tzinfo", None):
        return dt_raw.astimezone(timezone.utc)
    # Naive Datetimes als lokale Zeit annehmen und nach UTC konvertieren
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
        
        # --- KERNLOGIK: Modifizierte Serieninstanzen (RECURRENCE-ID) verarbeiten ---
        # Sammelt alle "geänderten" Einzeltermine einer Serie
        overrides: Dict[str, Dict[datetime, Any]] = {}
        for component in cal.walk("VEVENT"):
            uid = str(component.get("uid"))
            recurrence_id_prop = component.get("recurrence-id")
            if uid and recurrence_id_prop:
                if uid not in overrides:
                    overrides[uid] = {}
                recurrence_id_utc = to_utc_from_prop(recurrence_id_prop.dt, tz_vienna)
                overrides[uid][recurrence_id_utc] = component # Speichere die komplette Änderung

        # Reguläre Terminverarbeitung
        for component in cal.walk("VEVENT"):
            if component.get("recurrence-id"):
                continue # Überspringe die geänderten Einzeltermine, sie werden später behandelt

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
            
            # Serientermine verarbeiten
            if "rrule" in component:
                rrule = rrulestr(component.get('rrule').to_ical().decode('utf-8'), dtstart=dtstart_utc)
                exdates = {to_utc_from_prop(d.dt, tz_vienna) for ex in component.get("exdate", []) for d in ex.dts}
                
                pad = duration if duration > timedelta(0) else timedelta(days=1)
                search_start = start_of_week_dt - pad
                
                for occ_start_utc in rrule.between(search_start, end_of_week_dt, inc=True):
                    if occ_start_utc in exdates:
                        continue
                    
                    # Prüfen, ob dieses Vorkommen überschrieben wurde
                    uid = str(component.get("uid"))
                    effective_component = overrides.get(uid, {}).get(occ_start_utc, component)
                    
                    # Wenn die geänderte Instanz gelöscht wurde (Confluence-Stil), überspringen
                    if 'Ehemaliger Benutzer (Deleted)' in str(effective_component.get("organizer", "")):
                         continue

                    # Verwende die Daten der effektiven (ggf. geänderten) Komponente
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
            else: # Einmalige Termine
                add_event_to_week(week_events, component, dtstart_utc, dtend_utc, summary_str, tz_vienna, start_of_week_local.date())

        # HTML-Generierung
        generate_html(week_events, start_of_week_local, now_vienna)
        print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")

    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}", file=sys.stderr)
        sys.exit(3)

def add_event_to_week(week_events, component, start_dt, end_dt, summary, tz_vienna, week_start_date):
    """Fügt ein Ereignis den korrekten lokalen Tagen hinzu."""
    start_local = start_dt.astimezone(tz_vienna)
    end_local = end_dt.astimezone(tz_vienna)
    
    is_all_day = isinstance(component.get("dtstart").dt, date) and not isinstance(component.get("dtstart").dt, datetime)
    
    loop_end_date = end_local.date()
    if is_all_day or (end_local.time() == time.min and end_local.date() > start_local.date()):
        loop_end_date -= timedelta(days=1)
        
    current_date = start_local.date()
    while current_date <= loop_end_date:
        if week_start_date <= current_date < week_start_date + timedelta(days=5):
            time_str = "Ganztägig" if is_all_day else start_local.strftime("%H:%M") + " - " + end_local.strftime("%H:%M")
            week_events[current_date].append({"summary": summary, "time": time_str, "is_all_day": is_all_day, "start_time": start_dt})
        current_date += timedelta(days=1)

def generate_html(week_events, start_of_week_local, now_vienna):
    """Erstellt die finale HTML-Datei."""
    calendar_week = start_of_week_local.isocalendar()[1]
    date_range_str = f"{start_of_week_local.strftime('%d.%m.')}–{(start_of_week_local + timedelta(days=4)).strftime('%d.%m.%Y')}"
    
    html_parts = [f"""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=1920, initial-scale=1"><title>Wochenplan</title><style>
:root{{--bg:#121212;--card:#1e1e1e;--text:#e0e0e0;--muted:#888;--border:#333;--radius:12px;--brand:#2f6f3a;--brand2:#3f8b4c;--accent-soft:rgba(79,159,90,.15);}}
*{{box-sizing:border-box;}}html,body{{height:100%;}}
body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial;display:flex;flex-direction:column;min-height:100vh;}}
header.topbar{{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;padding:12px 20px;}}
.topbar-inner{{display:flex;align-items:center;gap:14px;}}
.logo{{background:#fff;border-radius:10px;padding:6px;display:flex;align-items:center;justify-content:center;}}
.logo img{{width:28px;height:28px;display:block;}}
.title{{font-weight:700;font-size:22px;letter-spacing:.2px;}}
.sub{{font-size:13px;opacity:.9;}}
main.container{{padding:16px 20px 8px;flex:1;}}
.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;}}
.day{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:0 6px 18px rgba(0,0,0,.2);display:flex;flex-direction:column;}}
.day-header{{padding:10px 12px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;justify-content:space-between;}}
.day-name{{font-weight:700;}}.day-date{{color:var(--muted);font-size:13px;}}
.day.today{{border-color:var(--brand2);box-shadow:0 0 0 3px var(--accent-soft),0 6px 18px rgba(0,0,0,.2);}}
.events{{padding:10px 12px 12px;display:grid;gap:10px;}}
.event{{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:start;background:rgba(255,255,255,.05);padding:8px;border-radius:6px;border-left:4px solid var(--brand);}}
.event.all-day{{border-left-color:var(--accent);}}
.badge{{font-weight:700;font-size:12px;white-space:nowrap;color:var(--muted);}}
.summary{{font-size:15px;line-height:1.35;}}
.no-events{{color:var(--muted);text-align:center;padding:18px 10px 22px;font-style:italic;}}
footer.foot{{color:#6b7280;font-size:13px;text-align:center;padding:6px 0 12px;margin-top:auto;}}
</style></head><body>
<header class="topbar" role="banner"><div class="topbar-inner">
<div class="logo" aria-hidden="true"><img src="https://cdn.riverty.design/logo/riverty-logomark-green.svg" alt="Logo"></div>
<div><div class="title">Wochenplan (KW {calendar_week})</div><div class="sub">{date_range_str}</div></div>
</div></header>
<main class="container" role="main"><section class="grid" aria-label="Wochentage">"""]

    for i, day_name in enumerate(["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]):
        current_date_local = start_of_week_local.date() + timedelta(days=i)
        events_for_day = sorted(week_events.get(current_date_local, []), key=lambda x: (not x["is_all_day"], x["start_time"]))
        is_today_cls = " today" if current_date_local == now_vienna.date() else ""
        
        html_parts.append(f'<article class="day{is_today_cls}"><div class="day-header"><div class="day-name">{day_name}</div><div class="day-date">{current_date_local.strftime("%d.%m.")}</div></div><div class="events">')
        if not events_for_day:
            html_parts.append('<div class="no-events">–</div>')
        else:
            for ev in events_for_day:
                badge_cls = "badge all" if ev["is_all_day"] else "badge"
                html_parts.append(f'<div class="event"><div class="{badge_cls}">{ev["time"]}</div><div class="summary">{ev["summary"]}</div></div>')
        html_parts.append('</div></article>')

    timestamp_vienna = datetime.now(tz_vienna).strftime("%d.%m.%Y um %H:%M:%S Uhr")
    html_parts.append(f'</section></main><footer class="foot" role="contentinfo">Zuletzt aktualisiert am {timestamp_vienna}</footer></body></html>')
    
    os.makedirs(os.path.dirname(OUTPUT_HTML_FILE), exist_ok=True)
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

if __name__ == "__main__":
    erstelle_kalender_html()
