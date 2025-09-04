import requests
from icalendar import Calendar
from datetime import datetime, date, timezone, timedelta
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
        
        # --- NEU: DEBUG-AUSGABE ALLER GEFUNDENEN TERMINE ---
        print("\n--- DEBUG: Alle gefundenen Termine im ICS File ---")
        has_any_events = False
        for component in cal.walk('VEVENT'):
            has_any_events = True
            summary = component.get('summary')
            start_time = component.get('dtstart').dt
            print(f"  -> Gefunden: '{summary}' am {start_time}")
        if not has_any_events:
            print("  -> KEINE TERMINE im gesamten ICS File gefunden.")
        print("--- ENDE DEBUG ---\n")
        # --- ENDE DEBUG-AUSGABE ---

        today_utc = datetime.now(timezone.utc).date()
        start_of_week = today_utc - timedelta(days=today_utc.weekday())
        end_of_week = start_of_week + timedelta(days=4)

        week_events = {start_of_week + timedelta(days=i): [] for i in range(5)}

        for component in cal.walk('VEVENT'):
            try:
                start_time = component.get('dtstart').dt
                summary_str = html.escape(str(component.get('summary')))
                
                event_date = start_time if isinstance(start_time, date) and not isinstance(start_time, datetime) else start_time.date()

                if start_of_week <= event_date <= end_of_week:
                    is_all_day = not isinstance(start_time, datetime)
                    time_str = "Ganztägig" if is_all_day else start_time.strftime('%H:%M')
                    
                    week_events[event_date].append({
                        'summary': summary_str,
                        'time': time_str,
                        'is_all_day': is_all_day,
                        'start_time': start_time
                    })
            except Exception as e:
                print(f"Fehler beim Verarbeiten eines Termins: {e}")

        html_content = f"""
        <!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Wochenkalender</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 1200px; margin: auto; background: #fff; padding: 20px; box-shadow: 0 0 15px rgba(0,0,0,0.1); border-radius: 8px; }}
            h1 {{ text-align: center; color: #333; }}
            .week-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
            .day-column {{ background-color: #fdfdfd; border: 1px solid #eee; border-radius: 5px; padding: 10px; }}
            .day-header {{ text-align: center; font-weight: bold; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0; margin-bottom: 10px; }}
            .day-header .date {{ font-size: 0.9em; color: #666; font-weight: normal; }}
            .event {{ border-left: 4px solid #007bff; margin-bottom: 8px; padding: 8px; background: #f9f9f9; border-radius: 3px; }}
            .event.all-day {{ border-left-color: #28a745; }}
            .event-time {{ font-weight: bold; font-size: 0.9em; color: #555; }}
            .event-summary {{ font-size: 1em; }}
            .no-events {{ color: #999; text-align: center; padding-top: 20px; }}
            .footer {{ text-align: center; margin-top: 20px; font-size: 0.8em; color: #777; }}
        </style>
        </head><body><div class="container">
        <h1>Arbeitswoche ({start_of_week.strftime('%d.%m')} - {end_of_week.strftime('%d.%m.%Y')})</h1>
        <div class="week-grid">
        """

        days_german = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
        
        for i, day_name in enumerate(days_german):
            current_date = start_of_week + timedelta(days=i)
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

        # KORRIGIERTER FOOTER (mit f-string)
        html_content += f"""
        </div>
        <div class="footer">
            Kalender zuletzt aktualisiert am {datetime.now().strftime('%d.%m.%Y um %H:%M:%S Uhr')}
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
