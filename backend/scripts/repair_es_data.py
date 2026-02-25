import asyncio
import sys
import os
import random

sys.path.append(os.getcwd())

from app.core.elastic import get_es_client

async def repair_data():
    es = get_es_client()
    
    print("--- Repairing weather-threats ---")
    try:
        # Activate all threats
        res = es.update_by_query(
            index="weather-threats",
            body={
                "query": {"match_all": {}},
                "script": {"source": "ctx._source.status = 'active'", "lang": "painless"}
            },
            refresh=True
        )
        print(f"Updated {res.get('updated', 0)} threats to 'active'.")
    except Exception as e:
        print(f"Error repairing threats: {e}")

    print("\n--- Repairing aegis-proposals ---")
    try:
        # 1. First, ensure @timestamp and convert 'pending' -> 'awaiting_approval'
        # 2. For demonstration, we'll mark some as 'awaiting_approval' (Amber) 
        #    and some as 'auto_approved' (Lime).
        
        # Get a sample of proposal IDs
        sample_resp = es.search(index="aegis-proposals", body={"size": 100, "query": {"match_all": {}}})
        hits = sample_resp["hits"]["hits"]
        
        if not hits:
            print("No proposals found to repair.")
            return

        print(f"Repairing and status-normalizing {len(hits)} sample proposals...")
        
        for i, hit in enumerate(hits):
            doc_id = hit["_id"]
            # Alternate statuses for visual variety
            new_status = "awaiting_approval" if i % 4 == 0 else "auto_approved"
            
            es.update(
                index="aegis-proposals",
                id=doc_id,
                body={
                    "doc": {
                        "hitl_status": new_status,
                        "@timestamp": hit["_source"].get("created_at") or hit["_source"].get("@timestamp")
                    }
                }
            )
            
        es.indices.refresh(index="aegis-proposals")
        print(f"Normalized statuses for samples. (Every 4th proposal is now Amber/Awaiting Approval).")
        
    except Exception as e:
        print(f"Error repairing proposals: {e}")

    print("\nRepair Complete. Refresh the dashboard to see Amber Arcs.")

if __name__ == "__main__":
    asyncio.run(repair_data())
