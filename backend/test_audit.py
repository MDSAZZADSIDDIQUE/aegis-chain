import json
import logging
import traceback
from fastapi.testclient import TestClient
from main import app

def test():
    try:
        print("Initializing TestClient (triggers lifespan and ensure_indices)...")
        with TestClient(app) as client:
            print("--- Testing /health ---")
            resp = client.get("/health")
            print("Status:", resp.status_code)
            try:
                print("Body:", json.dumps(resp.json(), indent=2))
            except json.JSONDecodeError:
                print("Raw Response:", resp.text)
            
            print("\n--- Testing /ingest/poll ---")
            resp = client.post("/ingest/poll")
            print("Status:", resp.status_code)
            try:
                print("Body:", json.dumps(resp.json(), indent=2))
            except json.JSONDecodeError:
                print("Raw Response:", resp.text)

            print("\n--- Testing /pipeline/run ---")
            resp = client.post("/pipeline/run")
            print("Status:", resp.status_code)
            try:
                body = resp.json()
                print("Watcher results:", body.get("watcher"))
                print("Procurement proposals count:", len(body.get("procurement", [])))
                print("Actions taken count:", len(body.get("actions_taken", [])))
            except json.JSONDecodeError:
                print("Raw Response:", resp.text)
    except Exception as e:
        print("Exception occurred:")
        traceback.print_exc()

if __name__ == "__main__":
    test()
