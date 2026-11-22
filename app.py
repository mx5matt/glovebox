import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

APP_VERSION = "0.1.1"
APP_TITLE = "Glovebox"
APP_INITIALS = "GB"
DB = os.environ.get("APP_DB", "/data/app.sqlite3")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# Used only to sign flash messages. No accounts or sensitive sessions exist.
app.secret_key = os.environ.get("SECRET_KEY", "glovebox-local-flash-messages")


@contextmanager
def db():
    folder = os.path.dirname(DB)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)


@app.before_request
def ensure_database():
    init_db()


@app.context_processor
def inject_metadata():
    return {"app_version": APP_VERSION, "app_title": APP_TITLE, "app_initials": APP_INITIALS}


def to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_float(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def to_date(value):
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


@app.get("/health")
def health():
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    return jsonify(status="ok", version=APP_VERSION)


def changelog_sections():
    try:
        with open(os.path.join(BASE_DIR, "CHANGELOG.md"), encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return []
    sections, current = [], None
    for line in content.splitlines():
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "groups": []}
            sections.append(current)
        elif line.startswith("### ") and current is not None:
            current["groups"].append({"title": line[4:].strip(), "items": []})
        elif line.startswith("- ") and current is not None:
            if not current["groups"]:
                current["groups"].append({"title": "Changes", "items": []})
            current["groups"][-1]["items"].append(line[2:].strip().replace("`", ""))
    return sections


@app.get("/changelog")
def changelog():
    return render_template("changelog.html", sections=changelog_sections())

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    year INTEGER,
    make TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    odometer INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    odometer INTEGER,
    cost REAL,
    notes TEXT NOT NULL DEFAULT ''
);
"""


@app.get("/")
def index():
    with db() as conn:
        vehicles = [dict(r) for r in conn.execute(
            "SELECT v.*, COALESCE(SUM(e.cost), 0) AS total_cost, COUNT(e.id) AS event_count "
            "FROM vehicles v LEFT JOIN events e ON e.vehicle_id = v.id "
            "GROUP BY v.id ORDER BY v.name COLLATE NOCASE")]
        events = [dict(r) for r in conn.execute(
            "SELECT e.*, v.name AS vehicle_name FROM events e JOIN vehicles v ON v.id = e.vehicle_id "
            "ORDER BY e.event_date DESC, e.id DESC LIMIT 200")]
    return render_template("index.html", vehicles=vehicles, events=events)


@app.post("/vehicles")
def add_vehicle():
    name = request.form.get("name", "").strip()
    make = request.form.get("make", "").strip()
    model = request.form.get("model", "").strip()
    year_raw = request.form.get("year", "").strip()
    year = to_int(year_raw) if year_raw else None
    odometer_raw = request.form.get("odometer", "").strip()
    odometer = to_int(odometer_raw) if odometer_raw else 0
    if (not name or len(name) > 80 or len(make) > 60 or len(model) > 60
            or (year_raw and (year is None or not 1886 <= year <= date.today().year + 1))
            or odometer is None or not 0 <= odometer <= 10_000_000):
        flash("Enter a vehicle name, an optional valid year and a non-negative odometer reading.")
        return redirect(dashboard_return(url_for("index")))
    with db() as conn:
        conn.execute("INSERT INTO vehicles(name, year, make, model, odometer) VALUES (?, ?, ?, ?, ?)",
                     (name, year, make, model, odometer))
    return redirect(dashboard_return(url_for("index")))


@app.post("/events")
def add_event():
    vehicle_id = to_int(request.form.get("vehicle_id"))
    event_date = to_date(request.form.get("event_date"))
    event_type = request.form.get("event_type", "").strip()
    notes = request.form.get("notes", "").strip()
    odometer_raw = request.form.get("odometer", "").strip()
    odometer = to_int(odometer_raw) if odometer_raw else None
    cost_raw = request.form.get("cost", "").strip()
    cost = to_float(cost_raw) if cost_raw else None
    invalid = (vehicle_id is None or event_date is None or event_date > date.today()
               or not event_type or len(event_type) > 80 or len(notes) > 2000
               or (odometer_raw and (odometer is None or not 0 <= odometer <= 10_000_000))
               or (cost_raw and (cost is None or not 0 <= cost <= 10_000_000)))
    with db() as conn:
        vehicle = None if vehicle_id is None else conn.execute(
            "SELECT odometer FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        if invalid or vehicle is None:
            flash("Choose a vehicle and enter a date (not in the future), a type, and non-negative odometer and cost values.")
            return redirect(dashboard_return(url_for("index")))
        conn.execute("INSERT INTO events(vehicle_id, event_date, event_type, odometer, cost, notes) VALUES (?, ?, ?, ?, ?, ?)",
                     (vehicle_id, event_date.isoformat(), event_type, odometer,
                      round(cost, 2) if cost is not None else None, notes))
        if odometer is not None and odometer > vehicle["odometer"]:
            conn.execute("UPDATE vehicles SET odometer = ? WHERE id = ?", (odometer, vehicle_id))
    return redirect(dashboard_return(url_for("index")))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080)

# Safe same-application return target. External, protocol-relative and control-character URLs are rejected.
def dashboard_return(default='/'):
    from urllib.parse import urlsplit
    target = request.form.get('return_to', '')
    if not target or not target.startswith('/') or target.startswith('//') or '\\' in target:
        return default
    if any(ord(c) < 32 or ord(c) == 127 for c in target):
        return default
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != '/':
        return default
    return target
