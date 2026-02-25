import json
from fastapi.testclient import TestClient
from main import app

def test():
    results = {}
    try:
        with TestClient(app) as client:
            resp = client.get("/health")
            try:
                results["health"] = resp.json()
            except:
                results["health"] = {"status": resp.status_code, "text": resp.text}
            
            resp = client.post("/ingest/poll")
            try:
                results["ingest"] = resp.json()
            except:
                results["ingest"] = {"status": resp.status_code, "text": resp.text}

            resp = client.post("/pipeline/run")
            try:
                results["pipeline"] = resp.json()
            except:
                results["pipeline"] = {"status": resp.status_code, "text": resp.text}

    except Exception as e:
        results["error"] = str(e)
        
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    test()
