import httpx

def check_dashboard():
    r = httpx.get("http://127.0.0.1:8000/dashboard/state", timeout=5)
    data = r.json()
    print("Keys available:", data.keys())
    print("Num Locations:", len(data.get("locations", [])))
    print("Num Threats:", len(data.get("active_threats", [])))
    print("Num Routes:", len(data.get("active_routes", [])))

if __name__ == "__main__":
    check_dashboard()
