import sqlite3
import time
from datetime import datetime
import os
import alert_worker  # We import your worker script directly!

def run_scheduler():
    print("🕰️ DevTelemetry Clock Started. Running in background...")
    
    db_path = os.path.join(os.path.dirname(__file__), 'usage.db')
    
    # We keep track of the last time we ran the job so we don't spam 
    # the team 60 times within the same scheduled minute!
    last_run_date = None 

    while True:
        try:
            # 1. Check the current real-world time
            now = datetime.now()
            current_day = now.strftime("%A")  # e.g., "Friday"
            current_time = now.strftime("%H:%M")  # e.g., "17:00"
            current_date_str = now.strftime("%Y-%m-%d")

            # 2. Check the database for the Manager's schedule
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT frequency, day, time FROM alert_settings WHERE id = 1")
            settings = cursor.fetchone()
            conn.close()

            if settings:
                db_freq = settings['frequency']
                db_day = settings['day']
                db_time = settings['time']

                # 3. Evaluate the Schedule
                should_run = False
                
                if db_freq == "Daily" and current_time == db_time:
                    should_run = True
                elif db_freq == "Weekly" and current_day == db_day and current_time == db_time:
                    should_run = True
                # (You can easily add Biweekly or Monthly logic here later)

                # 4. Pull the Trigger!
                if should_run and last_run_date != current_date_str:
                    print(f"\n⚡ [SYSTEM TRIGGER] Schedule matched: {db_freq} at {db_time}")
                    alert_worker.run_weekly_telemetry_check()
                    last_run_date = current_date_str  # Mark as done for today
                    print("✅ Job Complete. Resuming standby...\n")

            # Sleep for 30 seconds before checking the clock again
            time.sleep(30)

        except Exception as e:
            print(f"Clock Error: {e}")
            time.sleep(30) # If the DB is locked, wait and try again

if __name__ == "__main__":
    run_scheduler()