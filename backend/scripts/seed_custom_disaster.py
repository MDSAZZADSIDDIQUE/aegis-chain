"""
Custom Disaster Seeder
======================
Generates an extreme weather threat exactly on top of a known ERP location
and adds recent latency logs for that location to ensure the Watcher Agent
will pick it up as a high-priority risk.
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add backend to path
SCRIPTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env", override=False)

from app.core.config import settings
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

def _build_es_client() -> Elasticsearch:
    if settings.elastic_cloud_id:
        return Elasticsearch(
            cloud_id=settings.elastic_cloud_id,
            api_key=settings.elastic_api_key,
            request_timeout=60,
        )
    url = settings.elastic_url or "http://localhost:9200"
    return Elasticsearch(hosts=[url], api_key=settings.elastic_api_key, request_timeout=60)

def main():
    print("Connecting to Elasticsearch...")
    es = _build_es_client()

    now = datetime.now(timezone.utc)
    
    # We will target Hutchinson Grain Cooperative which is at:
    # lat: 38.0608, lon: -97.9298
    target_lat = 38.0608
    target_lon = -97.9298
    
    # Create an extreme tornado polygon right over Hutchinson
    # Polygon points must be lon, lat and closed
    poly = [
        [target_lon - 0.5, target_lat + 0.5],
        [target_lon + 0.5, target_lat + 0.5],
        [target_lon + 0.5, target_lat - 0.5],
        [target_lon - 0.5, target_lat - 0.5],
        [target_lon - 0.5, target_lat + 0.5],
    ]
    
    threat_id = f"demo-tornado-{int(now.timestamp())}"
    
    threat_doc = {
        "threat_id": threat_id,
        "source": "noaa",
        "event_type": "tornado",
        "severity": "extreme",
        "certainty": "Observed",
        "urgency": "Immediate",
        "headline": "EXTREME TORNADO EMERGENCY - DIRECT HIT ON HUTCHINSON",
        "description": "A massive, violent tornado is currently on the ground. This is a catastrophic situation.",
        "affected_zone": {
            "type": "Polygon",
            "coordinates": [poly]
        },
        "centroid": {
            "lat": target_lat,
            "lon": target_lon
        },
        "effective": now.isoformat(),
        "expires": (now + timedelta(hours=4)).isoformat(),
        "onset": now.isoformat(),
        "status": "active",
        "ingested_at": now.isoformat(),
    }
    
    print(f"Indexing custom threat: {threat_id}")
    es.index(index="weather-threats", id=threat_id, document=threat_doc)
    es.indices.refresh(index="weather-threats")
    
    # Add severe delays for this location in the last 24h
    print("Adding severe latency logs...")
    actions = []
    
    for i in range(12):
        t = now - timedelta(hours=i)
        doc = {
            "@timestamp": t.isoformat(),
            "location_id": "loc-ks-hutchinson",
            "supplier_id": "loc-ks-hutchinson",
            "destination_id": "dc-tx-dallas", # example destination
            "delay_hours": 24.0 + i, # worsening delays
            "shipment_value_usd": 500000,
            "disruption_category": "weather",
            "route_distance_km": 500,
        }
        actions.append({
            "_index": "supply-latency-logs",
            "_source": doc
        })
        
    bulk(es, actions)
    es.indices.refresh(index="supply-latency-logs")
    
    print("Done! Restart the pipeline to see the agents react to the Tornado.")

if __name__ == "__main__":
    main()
