# Critical Bug Tracker Report

As the Principal Chaos Engineer and Senior QA Defect Hunter for the AegisChain repository, I have performed an exhaustive static analysis and trace execution. The following critical bugs, logical flaws, and rendering glitches have been identified. They must be systematically patched before production release.

## 1. Frontend / React Glitches (Next.js & Mapbox)

- **[Severity Level: CRITICAL]**
- **File:** `frontend/src/components/map/AegisGlobe.tsx`
- **Trigger/Trace:** When drawing `route-lines` (the supply chain paths), if `origin.coordinates` and `dest.coordinates` are identical (e.g., origin and destination are physically co-located), the codebase intercepts the routing algorithm to prevent failure and creates a fallback geometry: `{ type: "Point", coordinates: [...] }`.
- **The Crash/Glitch:** The Mapbox layer `route-lines` is explicitly defined as `type: "line"`. Passing a geojson `Point` to a `line` layer breaks the WebGL vertex array bounds instantly, completely crashing the Mapbox instance and white-screening the Next.js visualizer.
- **The Required Patch:** Change the fallback geometry from a `Point` to a zero-length `LineString` composed of identical coordinate pairs.

- **[Severity Level: UI-GLITCH]**
- **File:** `frontend/src/components/map/AegisGlobe.tsx`
- **Trigger/Trace:** The main polling loop uses `setInterval(() => { ... updateThreats(); ... }, 100);` wrapped in a `useEffect` hooked into `[threats, locations, routes, highlightedEntities]`.
- **The Crash/Glitch:** This is a severe React anti-pattern (Stale State Interval creation). Every single time Redux/SWR mutates the `threats` state, the entire interval is torn down and re-registered, forcing continuous and costly Mapbox `setData()` payload executions at an unpredictable cadence. This causes severe rendering stutter and frame-rate drops.
- **The Required Patch:** Utilize `useRef` to store the latest state variables without adding them to the interval's dependency mapping, avoiding teardown thrashing.

- **[Severity Level: UI-GLITCH]**
- **File:** `frontend/src/app/page.tsx`
- **Trigger/Trace:** Clicking a specific active threat triggers the `selectedThreat` overlay at the top of the GUI.
- **The Crash/Glitch:** The HTML element (`<div className="absolute top-4 left-1/2 ...">`) explicitly lacks any `z-index`. Contrastingly, `RLOverlay.tsx` dictates `z-40`. Under heavy DOM load or differing component render sequences, the Mapbox container or right-side Auditor terminal can entirely obscure this crucial threat detail box.
- **The Required Patch:** Add `z-50` via Tailwind class configurations directly to the `selectedThreat` `<div />` wrapper.

---

## 2. Backend / API Contract Breaks (FastAPI)

- **[Severity Level: CRITICAL]**
- **File:** `backend/app/services/mapbox.py`
- **Trigger/Trace:** Agent 2 (Procurement) calls `get_route()` to receive live Mapbox directions. At Line 94, it triggers `data = await _fetch_mapbox_route(url, params)`.
- **The Crash/Glitch:** The local variable `url` is _never defined_ inside the `get_route()` scope! The Python interpreter immediately throws `UnboundLocalError: local variable 'url' referenced before assignment`. Mapbox never gets pinged, collapsing the entire live-route capability. The Agent silently handles the `except Exception` by faking the `drive_time_min` value.
- **The Required Patch:** Initialize `url = DIRECTIONS_URL` before line 94.

- **[Severity Level: HIGH]**
- **File:** `backend/app/api/ingest.py` (and NOOAA/FIRMS edge case handling)
- **Trigger/Trace:** You queried: "What happens if the NOAA API returns a 500 error?"
- **The Crash/Glitch:** In `noaa.py`, Line 86 issues `resp.raise_for_status()`. A 500 NOAA error triggers an `Exception`. The ingestion module `app/api/ingest.py` Line 34 catches this broadly and explicitly logs the error. Because `noaa_threats` was instantiated as an empty list, it safely skips ingestion. **However**, the API does not throw a 500 Internal Server error back to the user—the system silently swallows the 500 error and proceeds as if there's no data.
- **The Required Patch:** This operates cleanly, but operational resilience dictates we alert the `WatcherAgent` about upstream blackout status, perhaps via SSE metrics.

