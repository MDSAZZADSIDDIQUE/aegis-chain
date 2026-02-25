import json
from fastapi.testclient import TestClient
from main import app

def test():
    results = {}
    with TestClient(app) as client:
        resp = client.get("/dashboard/state")
        data = resp.json()
        threats = data.get("active_threats", [])
        
        results["count"] = len(threats)
        if threats:
            results["first_centroid"] = threats[0].get("centroid")
            results["keys"] = list(threats[0].keys())

    with open("centroid_test.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    test()
