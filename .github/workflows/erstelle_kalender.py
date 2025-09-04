import requests
from icalendar import Calendar
from datetime import datetime
import html
import os  # <-- NEU
import sys # <-- NEU

# --- KONFIGURATION WIRD JETZT VON GITHUB ACTIONS ÜBERGEBEN ---
# Name der zu erstellenden HTML-Datei
OUTPUT_HTML_FILE = "kalender.html"

def create_calendar_html():
    """Holt eine ICS-Datei, parst sie und erstellt eine einfache HTML-Kalenderseite."""
    
    # 1. ICS-URL aus der Environment-Variable lesen
    ICS_URL = os.getenv("ICS_URL")
    if not ICS_URL:
        print("Fehler: Die Environment-Variable 'ICS_URL' ist nicht gesetzt!")
        print("Stelle sicher, dass das Secret 'ICS_CALENDAR_URL' im Workflow korrekt übergeben wird.")
        sys.exit(1) # Skript mit Fehler beenden

    print(f"Lade Kalender von der bereitgestellten URL...")
    
    try:
        # 2. ICS-Datei herunterladen
        response = requests.get(ICS_URL)
        response.raise_for_status()
        cal_content = response.text
        
        # ... der Rest des Skripts bleibt unverändert ...

        # 3. ICS-Daten parsen
        cal = Calendar.from_ical(cal_content)
        
        events = []
        for component in cal.walk('VEVENT'):
            try:
                start_time = component.get('dtstart').dt
                summary = component.get('summary')
                
                if isinstance(start_time, datetime) and start_time.date() < datetime.now().date():
                    continue
                if isinstance(start_time, datetime.date) and start_time < datetime.now().date():
                    continue

                events.append({
                    'start_time': start_time,
                    'summary': summary
                })
            except Exception as e:
                print(f"Fehler beim Verarbeiten eines Termins: {e}")

        events.sort(key=lambda e: e['start_time'])
        
        html_content = """
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Mein Kalender</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
                .container { max-width: 800px; margin: auto; background: #fff; padding: 20px; box-shadow: 0 0 10px rgba(0,0,0,0.1); border-radius: 8px; }
                h1 { color: #444; border-bottom: 2px solid #eee; padding-bottom: 10px; }
                .event { border-left: 5px solid #007bff; margin-bottom: 15px; padding: 10px 15px; background: #f9f9f9; }
                .event-date { font-weight: bold; font-size: 1.1em; color: #0056b3; }
                .event-summary { font-size: 1em; }
                .footer { text-align: center; margin-top: 20px; font-size: 0.8em; color: #777; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Kalender</h1>
        """

        if not events:
            html_content += "<p>Keine bevorstehenden Termine gefunden.</p>"
        else:
            current_month = ""
            for event in events:
                dt = event['start_time']
                is_all_day = not isinstance(dt, datetime)
                month_year = dt.strftime('%B %Y')
                if month_year != current_month:
                    html_content += f"<h2>{month_year}</h2>"
                    current_month = month_year
                if is_all_day:
                    date_str = dt.strftime('%a, %d.%m.%Y')
                    time_str = "Ganztägig"
                else:
                    date_str = dt.strftime('%a, %d.%m.%Y')
                    time_str = dt.strftime('%H:%M Uhr')
                summary_str = html.escape(str(event['summary']))
                html_content += f"""
                <div class="event">
                    <div class="event-date">{date_str} &ndash; {time_str}</div>
                    <div class="event-summary">{summary_str}</div>
                </div>
                """

        html_content += f"""
                <div class="footer">
                    Kalender zuletzt aktualisiert am {datetime.now().strftime('%d.%m.%Y um %H:%M:%S Uhr')}
                </div>
            </div>
        </body>
        </html>
        """

        with open(OUTPUT_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        print(f"Fertig! Kalender wurde erfolgreich in '{OUTPUT_HTML_FILE}' erstellt.")

    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Herunterladen der ICS-Datei: {e}")
    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")

if __name__ == "__main__":
    create_calendar_html()
