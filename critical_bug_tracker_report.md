# Critical Bug Tracker Report

## 1. Frontend / React Glitches (Next.js & Mapbox)

* **[Severity Level: CRITICAL]**
* **File:** `frontend/src/components/map/AegisGlobe.tsx`
* **Status:** **[FIXED]**
* **Trigger/Trace:** When evaluating route paths, if `origin` and `dest` refer to the exact same geographic coordinates.
* **The Crash/Glitch:** `turf.greatCircle()` throws an unhandled `Error: origin and destination cannot be the same` exception. Because this executes inside the `setInterval` data-syncing block, React ErrorBoundaries fail to catch it, causing the Mapbox and local React state to irrecoverably freeze.
* **The Required Patch:** Add a strict coordinate equality guard `if (origin.coordinates.lon === dest.coordinates.lon && origin.coordinates.lat === dest.coordinates.lat)` and fall back to processing `route.route_geometry` or inserting a simple Point/LineString instead.

* **[Severity Level: HIGH]**
* **File:** `frontend/src/components/map/AegisGlobe.tsx`
* **Status:** **[FIXED]**
* **Trigger/Trace:** Normal SPA navigation causing the component to unmount while the loop is active.
* **The Crash/Glitch:** The rendering loop `animationId = requestAnimationFrame(animate)` is never cancelled during the `useEffect` cleanup. This creates runaway `requestAnimationFrame` memory leaks that indefinitely poll dead map instances.
* **The Required Patch:** Ensure you store the `animationId` and invoke `cancelAnimationFrame(animationId)` within the cleanup return block of the initialization `useEffect`.

* **[Severity Level: UI-GLITCH]**
* **File:** `frontend/src/components/map/AegisGlobe.tsx`
* **Status:** **[FIXED]**
* **Trigger/Trace:** The operator selects a `selectedThreatId` via UI while the Mapbox style hasn't fired `style.load` yet.
* **The Crash/Glitch:** `map.getLayer("threat-fills")` returns `undefined`, immediately skipping the `setPaintProperty` highlighting calls. Because the `useEffect` tracking `[selectedThreatId, threats]` does not trigger off the style load event, the threat will load into the map invisibly (from a selection standpoint) until explicitly reselected.
* **The Required Patch:** Re-trigger the selection paint properties inside the core `map.on("style.load")` event block, or track style-load state as a React dependency.

* **[Severity Level: UI-GLITCH]**
* **File:** `frontend/src/components/chat/ChatToMap.tsx`
* **Status:** **[FIXED]**
* **Trigger/Trace:** The backend LLM takes 10+ seconds to respond. Meanwhile, the operator clicks a *different* active threat on the globe.
* **The Crash/Glitch:** `sendChatMessage` finishes and updates the UI. However, it resolves and highlights entities pertinent to the *old* threat, while the operator is currently viewing the *new* threat selection (stale state closure mismatch).
* **The Required Patch:** Implement an AbortController signal mapped to `contextThreatId` changes so stale queries are cancelled mid-flight, or check `if (contextThreatId === latestContextRef.current)` before visually logging the response.

* **[Severity Level: HIGH]**
* **File:** `frontend/src/components/map/AegisGlobe.tsx`
* **Status:** **[FIXED]**
* **Trigger/Trace:** The operator clicks an ERP Location (Warehouse, Supplier, etc.) on the map expecting `onLocationClick` to fire.
* **The Crash/Glitch:** The Mapbox click event handler (`map.on("click", layer, (e) => {...})`) extracts `e.features[0].properties`, which does *not* contain the `coordinates` array because Mapbox strips geo-coordinates from the `properties` object. The `onLocationClick` callback expects an `ERPLocation` but receives an incomplete object where `lat` and `lon` are missing.
* **The Required Patch:** Reconstruct the full `ERPLocation` object by explicitly extracting `(e.features[0].geometry as GeoJSON.Point).coordinates` and mapping it back into the payload before invoking the `onLocationClick` callback.

* **[Severity Level: UI-GLITCH]**
* **File:** `frontend/src/app/page.tsx`
* **Status:** **[FIXED]**
* **Trigger/Trace:** The operator clicks a Weather Threat polygon directly on the Mapbox globe instead of using the left-hand sidebar list.
* **The Crash/Glitch:** `AegisGlobe.tsx` calls `onThreatClick` passing only the `properties` block which excludes `description`, `source`, `affected_zone`, and `centroid`. When `page.tsx` updates `selectedThreat(threat)`, the threat detail overlay evaluates `undefined.slice()`. Next.js/React doesn't crash, but the UI renders an incomplete or blank threat info card.
* **The Required Patch:** Alter `AegisGlobe.tsx` to search the original `threats` array (`threats.find(t => t.threat_id === props.threat_id)`) and return the full object in the click handler.


## 2. Backend / API Contract Breaks (FastAPI)

