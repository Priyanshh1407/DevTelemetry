"""Local stand-in for the production scheduler.

In production, .github/workflows/scheduled-alerts.yml calls POST /api/scheduled-tick every
15 minutes. Locally, run this instead:

    python data/clock.py

It ticks the same decision code (api.routes.start_scheduled_dispatch) once a minute, so a
slot is sent at most once even if this and the GitHub cron both run. It replaces the old
loop, which compared the server's local clock to the saved time, ignored Biweekly/Monthly,
and kept "already ran today" only in memory.
"""
import os
import sys
import time

# Ensure Python can find the project packages when run as a script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from api.routes import run_dispatch, start_scheduled_dispatch  # noqa: E402
from core.db import init_db  # noqa: E402

TICK_SECONDS = 60


def tick_once():
    """One scheduler tick: start and run the dispatch if a slot is due."""
    result = start_scheduled_dispatch()
    if result["status"] == "started":
        print(f"⚡ Slot {result['slot']} is due: dispatching (run {result['run_id']})...")
        run_dispatch(result["run_id"])
    return result


def run_scheduler():
    init_db()
    print(f"🕰️ DevTelemetry clock started; checking the schedule every {TICK_SECONDS}s.")
    while True:
        try:
            result = tick_once()
            if result["status"] not in ("not_due", "already_sent"):
                print(f"[tick] {result}")
        except Exception as e:
            print(f"Clock error: {e}")
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    # Ensure stdout can print emojis on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8")
    run_scheduler()