- **[Severity Level: HIGH]**
- **File:** `backend/app/api/routes.py` (Async/Await Iterative Query Trap)
- **Trigger/Trace:** The `/dashboard/state` route loops sequentially over potentially hundreds of `active_threats`, halting logic execution to execute `var_resp = await run_in_threadpool(es.search, ...)` for each zone.
- **The Crash/Glitch:** While it properly utilizes the threadpool to avoid freezing the ASGI event loop, doing an N+1 query directly via HTTP threads creates cascading timeouts. If 300 active threats are indexed, `dashboard_state()` sequentially queries Elasticsearch 300 times, destroying the 500ms SLA and hanging the UI connection entirely.
- **The Required Patch:** Refactor this into a singular Multi-Search (`msearch`) API execution step.

- **[Severity Level: MEDIUM]**
- **File:** `backend/app/models/schemas.py` and `frontend/src/lib/api.ts`
- **Trigger/Trace:** Type mismatch across API edges. Next.js natively expects the `Proposal` object to possess `hitl_status?: string` and `approved?: boolean`.
- **The Crash/Glitch:** The FastAPI Pydantic `RerouteProposal` has absolutely no definition or schema coverage for these fields. The system bypasses Pydantic boundaries completely by casting to `dict[str, Any]` inside pipeline aggregations to serve it to the frontend via `/dashboard/state`. This inherently defeats Pydantic's security boundary.
- **The Required Patch:** Extend the `RerouteProposal` Pydantic class to include `hitl_status: str | None = None` and `approved: bool | None = None`.

---

## 3. Database & Logic Bugs (Elasticsearch / ES|QL)

- **[Severity Level: HIGH]**
- **File:** `backend/app/services/noaa.py` and `backend/app/services/nasa_firms.py`
- **Trigger/Trace:** Polygons from NOAA/FIRMs regularly fail the `.is_valid` Shapely parameter. The script attempts to rectify this gracefully by invoking `.make_valid()`.
- **The Crash/Glitch:** When `make_valid()` breaks apart a self-intersecting polygon, it commonly outputs a `GeometryCollection` containing the valid polygon chunks, interspersed with erratic zero-width `LineString`s and `Point` features. Elasticsearch parses `geo_shape` as a `GeometryCollection` successfully. However, when the frontend retrieves this raw JSON and feeds it to the Next.js `<AegisGlobe />` `threat-fills` layer, Mapbox explicitly fails rendering logic due to non-Fill geometry being cast into a `fill` type source.
- **The Required Patch:** Inject logic immediately after `.make_valid()` to iterate through the geometry type outputs, explicitly discarding anomalous Point/Line configurations, retaining exclusively Polygon and MultiPolygon boundaries.

- **[Severity Level: UI-GLITCH / MEDIUM]**
- **File:** `backend/app/agents/procurement.py`
- **Trigger/Trace:** Attention Score Math Evaluation. What happens if `Live_Drive_Time_Minutes` is completely 0.0?
- **The Crash/Glitch:** The system definitively _does not throw a DivisionByZeroException_. Instead, on Line 208, the pipeline utilizes `max(drive_time_min, 0.1)`. The value evaluates to `0.1` and scales the attention score up by a factor of 10x. This creates a severe artificial weighting glitch, artificially catapulting the attention score of directly neighboring "zero drive-time" suppliers past highly secured long-range locations.
- **The Required Patch:** Replace the arbitrary `0.1` clamping with a more normalized baseline routing penalty factor (e.g., minimum 5.0 minutes) or penalize physically compromised local zones directly if under 15 minutes drive.
