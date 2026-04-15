""
EC 459 Bad Schandau — kontrola zpoždění
Dotáže se DB API, zjistí aktuální zpoždění EC 459 v Bad Schandau
a pošle push notifikaci přes ntfy.sh.
"""
 
import os
import sys
import time
import requests
from datetime import datetime
 
# ntfy topic se načte z proměnné prostředí (nastavené jako GitHub Secret)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
 
# Zkusíme v6, pak v5 jako zálohu
API_BASES = [
    "https://v6.db.transport.rest",
    "https://v5.db.transport.rest",
]
MAX_RETRIES = 3
RETRY_DELAY = 10  # sekund mezi pokusy
 
 
def api_get(path: str, params: dict, retries: int = MAX_RETRIES) -> dict | list:
    """GET request s automatickým retry a záložním API."""
    last_error = None
    for api_base in API_BASES:
        url = f"{api_base}{path}"
        for attempt in range(1, retries + 1):
            try:
                print(f"   [{attempt}/{retries}] {url}")
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as e:
                last_error = e
                if resp.status_code in (503, 502, 429):
                    print(f"   ⚠️  HTTP {resp.status_code}, čekám {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    break  # jiná chyba — nepomůže retry
            except requests.RequestException as e:
                last_error = e
                print(f"   ⚠️  Chyba připojení: {e}, čekám {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
        print(f"   ❌ {api_base} nedostupné, zkouším zálohu...")
    raise RuntimeError(f"Všechna API selhala. Poslední chyba: {last_error}")
 
 
def find_stop(name: str) -> str:
    """Najde ID stanice v DB podle názvu."""
    data = api_get("/locations", {
        "query": name,
        "results": 5,
        "stops": "true",
        "addresses": "false",
        "poi": "false",
    })
    stops = data if isinstance(data, list) else data.get("stops", [])
    for stop in stops:
        if stop.get("type") == "stop" and "Bad Schandau" in stop.get("name", ""):
            return stop["id"]
    raise RuntimeError(f"Stanice '{name}' nenalezena v DB API")
 
 
def get_departures(stop_id: str) -> list:
    """Načte nejbližší odjezdy ze stanice (příštích 90 minut)."""
    data = api_get(f"/stops/{stop_id}/departures", {
        "duration": 90,
        "results": 100,
        "nationalExpress": "true",
        "national": "true",
        "regionalExp": "false",
        "regional": "false",
        "suburban": "false",
        "subway": "false",
        "tram": "false",
        "bus": "false",
        "ferry": "false",
    })
    return data.get("departures", []) if isinstance(data, dict) else data
 
 
def find_ec459(departures: list) -> dict | None:
    """Najde EC 459 v seznamu odjezdů."""
    for dep in departures:
        line_name = dep.get("line", {}).get("name", "")
        if "459" in line_name:
            return dep
    return None
 
 
def format_time(iso_str: str | None) -> str:
    """Převede ISO timestamp na HH:MM."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M")
    except Exception:
        return str(iso_str)[:5]
 
 
def format_message(dep: dict) -> str:
    """Sestaví srozumitelnou zprávu o aktuálním stavu vlaku."""
    if dep.get("cancelled"):
        return "🚫 EC 459 Bad Schandau: vlak je dnes ZRUŠEN"
 
    planned = dep.get("plannedWhen")
    delay_s = dep.get("delay") or 0
    delay_m = round(delay_s / 60)
    planned_time = format_time(planned)
 
    if delay_m == 0:
        return f"✅ EC 459 Bad Schandau: odjezd {planned_time} — včas"
    elif delay_m > 0:
        actual_time = format_time(dep.get("when"))
        return (
            f"⚠️ EC 459 Bad Schandau: plán {planned_time}, "
            f"skutečnost {actual_time} (+{delay_m} min)"
        )
    else:
        actual_time = format_time(dep.get("when"))
        return (
            f"✅ EC 459 Bad Schandau: plán {planned_time}, "
            f"skutečnost {actual_time} ({delay_m} min)"
        )
 
 
def send_ntfy(topic: str, message: str) -> None:
    """Odešle push notifikaci přes ntfy.sh."""
    if not topic:
        print("⚠️  NTFY_TOPIC není nastaveno — notifikace nebude odeslána.")
        return
    requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": "EC 459 Bad Schandau",
            "Priority": "default",
            "Tags": "train",
        },
        timeout=10,
    )
    print(f"✉️  Notifikace odeslána na topic: {topic}")
 
 
def main():
    try:
        print("🔍 Hledám stanici Bad Schandau...")
        stop_id = find_stop("Bad Schandau")
        print(f"   Nalezena stanice ID: {stop_id}")
 
        print("🚂 Načítám aktuální odjezdy...")
        departures = get_departures(stop_id)
        print(f"   Celkem odjezdů: {len(departures)}")
 
        dep = find_ec459(departures)
        if dep is None:
            message = "❓ EC 459 dnes v Bad Schandau nenalezen (zrušen nebo jiná trasa?)"
        else:
            message = format_message(dep)
 
        print(f"\n📋 Výsledek: {message}\n")
        send_ntfy(NTFY_TOPIC, message)
 
    except Exception as e:
        error_msg = f"❌ Chyba při kontrole zpoždění: {e}"
        print(error_msg, file=sys.stderr)
        try:
            send_ntfy(NTFY_TOPIC, error_msg)
        except Exception:
            pass
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
