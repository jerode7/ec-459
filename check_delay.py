#!/usr/bin/env python3
import os, sys, time, requests
from datetime import datetime

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
BAD_SCHANDAU_ID = "8010020"
API_BASES = ["https://v6.db.transport.rest", "https://v5.db.transport.rest"]
MAX_RETRIES = 3
RETRY_DELAY = 15

def api_get(path, params):
    last_error = None
    for api_base in API_BASES:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"   [{attempt}/{MAX_RETRIES}] {api_base}{path}")
                resp = requests.get(f"{api_base}{path}", params=params, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as e:
                last_error = e
                if resp.status_code in (500, 502, 503, 429):
                    print(f"   HTTP {resp.status_code}, čekám {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    break
            except requests.RequestException as e:
                last_error = e
                time.sleep(RETRY_DELAY)
        print(f"   Zkouším záložní API...")
    raise RuntimeError(f"Všechna API selhala: {last_error}")

def get_departures(stop_id):
    data = api_get(f"/stops/{stop_id}/departures", {
        "duration": 90, "results": 100,
        "nationalExpress": "true", "national": "true",
        "regionalExp": "false", "regional": "false",
        "suburban": "false", "subway": "false",
        "tram": "false", "bus": "false", "ferry": "false",
    })
    return data.get("departures", []) if isinstance(data, dict) else data

def find_ec459(departures):
    for dep in departures:
        if "459" in dep.get("line", {}).get("name", ""):
            return dep
    return None

def format_time(iso_str):
    if not iso_str:
        return "?"
    try:
        return datetime.fromisoformat(iso_str).strftime("%H:%M")
    except:
        return str(iso_str)[:5]

def format_message(dep):
    if dep.get("cancelled"):
        return "🚫 EC 459 Bad Schandau: vlak je dnes ZRUŠEN"
    planned_time = format_time(dep.get("plannedWhen"))
    delay_m = round((dep.get("delay") or 0) / 60)
    if delay_m == 0:
        return f"✅ EC 459 Bad Schandau: odjezd {planned_time} — včas"
    elif delay_m > 0:
        return f"⚠️ EC 459 Bad Schandau: plán {planned_time}, skutečnost {format_time(dep.get('when'))} (+{delay_m} min)"
    else:
        return f"✅ EC 459 Bad Schandau: plán {planned_time}, skutečnost {format_time(dep.get('when'))} ({delay_m} min)"

def send_ntfy(topic, message):
    if not topic:
        print("NTFY_TOPIC není nastaveno.")
        return
    resp = requests.post(f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": "EC 459 Bad Schandau", "Priority": "default", "Tags": "train"},
        timeout=10)
    print(f"ntfy HTTP {resp.status_code}, topic: {topic}")

def main():
    try:
        print(f"🚂 Načítám odjezdy z Bad Schandau (ID: {BAD_SCHANDAU_ID})...")
        departures = get_departures(BAD_SCHANDAU_ID)
        print(f"   Celkem odjezdů: {len(departures)}")
        dep = find_ec459(departures)
        if dep is None:
            lines = [d.get("line", {}).get("name", "?") for d in departures]
            print(f"   Nalezené linky: {lines}")
            message = "❓ EC 459 nenalezeno v Bad Schandau"
        else:
            message = format_message(dep)
        print(f"\n📋 {message}\n")
        send_ntfy(NTFY_TOPIC, message)
    except Exception as e:
        error_msg = f"❌ Chyba: {e}"
        print(error_msg, file=sys.stderr)
        try:
            send_ntfy(NTFY_TOPIC, error_msg)
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
