import os
from flask import Flask, render_template, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from database import init_db, get_all_reports, get_last_report_date
from scraper import process_reports
from datetime import datetime, timedelta

app = Flask(__name__)

last_update = None


def scheduled_update():
    """Run daily update - fetches last 2 days to catch anything missed."""
    global last_update
    print(f"[{datetime.now()}] Running scheduled update...")
    process_reports(days_back=2)
    last_update = datetime.now().strftime("%Y-%m-%d %H:%M")


def ensure_fresh_data():
    """On first request, check if data is stale and refresh if needed."""
    global last_update
    if last_update:
        return
    last_report = get_last_report_date()
    if not last_report or last_report < (datetime.now() - timedelta(hours=12)).isoformat():
        print("Data is stale, refreshing...")
        process_reports(days_back=7)
        last_update = datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        last_update = "from cache"


@app.route("/")
def index():
    ensure_fresh_data()
    return render_template("index.html")


@app.route("/api/reports")
def api_reports():
    ensure_fresh_data()
    reports = get_all_reports(limit=200)
    return jsonify({"reports": reports, "last_update": last_update})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    scheduled_update()
    return jsonify({"status": "ok", "last_update": last_update})


# Initialize DB on import (needed for gunicorn)
init_db()

# Start scheduler - run at 7:00 AM ET (after market opens pre-market filings)
scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_update, "cron", hour=7, minute=0)
scheduler.start()
print("Scheduler started - daily update at 07:00")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
