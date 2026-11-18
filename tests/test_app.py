from datetime import date, timedelta

from tests.common import check_common, cleanup, client, query

check_common()

# Normal path.
client.post("/vehicles", data={"name": "Example Roadster", "year": "2008", "make": "Example", "model": "Roadster", "odometer": "90000"})
assert query("SELECT name, year, make, model, odometer FROM vehicles") == [("Example Roadster", 2008, "Example", "Roadster", 90000)]

# Invalid vehicles and boundaries.
for bad in ({"name": ""}, {"name": "Car", "year": "1885"}, {"name": "Car", "year": str(date.today().year + 2)},
            {"name": "Car", "year": "abc"}, {"name": "Car", "odometer": "-1"}):
    client.post("/vehicles", data=bad)
assert len(query("SELECT id FROM vehicles")) == 1, "invalid vehicle was stored"

vehicle_id = str(query("SELECT id FROM vehicles")[0][0])

# A newer, higher reading updates the vehicle odometer.
client.post("/events", data={"vehicle_id": vehicle_id, "event_date": "2026-01-15", "event_type": "Service", "odometer": "91000", "cost": "250.50"})
assert query("SELECT odometer FROM vehicles") == [(91000,)]

# A lower historical reading is recorded but does not reduce the odometer.
client.post("/events", data={"vehicle_id": vehicle_id, "event_date": "2025-01-15", "event_type": "Inspection", "odometer": "85000", "cost": "60"})
assert query("SELECT odometer FROM vehicles") == [(91000,)]

# Invalid records are rejected without changing data.
future = (date.today() + timedelta(days=1)).isoformat()
for bad in ({"vehicle_id": "999999", "event_date": "2026-01-01", "event_type": "Service"},
            {"vehicle_id": vehicle_id, "event_date": "2026-13-40", "event_type": "Service"},
            {"vehicle_id": vehicle_id, "event_date": future, "event_type": "Service"},
            {"vehicle_id": vehicle_id, "event_date": "2026-01-01", "event_type": ""},
            {"vehicle_id": vehicle_id, "event_date": "2026-01-01", "event_type": "Repair", "cost": "-5"},
            {"vehicle_id": vehicle_id, "event_date": "2026-01-01", "event_type": "Repair", "cost": "nan"},
            {"vehicle_id": vehicle_id, "event_date": "2026-01-01", "event_type": "Repair", "odometer": "abc"}):
    client.post("/events", data=bad)
assert len(query("SELECT id FROM events")) == 2, "invalid event was stored"
assert query("SELECT odometer FROM vehicles") == [(91000,)]

# Totals and formatting are visible.
page = client.get("/").data
assert b"91,000 km" in page and b"$310.50" in page

# Notes are escaped.
client.post("/events", data={"vehicle_id": vehicle_id, "event_date": "2026-02-01", "event_type": "Note", "notes": "<b>bold</b>"})
page = client.get("/").data
assert b"&lt;b&gt;bold&lt;/b&gt;" in page and b"<b>bold</b>" not in page

cleanup()
print("Glovebox tests passed.")
