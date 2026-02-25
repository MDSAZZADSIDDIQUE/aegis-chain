import asyncio
import sys
import os

sys.path.append(os.getcwd())

from app.core.elastic import get_es_client

async def check_all_threats():
    es = get_es_client()
    index = "weather-threats"
    
    print(f"--- All Threats: {index} ---")
    if not es.indices.exists(index=index):
        print(f"Index [{index}] does not exist.")
        return

    try:
        # Total count
        resp = es.count(index=index)
        print(f"Total threats in index: {resp['count']}")
        
        # Status counts
        agg_body = {
            "size": 0,
            "aggs": {
                "status_counts": {
                    "terms": {"field": "status.keyword", "size": 10, "missing": "MISSING"}
                }
            }
        }
        res_agg = es.search(index=index, body=agg_body)
        buckets = res_agg['aggregations']['status_counts']['buckets']
        print("Status Breakdown:")
        for b in buckets:
            print(f"  {b['key']}: {b['doc_count']}")
            
        # Sample threats
        sample = es.search(index=index, body={"size": 10, "sort": [{"ingested_at": "desc"}]})
        print("\nRecent Threats:")
        for h in sample['hits']['hits']:
            src = h['_source']
            print(f"  ID: {src.get('threat_id')} | Status: {src.get('status')} | Event: {src.get('event_type')} | Ingested: {src.get('ingested_at')}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_all_threats())
