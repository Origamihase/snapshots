import requests
from icalendar import Calendar, vRecur
from datetime import datetime, date, timezone, timedelta, time
from dateutil.rrule import rrulestr
from zoneinfo import ZoneInfo
import html
import os
import sys

OUTPUT_HTML_FILE = "public/calendar/index.html"

def create_calendar_html():
    ICS_URL = os.getenv("ICS_URL")
    if not ICS_URL:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!")
        sys.exit(1)

    print("Lade Kalender von der bereitgestellten URL...")
    
    try:
        response = requests.get(ICS_URL)
        response.raise_for_status()
        cal_content = response.text
        
        cal = Calendar.from_ical(cal_content)
        
        today_utc = datetime.now(timezone.utc)
        start_of_week_dt = today_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=today_utc.weekday())
        end_of_week_dt = start_of_week_dt + timedelta(days=4, hours=23, minutes=59, seconds=59)

        week_events = {start_of_week_dt.date() + timedelta(days=i): [] for i in range(5)}

        for component in cal.walk('VEVENT'):
            summary_str = ""
            try:
                summary_str = html.escape(str(component.get('summary')))
                dtstart_raw = component.get('dtstart').dt
                
                dtend_raw = component.get('dtend').dt if component.get('dtend') else dtstart_raw
                
                if isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime):
                    dtstart = datetime.combine(dtstart_raw, time.min, tzinfo=timezone.utc)
                else:
                    dtstart = dtstart_raw.astimezone(timezone.utc) if dtstart_raw.tzinfo else dtstart_raw.replace(tzinfo=timezone.utc)

                if isinstance(dtend_raw, date) and not isinstance(dtend_raw, datetime):
                    dtend = datetime.combine(dtend_raw, time.min, tzinfo=timezone.utc)
                else:
                    dtend = dtend_raw.astimezone(timezone.utc) if dtend_raw.tzinfo else dtend_raw.replace(tzinfo=timezone.utc)
                
                duration = dtend - dtstart

                def add_event_to_week(start_dt, end_dt):
                    loop_end_date = end_dt.date()
                    is_all_day_event = (isinstance(component.get('dtstart').dt, date) and not isinstance(component.get('dtstart').dt, datetime))
                    if end_dt.time() == time.min and duration.days > 0:
                         loop_end_date -= timedelta(days=1)

                    current_date = start_dt.date()
                    while current_date <= loop_end_date:
                        if start_of_week_dt.date() <= current_date <= (start_of_week_dt.date() + timedelta(days=4)):
                            if current_date in week_events:
                                time_str = "Ganztägig" if is_all_day_event else start_dt.strftime('%H:%M')
                                week_events[current_date].append({
                                    'summary': summary_str,
                                    'time': time_str,
                                'is_all_day': is_all_day_event,
                                'start_time': start_dt
                                })
                        current_date += timedelta(days=1)

                if 'RRULE' in component:
                    rrule = rrulestr(component.get('rrule').to_ical().decode(), dtstart=dtstart)
                    search_end_dt = end_of_week_dt + timedelta(days=duration.days)
                    occurrences = rrule.between(start_of_week_dt, search_end_dt, inc=True)
                    for occ_start_dt in occurrences:
                        occ_end_dt = occ_start_dt + duration
                        add_event_to_week(occ_start_dt, occ_end_dt)
                else:
                    add_event_to_week(dtstart, dtend)

            except Exception as e:
                print(f"Fehler beim Verarbeiten eines Termins ('{summary_str}'): {e}")
        
        calendar_week = start_of_week_dt.isocalendar()[1]
        
        timestamp_vienna = datetime.now(ZoneInfo("Europe/Vienna")).strftime('%d.%m.%Y um %H:%M:%S Uhr')

        html_content = f"""
        <!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Wochenplan</title>
        <style>
            :root {{
                --main-green: #4d824d; --light-green: #6aa84f; --dark-green: #386638;
                --text-color: #333; --light-text-color: #eee; --bg-color: #f4f4f9;
                --container-bg: #fff; --border-color: #eee; --header-bg: #fdfdfd;
            }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 0; }}
            .top-bar {{ background-color: var(--main-green); padding: 15px 20px; color: var(--light-text-color); text-align: center; font-size: 1.8em; font-weight: bold; margin-bottom: 20px; }}
            .container {{ max-width: 95%; /* ANGEPASST: Nutzt mehr Breite */ margin: 20px auto; background: var(--container-bg); padding: 20px; box-shadow: 0 0 15px rgba(0,0,0,0.1); border-radius: 8px; }}
            .week-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
            .day-column {{ background-color: var(--header-bg); border: 1px solid var(--border-color); border-radius: 5px; padding: 10px; min-height: 150px; }}
            .day-header {{ text-align: center; font-weight: bold; padding-bottom: 10px; border-bottom: 2px solid var(--border-color); margin-bottom: 10px; }}
            .day-header .date {{ font-size: 0.9em; color: #666; font-weight: normal; }}
            .event {{ margin-bottom: 8px; padding: 8px; background: #f9f9f9; border-radius: 3px; }}
            .event.all-day {{ border-left: 4px solid var(--dark-green); }}
            .event:not(.all-day) {{ border-left: 4px solid var(--light-green); }}
            .event-time {{ font-weight: bold; font-size: 0.9em; color: #555; }}
            .event-summary {{ font-size: 1em; }}
            .no-events {{ color: #999; text-align: center; padding-top: 20px; }}
            .footer {{ text-align: center; margin-top: 20px; font-size: 0.8em; color: #777; }}
        </style>
        </head><body>
        <div class="top-bar">Wochenplan (KW {calendar_week})</div>
        <div class="container">
        <div class="week-grid">
        """
        days_german = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
        for i, day_name in enumerate(days_german):
            current_date = start_of_week_dt.date() + timedelta(days=i)
            events_for_day = week_events.get(current_date, [])
            events_for_day.sort(key=lambda x: (not x['is_all_day'], x['start_time']))
            html_content += f"""
            <div class="day-column">
                <div class="day-header">{day_name}<div class="date">{current_date.strftime('%d.%m.')}</div></div>
            """
            if not events_for_day:
                html_content += '<div class="no-events">-</div>'
            else:
                for event in events_for_day:
                    event_class = "event all-day" if event['is_all_day'] else "event"
                    html_content += f"""
                    <div class="{event_class}">
                        <div class="event-time">{event['time']}</div>
                        <div class="event-summary">{event['summary']}</div>
                    </div>
                    """
            html_content += "</div>"
        html_content += f"""
        </div>
        <div class="footer">
            Kalender zuletzt aktualisiert am {timestamp_vienna}
        </div>
        </div></body></html>
        """

        with open(OUTPUT_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Fertig! Wochenkalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")

    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Herunterladen der ICS-Datei: {e}")
    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")

if __name__ == "__main__":
    create_calendar_html()