* **[Severity Level: CRITICAL]**
* **File:** `backend/app/agents/watcher.py`, `backend/app/agents/orchestrator.py`, and `backend/app/api/simulate.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** Any agent cycles or simulations executing against Elasticsearch.
* **The Crash/Glitch:** Calls to `es.search()` and `es.esql.query()` utilize the standard synchronous blocking `elasticsearch-py` client but are called directly inside `async def` routes and blocks. This entirely freezes the FastAPI ASGI event loop waiting on TCP sockets, essentially bricking the API during heavy NOAA data ingestion polling.
* **The Required Patch:** Wrap all blocking `es.search()` and `es.esql.query()` transactions utilizing `await run_in_threadpool(...)` or refactor the client to use `AsyncElasticsearch`.

* **[Severity Level: HIGH]**
* **File:** `backend/app/api/routes.py` and `backend/app/services/slack.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** `/dashboard/state` is rapidly polled by intervals, or Slack fails via `send_hitl_approval_request()` in the auditor loop.
* **The Crash/Glitch:** Multiple HTTP boundaries operate without `try/except` guards. If Elasticsearch misses an index or stutters, `dashboard_state()` throws an unhandled exception yielding an HTTP 500, immediately bricking the frontend Globe. If Slack's API experiences a network timeout during `httpx.AsyncClient().post`, it bubbles up to crash `submit_verdict()`, silently destroying proposal records without state persistence.
* **The Required Patch:** Inject `try/except` guard rails into `dashboard_state()` to fall back to an empty metrics envelope on query failures, and catch `httpx.RequestError` inside `slack.py` to gracefully downgrade the proposal to "awaiting_approval" via email or dash backlog.

* **[Severity Level: MEDIUM]**
* **File:** `backend/app/agents/procurement.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** Agent 2 generates reroute proposals, appending a raw dictionary into the pipeline array.
* **The Crash/Glitch:** The payload dict injects non-contract fields (`rank`, `reliability_index`, `vector_similarity`, `distance_from_threat_km`) completely undocumented by `RerouteProposal` in `schemas.py`. `orchestrator.py` subsequently calls `upsert_proposal` natively skipping Pydantic. This creates a schema divergence severely bloating Elasticsearch indices and silently breaking analytical aggregations.
* **The Required Patch:** Enforce model serialization `RerouteProposal(**proposal).model_dump()` prior to forwarding payloads into the persistence layer.

* **[Severity Level: CRITICAL]**
* **File:** `backend/app/agents/watcher.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** The `run_watcher_cycle()` pipeline or manual `/ingest/poll` is executed.
* **The Crash/Glitch:** Line 161 in `watcher.py` contains an incomplete, trailing `},` immediately followed by `)` within the `ml_by_entity` block, without an opening dictionary or the required `search_kwargs` assignment. This explicit `SyntaxError` prevents the module from compiling or running, crashing the `orchestrator.py` agent cycle.
* **The Required Patch:** Remove the dangling `},` and `)` and properly define the `search_kwargs = {"index": "aegis-ml-results", ...}` dictionary before calling `await run_in_threadpool(es.search, **search_kwargs)`.

* **[Severity Level: HIGH]**
* **File:** `backend/app/api/routes.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** Slack sends a webhook payload (or a malicious actor hits the endpoint) missing the `X-Slack-Request-Timestamp` header.
* **The Crash/Glitch:** The `/slack/actions` endpoint defaults this missing header to an empty string (`""`). It passes this to `verify_slack_signature(timestamp, ...)` which attempts to execute `int(timestamp)`. This immediately throws a `ValueError: invalid literal for int() with base 10: ''` yielding an unhandled 500 Server Error instead of a 403 Forbidden.
* **The Required Patch:** Add an explicit guard `if not timestamp: raise HTTPException(...)` before executing `verify_slack_signature()` or modifying the signature checker.


## 3. Database & Logic Bugs (Elasticsearch / ES|QL)

* **[Severity Level: CRITICAL]**
* **File:** `backend/app/services/noaa.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** NOAA API produces a weather alert with immediate root geometry object, skipping the `affectedZones` lookup loop.
* **The Crash/Glitch:** The script blindly maps this root `geometry` parameter into `affected_zone` GeoJSON. Critically, it skips applying the Shapely `.is_valid` / `make_valid()` check (which is only present in the `zone_geoms` loop). Since NOAA geometries frequently contain raw, unclosed, or self-intersecting loops, mapping these broken polygons instantly crashes Elasticsearch bulk ingestion throwing an `Invalid shape: intersections detected` ES 400 Bad Request pipeline failure.
* **The Required Patch:** Systematically pass the primary NOAA `geom` through Shapely's `shape(geom)`, run `make_valid()`, and then extract the final mapping directly prior to building the payload dict.

* **[Severity Level: HIGH]**
* **File:** `backend/app/agents/procurement.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** An anomalous or manually seeded weather threat fails to generate a valid centroid topology due to unresolvable zones (evaluating to `None`).
* **The Crash/Glitch:** At line 171, the script calculates straight-line out-of-bounds metrics directly referencing `threat_centroid["lat"]`. This triggers a strict `TypeError: 'NoneType' object is not subscriptable` dividing logic and permanently blocking Agent 2 processing.
* **[Severity Level: MEDIUM]**
* **File:** `backend/app/agents/orchestrator.py`
* **Status:** **[FIXED]**
* **Trigger/Trace:** The Procurement Agent 2 triggers, determining the "highest-value affected location" from an array where one or more locations do not have a defined `inventory_value_usd` (e.g., set to explicitly `null` in Elasticsearch).
* **The Crash/Glitch:** The function uses `max(affected_locs, key=lambda x: x.get("inventory_value_usd", 0))`. If the underlying Elastic value is `null`, Python's `.get()` returns `None` instead of `0`. The `max()` function then throws an unhandled `TypeError: '>' not supported between instances of 'NoneType' and 'int'`, instantly killing Agent 2.
* **The Required Patch:** Modify the lambda to safely coalesce nulls: `lambda x: x.get("inventory_value_usd") or 0`.
