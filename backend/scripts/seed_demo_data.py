"""
AegisChain Demo Data Seeder
============================

Inserts 50 realistic US agricultural ERP nodes into `erp-locations`,
6 synthetic weather threats into `weather-threats` (with polygons that
cover the seeded ERP nodes so the pipeline always produces results),
and 90 days of synthetic `supply-latency-logs` with realistic delay
distributions.  Without this, the globe shows a blank map.

Usage (from the `backend/` directory):

    python -m scripts.seed_demo_data                # seed if empty
    python -m scripts.seed_demo_data --force        # wipe & re-seed
    python -m scripts.seed_demo_data --dry-run      # preview counts, no writes
    python -m scripts.seed_demo_data --locations-only
    python -m scripts.seed_demo_data --threats-only
    python -m scripts.seed_demo_data --logs-only

Requirements:
    pip install elasticsearch python-dotenv  (already in requirements.txt)

The script reads ELASTIC_CLOUD_ID / ELASTIC_API_KEY  (or ELASTIC_URL) from
backend/.env — copy .env.example and fill in your credentials first.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Path bootstrap: allow `from app.core…` imports when running as __main__ ──
SCRIPTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR  = SCRIPTS_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

sys.path.insert(0, str(BACKEND_DIR))

# Load .env before pydantic-settings reads env vars
from dotenv import load_dotenv                        # noqa: E402  (after sys.path)
load_dotenv(BACKEND_DIR / ".env", override=False)

from elasticsearch import Elasticsearch, NotFoundError   # noqa: E402
from elasticsearch.helpers import bulk as es_bulk         # noqa: E402

from app.core.config import settings                      # noqa: E402


# ── Deterministic RNG (reproducible dataset on every run) ─────────────────
_RNG = random.Random(42)


# ─────────────────────────────────────────────────────────────────────────────
# ERP NODE MASTER LIST — 50 realistic US agricultural locations
# ─────────────────────────────────────────────────────────────────────────────

ERP_NODES: list[dict] = [

    # ── Midwest Grain Elevator Suppliers ─────────────────────────────────────

    {
        "location_id": "loc-ks-hutchinson",
        "name": "Hutchinson Grain Cooperative",
        "type": "supplier",
        "coordinates": {"lat": 38.0608, "lon": -97.9298},
        "address": "1200 E 4th Ave, Hutchinson, KS 67501",
        "region": "Midwest",
        "inventory_value_usd": 18_400_000.0,
        "reliability_index": 0.912,
        "avg_lead_time_hours": 36.0,
        "capacity_units": 45_000,
        "contract_sla": "48h delivery guarantee, 99% fill rate, weather force majeure, "
                        "annual rate review, dedicated I-70 truck lanes",
        "tags": ["grain", "wheat", "elevator", "kansas"],
    },
    {
        "location_id": "loc-ks-dodge-city",
        "name": "Dodge City Grain Elevators",
        "type": "supplier",
        "coordinates": {"lat": 37.7528, "lon": -100.0171},
        "address": "800 W Wyatt Earp Blvd, Dodge City, KS 67801",
        "region": "Midwest",
        "inventory_value_usd": 14_200_000.0,
        "reliability_index": 0.884,
        "avg_lead_time_hours": 42.0,
        "capacity_units": 38_000,
        "contract_sla": "72h delivery window, 97% fill rate, winter weather SLA extension, "
                        "quarterly performance review",
        "tags": ["grain", "sorghum", "elevator", "kansas"],
    },
    {
        "location_id": "loc-ks-salina",
        "name": "Salina Agri-Hub Terminal",
        "type": "supplier",
        "coordinates": {"lat": 38.8403, "lon": -97.6114},
        "address": "2300 N Broadway, Salina, KS 67401",
        "region": "Midwest",
        "inventory_value_usd": 22_800_000.0,
        "reliability_index": 0.941,
        "avg_lead_time_hours": 30.0,
        "capacity_units": 52_000,
        "contract_sla": "48h priority delivery, 99.5% fill rate, dual rail/truck access, "
                        "SLA credits 0.5% per day late",
        "tags": ["grain", "wheat", "corn", "elevator", "kansas", "rail-access"],
    },
    {
        "location_id": "loc-ia-ames",
        "name": "Ames Cooperative Elevator",
        "type": "supplier",
        "coordinates": {"lat": 42.0308, "lon": -93.6319},
        "address": "505 S Duff Ave, Ames, IA 50010",
        "region": "Midwest",
        "inventory_value_usd": 16_500_000.0,
        "reliability_index": 0.896,
        "avg_lead_time_hours": 24.0,
        "capacity_units": 41_000,
        "contract_sla": "36h standard delivery, 98% fill rate, Iowa State Agri extension partnership",
        "tags": ["grain", "corn", "soybeans", "elevator", "iowa"],
    },
    {
        "location_id": "loc-ia-sioux-city",
        "name": "Sioux City Grain Terminal",
        "type": "supplier",
        "coordinates": {"lat": 42.4997, "lon": -96.4003},
        "address": "1 Terminal Dr, Sioux City, IA 51101",
        "region": "Midwest",
        "inventory_value_usd": 27_300_000.0,
        "reliability_index": 0.927,
        "avg_lead_time_hours": 28.0,
        "capacity_units": 60_000,
        "contract_sla": "48h rail/truck dual-mode delivery, 99% fill rate, "
                        "Missouri River barge option, force majeure clause",
        "tags": ["grain", "corn", "soybeans", "terminal", "iowa", "rail-access", "barge"],
    },
    {
        "location_id": "loc-ia-cedar-rapids",
        "name": "Cedar Rapids Grain Hub",
        "type": "supplier",
        "coordinates": {"lat": 41.9779, "lon": -91.6656},
        "address": "3200 16th Ave SW, Cedar Rapids, IA 52404",
        "region": "Midwest",
        "inventory_value_usd": 19_100_000.0,
        "reliability_index": 0.908,
        "avg_lead_time_hours": 26.0,
        "capacity_units": 44_000,
        "contract_sla": "36h guaranteed delivery, 98.5% fill rate, "
                        "ethanol-grade corn available, volume discount tiers",
        "tags": ["grain", "corn", "ethanol-grade", "iowa"],
    },
    {
        "location_id": "loc-ne-lincoln",
        "name": "Lincoln Grain Services",
        "type": "supplier",
        "coordinates": {"lat": 40.8136, "lon": -96.7026},
        "address": "400 N 33rd St, Lincoln, NE 68503",
        "region": "Midwest",
        "inventory_value_usd": 15_700_000.0,
        "reliability_index": 0.875,
        "avg_lead_time_hours": 38.0,
        "capacity_units": 36_000,
        "contract_sla": "72h standard, 97% fill rate, Nebraska winter clause, "
                        "UP railroad siding access",
        "tags": ["grain", "corn", "wheat", "elevator", "nebraska", "rail-access"],
    },
    {
        "location_id": "loc-ne-columbus",
        "name": "Columbus Agri Center",
        "type": "supplier",
        "coordinates": {"lat": 41.4297, "lon": -97.3683},
        "address": "1525 27th Ave, Columbus, NE 68601",
        "region": "Midwest",
        "inventory_value_usd": 12_900_000.0,
        "reliability_index": 0.861,
        "avg_lead_time_hours": 44.0,
        "capacity_units": 31_000,
        "contract_sla": "72h standard delivery, 96% fill rate, Platte Valley origin grains, "
                        "spot pricing available",
        "tags": ["grain", "corn", "elevator", "nebraska"],
    },
    {
        "location_id": "loc-il-bloomington",
        "name": "Bloomington Grain Hub",
        "type": "supplier",
        "coordinates": {"lat": 40.4842, "lon": -88.9937},
        "address": "2400 W Market St, Bloomington, IL 61701",
        "region": "Midwest",
        "inventory_value_usd": 23_600_000.0,
        "reliability_index": 0.934,
        "avg_lead_time_hours": 22.0,
        "capacity_units": 55_000,
        "contract_sla": "24h express and 48h standard tiers, 99% fill rate, "
                        "Central Illinois origin, I-74/I-55 direct lanes",
        "tags": ["grain", "corn", "soybeans", "elevator", "illinois"],
    },
    {
        "location_id": "loc-il-peoria",
        "name": "Peoria Agri Terminal",
        "type": "supplier",
        "coordinates": {"lat": 40.6936, "lon": -89.5890},
        "address": "1 Caterpillar Dr, Peoria, IL 61602",
        "region": "Midwest",
        "inventory_value_usd": 31_200_000.0,
        "reliability_index": 0.952,
        "avg_lead_time_hours": 20.0,
        "capacity_units": 68_000,
        "contract_sla": "24h priority truck, 48h rail, 99.5% fill rate, "
                        "Illinois River barge access, ADM partnership SLA",
        "tags": ["grain", "corn", "soybeans", "terminal", "illinois", "rail-access", "barge"],
    },
    {
        "location_id": "loc-mn-minneapolis",
        "name": "Minneapolis Grain Exchange Elevator",
        "type": "supplier",
        "coordinates": {"lat": 44.9778, "lon": -93.2650},
        "address": "400 S 4th St, Minneapolis, MN 55415",
        "region": "Midwest",
        "inventory_value_usd": 38_500_000.0,
        "reliability_index": 0.943,
        "avg_lead_time_hours": 18.0,
        "capacity_units": 82_000,
        "contract_sla": "24h metro delivery, 48h regional, 99% fill rate, "
                        "MGE certified grain, cold-weather SLA provisions",
        "tags": ["grain", "wheat", "corn", "exchange", "minnesota"],
    },
    {
        "location_id": "loc-nd-fargo",
        "name": "Fargo Wheat Cooperative",
        "type": "supplier",
        "coordinates": {"lat": 46.8772, "lon": -96.7898},
        "address": "3700 Main Ave, Fargo, ND 58103",
        "region": "Midwest",
        "inventory_value_usd": 11_300_000.0,
        "reliability_index": 0.842,
        "avg_lead_time_hours": 52.0,
        "capacity_units": 28_000,
        "contract_sla": "72h standard delivery, 95% fill rate, spring wheat specialty, "
                        "blizzard force majeure 30-day window",
        "tags": ["grain", "wheat", "spring-wheat", "north-dakota"],
    },
    {
        "location_id": "loc-sd-sioux-falls",
        "name": "Sioux Falls Agri Depot",
        "type": "supplier",
        "coordinates": {"lat": 43.5460, "lon": -96.7313},
        "address": "1100 N Cliff Ave, Sioux Falls, SD 57103",
        "region": "Midwest",
        "inventory_value_usd": 10_800_000.0,
        "reliability_index": 0.857,
        "avg_lead_time_hours": 48.0,
        "capacity_units": 26_000,
        "contract_sla": "72h delivery, 96% fill rate, corn and soybeans, I-29 truck lane preferred",
        "tags": ["grain", "corn", "soybeans", "south-dakota"],
    },
    {
        "location_id": "loc-mo-st-joseph",
        "name": "St. Joseph Grain Partners",
        "type": "supplier",
        "coordinates": {"lat": 39.7675, "lon": -94.8467},
        "address": "4200 S Belt Hwy, St. Joseph, MO 64503",
        "region": "Midwest",
        "inventory_value_usd": 17_400_000.0,
        "reliability_index": 0.889,
        "avg_lead_time_hours": 34.0,
        "capacity_units": 40_000,
        "contract_sla": "48h delivery, 98% fill rate, Missouri River access, "
                        "BNSF rail connection, spot and contract pricing",
        "tags": ["grain", "corn", "soybeans", "missouri", "rail-access", "barge"],
    },
    {
        "location_id": "loc-co-greeley",
        "name": "Greeley Feedlot Grain Logistics",
        "type": "supplier",
        "coordinates": {"lat": 40.4233, "lon": -104.7091},
        "address": "1800 N 35th Ave, Greeley, CO 80631",
        "region": "Midwest",
        "inventory_value_usd": 9_600_000.0,
        "reliability_index": 0.832,
        "avg_lead_time_hours": 56.0,
        "capacity_units": 22_000,
        "contract_sla": "72h standard delivery, 95% fill rate, high-altitude route extension, "
                        "feedlot-grade corn specialty",
        "tags": ["grain", "corn", "feedlot-grade", "colorado"],
    },

    # ── Gulf Coast Ports ──────────────────────────────────────────────────────

    {
        "location_id": "loc-tx-houston-port",
        "name": "Port of Houston Grain Terminal",
        "type": "port",
        "coordinates": {"lat": 29.7273, "lon": -95.2987},
        "address": "7300 Clinton Dr, Houston, TX 77020",
        "region": "Gulf Coast",
        "inventory_value_usd": 87_500_000.0,
        "reliability_index": 0.967,
        "avg_lead_time_hours": 72.0,
        "capacity_units": 250_000,
        "contract_sla": "72h berth guaranteed, 99.5% vessel loading rate, "
                        "Panamax/Capesize capable, 24/7 ops, hurricane contingency protocol",
        "tags": ["port", "export", "grain", "texas", "gulf-coast", "deep-water"],
    },
    {
        "location_id": "loc-tx-corpus-christi",
        "name": "Corpus Christi Bulk Terminal",
        "type": "port",
        "coordinates": {"lat": 27.8006, "lon": -97.3964},
        "address": "100 Harbor Dr, Corpus Christi, TX 78401",
        "region": "Gulf Coast",
        "inventory_value_usd": 54_200_000.0,
        "reliability_index": 0.944,
        "avg_lead_time_hours": 96.0,
        "capacity_units": 165_000,
        "contract_sla": "96h standard vessel turnaround, 99% loading uptime, "
                        "sorghum/grain sorghum specialty, storm surge protocol",
        "tags": ["port", "export", "grain", "sorghum", "texas", "gulf-coast"],
    },
    {
        "location_id": "loc-la-new-orleans",
        "name": "Port of New Orleans Export Dock",
        "type": "port",
        "coordinates": {"lat": 29.9511, "lon": -90.0715},
        "address": "1 Canal St, New Orleans, LA 70130",
        "region": "Gulf Coast",
        "inventory_value_usd": 112_000_000.0,
        "reliability_index": 0.958,
        "avg_lead_time_hours": 48.0,
        "capacity_units": 320_000,
        "contract_sla": "48h barge-to-vessel transfer SLA, 99.8% uptime, "
                        "Mississippi River corridor, Cargill/ADM preferred lanes, "
                        "hurricane deductible clause",
        "tags": ["port", "export", "grain", "louisiana", "gulf-coast", "barge", "deep-water"],
    },
    {
        "location_id": "loc-la-baton-rouge",
        "name": "Baton Rouge Grain Port",
        "type": "port",
        "coordinates": {"lat": 30.4515, "lon": -91.1871},
        "address": "900 N River Rd, Baton Rouge, LA 70802",
        "region": "Gulf Coast",
        "inventory_value_usd": 63_800_000.0,
        "reliability_index": 0.936,
        "avg_lead_time_hours": 60.0,
        "capacity_units": 180_000,
        "contract_sla": "60h barge consolidation and transfer, 98.5% fill rate, "
                        "river stage contingency SLA, ADM facility partnership",
        "tags": ["port", "export", "grain", "louisiana", "gulf-coast", "barge"],
    },
    {
        "location_id": "loc-ms-gulfport",
        "name": "Gulfport Agri Export Hub",
        "type": "port",
        "coordinates": {"lat": 30.3674, "lon": -89.0928},
        "address": "1 Gulfport Harbor Dr, Gulfport, MS 39501",
        "region": "Gulf Coast",
        "inventory_value_usd": 39_400_000.0,
        "reliability_index": 0.912,
        "avg_lead_time_hours": 84.0,
        "capacity_units": 110_000,
        "contract_sla": "84h vessel loading, 98% uptime, "
                        "hurricane season SLA extension June–November, specialty rice export",
        "tags": ["port", "export", "grain", "rice", "mississippi", "gulf-coast"],
    },
    {
        "location_id": "loc-tx-beaumont",
        "name": "Beaumont Gulf Export Terminal",
        "type": "port",
        "coordinates": {"lat": 30.0802, "lon": -94.1266},
        "address": "550 Magnolia Ave, Beaumont, TX 77701",
        "region": "Gulf Coast",
        "inventory_value_usd": 44_600_000.0,
        "reliability_index": 0.921,
        "avg_lead_time_hours": 80.0,
        "capacity_units": 130_000,
        "contract_sla": "80h standard loading, 98.5% uptime, "
                        "Gulf Intracoastal Waterway access, petrochemical co-terminal",
        "tags": ["port", "export", "grain", "texas", "gulf-coast"],
    },
    {
        "location_id": "loc-fl-tampa",
        "name": "Tampa Port Agricultural Dock",
        "type": "port",
        "coordinates": {"lat": 27.9389, "lon": -82.4450},
        "address": "1101 Channelside Dr, Tampa, FL 33602",
        "region": "Gulf Coast",
        "inventory_value_usd": 28_700_000.0,
        "reliability_index": 0.903,
        "avg_lead_time_hours": 96.0,
        "capacity_units": 85_000,
        "contract_sla": "96h loading turnaround, 98% uptime, "
                        "phosphate/fertilizer return cargo synergy, hurricane season addendum",
        "tags": ["port", "export", "grain", "fertilizer", "florida", "gulf-coast"],
    },
    {
        "location_id": "loc-al-mobile",
        "name": "Mobile Bay Grain Terminal",
        "type": "port",
        "coordinates": {"lat": 30.6954, "lon": -88.0399},
        "address": "250 Water St, Mobile, AL 36602",
        "region": "Gulf Coast",
        "inventory_value_usd": 31_500_000.0,
        "reliability_index": 0.914,
        "avg_lead_time_hours": 88.0,
        "capacity_units": 92_000,
        "contract_sla": "88h vessel turnaround, 98.5% uptime, "
                        "Alabama State Port Authority SLA, CSX rail direct connection",
        "tags": ["port", "export", "grain", "alabama", "gulf-coast", "rail-access"],
    },
    {
        "location_id": "loc-oh-toledo",
        "name": "Toledo Grain Terminal (Lake Erie)",
        "type": "port",
        "coordinates": {"lat": 41.6639, "lon": -83.5552},
        "address": "1 Lake Erie Dr, Toledo, OH 43611",
        "region": "Midwest",
        "inventory_value_usd": 42_700_000.0,
        "reliability_index": 0.925,
        "avg_lead_time_hours": 36.0,
        "capacity_units": 100_000,
        "contract_sla": "48h Great Lakes vessel loading, 98.5% uptime, Seaway transit, "
                        "CSX/NS rail, ice season SLA November–April",
        "tags": ["port", "grain", "soybeans", "ohio", "lake-erie", "seaway", "rail-access"],
    },

    # ── California Cold-Chain Distribution Centers ────────────────────────────

    {
        "location_id": "loc-ca-fresno",
        "name": "Fresno Cold Chain Hub",
        "type": "distribution_center",
        "coordinates": {"lat": 36.7468, "lon": -119.7726},
        "address": "2180 E Jensen Ave, Fresno, CA 93706",
        "region": "West",
        "inventory_value_usd": 41_300_000.0,
        "reliability_index": 0.948,
        "avg_lead_time_hours": 16.0,
        "capacity_units": 95_000,
        "contract_sla": "24h refrigerated delivery, 99% cold-chain integrity, "
                        "−4°F to 34°F zones, FSMA compliant, Central Valley origin fresh",
        "tags": ["cold-chain", "produce", "refrigerated", "california", "central-valley"],
    },
    {
        "location_id": "loc-ca-stockton",
        "name": "Stockton Refrigerated DC",
        "type": "distribution_center",
        "coordinates": {"lat": 37.9577, "lon": -121.2908},
        "address": "4200 W March Ln, Stockton, CA 95219",
        "region": "West",
        "inventory_value_usd": 35_800_000.0,
        "reliability_index": 0.939,
        "avg_lead_time_hours": 12.0,
        "capacity_units": 78_000,
        "contract_sla": "12h Bay Area delivery, 24h SoCal delivery, 99% cold-chain integrity, "
                        "asparagus/tomato specialty, Port of Stockton rail siding",
        "tags": ["cold-chain", "produce", "refrigerated", "california", "delta"],
    },
    {
        "location_id": "loc-ca-bakersfield",
        "name": "Bakersfield Produce DC",
        "type": "distribution_center",
        "coordinates": {"lat": 35.3733, "lon": -119.0187},
        "address": "3301 Fruitvale Ave, Bakersfield, CA 93308",
        "region": "West",
        "inventory_value_usd": 29_400_000.0,
        "reliability_index": 0.921,
        "avg_lead_time_hours": 18.0,
        "capacity_units": 68_000,
        "contract_sla": "24h Kern County distribution, 48h SoCal delivery, 98.5% fill rate, "
                        "citrus/grapes specialty, I-5 and Hwy 99 dual access",
        "tags": ["cold-chain", "produce", "citrus", "grapes", "california", "kern-county"],
    },
    {
        "location_id": "loc-ca-modesto",
        "name": "Modesto Agri-Cold Center",
        "type": "distribution_center",
        "coordinates": {"lat": 37.6391, "lon": -120.9969},
        "address": "500 9th St, Modesto, CA 95354",
        "region": "West",
        "inventory_value_usd": 26_700_000.0,
        "reliability_index": 0.916,
        "avg_lead_time_hours": 14.0,
        "capacity_units": 60_000,
        "contract_sla": "12h Bay Area, 24h regional, 98% cold-chain uptime, "
                        "almond/walnut processing hub, UC Cooperative Extension SLA",
        "tags": ["cold-chain", "nuts", "almonds", "california", "stanislaus"],
    },
    {
        "location_id": "loc-ca-salinas",
        "name": "Salinas Valley Cold Hub",
        "type": "distribution_center",
        "coordinates": {"lat": 36.6777, "lon": -121.6555},
        "address": "1150 Airport Blvd, Salinas, CA 93905",
        "region": "West",
        "inventory_value_usd": 33_600_000.0,
        "reliability_index": 0.944,
        "avg_lead_time_hours": 10.0,
        "capacity_units": 72_000,
        "contract_sla": "12h Bay Area delivery, 8h direct cooler-to-market, 99% integrity, "
                        "leafy greens specialty, FDA FSMA 204 traceability",
        "tags": ["cold-chain", "leafy-greens", "lettuce", "california", "monterey"],
    },
    {
        "location_id": "loc-ca-los-angeles",
        "name": "LA Port Cold Chain Facility",
        "type": "distribution_center",
        "coordinates": {"lat": 33.7298, "lon": -118.2639},
        "address": "2300 E Pacific Coast Hwy, Wilmington, CA 90744",
        "region": "West",
        "inventory_value_usd": 68_400_000.0,
        "reliability_index": 0.961,
        "avg_lead_time_hours": 8.0,
        "capacity_units": 145_000,
        "contract_sla": "8h SoCal delivery, 24h northern, 99.5% cold-chain uptime, "
                        "Port of LA integration, reefer container staging",
        "tags": ["cold-chain", "produce", "import-export", "california", "los-angeles"],
    },
    {
        "location_id": "loc-ca-long-beach",
        "name": "Long Beach Refrigerated Terminal",
        "type": "distribution_center",
        "coordinates": {"lat": 33.7701, "lon": -118.1937},
        "address": "900 E Ocean Blvd, Long Beach, CA 90802",
        "region": "West",
        "inventory_value_usd": 57_900_000.0,
        "reliability_index": 0.955,
        "avg_lead_time_hours": 9.0,
        "capacity_units": 128_000,
        "contract_sla": "8h SoCal delivery, 99% cold-chain integrity, "
                        "Port of Long Beach reefer priority, bonded warehouse status",
        "tags": ["cold-chain", "produce", "refrigerated", "california", "long-beach"],
    },
    {
        "location_id": "loc-ca-sacramento",
        "name": "Sacramento Cold Storage Hub",
        "type": "distribution_center",
        "coordinates": {"lat": 38.5816, "lon": -121.4944},
        "address": "3800 Bradshaw Rd, Sacramento, CA 95827",
        "region": "West",
        "inventory_value_usd": 31_200_000.0,
        "reliability_index": 0.927,
        "avg_lead_time_hours": 12.0,
        "capacity_units": 70_000,
        "contract_sla": "12h Northern California delivery, 24h Sierra Nevada region, "
                        "99% uptime, rice and tree nut specialty, Port of Sacramento barge",
        "tags": ["cold-chain", "rice", "tree-nuts", "california", "sacramento"],
    },
    {
        "location_id": "loc-ca-san-jose",
        "name": "San Jose Agri Logistics Hub",
        "type": "distribution_center",
        "coordinates": {"lat": 37.3382, "lon": -121.8863},
        "address": "2100 Airport Blvd, San Jose, CA 95110",
        "region": "West",
        "inventory_value_usd": 44_700_000.0,
        "reliability_index": 0.949,
        "avg_lead_time_hours": 10.0,
        "capacity_units": 98_000,
        "contract_sla": "8h Bay Area delivery, 24h regional, 99.5% uptime, "
                        "Silicon Valley food tech client SLA, automated cold storage",
        "tags": ["cold-chain", "produce", "tech-enabled", "california", "santa-clara"],
    },

    # ── Midwest / National Warehouses ─────────────────────────────────────────

    {
        "location_id": "loc-il-chicago",
        "name": "Chicago Intermodal Agri Warehouse",
        "type": "warehouse",
        "coordinates": {"lat": 41.8526, "lon": -87.6534},
        "address": "1000 W 51st St, Chicago, IL 60609",
        "region": "Midwest",
        "inventory_value_usd": 56_800_000.0,
        "reliability_index": 0.953,
        "avg_lead_time_hours": 18.0,
        "capacity_units": 120_000,
        "contract_sla": "24h Midwest delivery, 48h national, 99% fill rate, "
                        "5 Class I railroad connections, I-80/I-90 gateway, bonded warehouse",
        "tags": ["warehouse", "grain", "intermodal", "illinois", "chicago", "rail-access"],
    },
    {
        "location_id": "loc-tn-memphis",
        "name": "Memphis Agri Logistics Center",
        "type": "warehouse",
        "coordinates": {"lat": 35.1495, "lon": -90.0490},
        "address": "4801 E Holmes Rd, Memphis, TN 38118",
        "region": "South",
        "inventory_value_usd": 43_200_000.0,
        "reliability_index": 0.938,
        "avg_lead_time_hours": 20.0,
        "capacity_units": 95_000,
        "contract_sla": "24h Mid-South delivery, 48h Southeast, 99% fill rate, "
                        "FedEx hub proximity, Mississippi River access",
        "tags": ["warehouse", "grain", "cotton", "soybeans", "tennessee", "barge"],
    },
    {
        "location_id": "loc-mo-kansas-city",
        "name": "Kansas City Agricultural Depot",
        "type": "warehouse",
        "coordinates": {"lat": 39.0997, "lon": -94.5786},
        "address": "3600 Guinotte Ave, Kansas City, MO 64120",
        "region": "Midwest",
        "inventory_value_usd": 48_700_000.0,
        "reliability_index": 0.946,
        "avg_lead_time_hours": 16.0,
        "capacity_units": 105_000,
        "contract_sla": "24h Midwest delivery, 48h multi-regional, 99% fill rate, "
                        "BNSF/UP rail hub, Missouri River barge origination",
        "tags": ["warehouse", "grain", "intermodal", "missouri", "rail-access", "barge"],
    },
    {
        "location_id": "loc-tx-dallas",
        "name": "Dallas–Fort Worth Agri Hub",
        "type": "warehouse",
        "coordinates": {"lat": 32.8998, "lon": -97.0403},
        "address": "2900 E Airfield Dr, Irving, TX 75062",
        "region": "South",
        "inventory_value_usd": 52_300_000.0,
        "reliability_index": 0.949,
        "avg_lead_time_hours": 14.0,
        "capacity_units": 115_000,
        "contract_sla": "24h Texas delivery, 48h South Central, 99% fill rate, "
                        "DFW airport cargo adjacency, I-35 north–south corridor",
        "tags": ["warehouse", "grain", "produce", "texas", "dallas", "air-access"],
    },
    {
        "location_id": "loc-oh-columbus",
        "name": "Columbus Agricultural Warehouse",
        "type": "warehouse",
        "coordinates": {"lat": 39.9612, "lon": -82.9988},
        "address": "3400 Alum Creek Dr, Columbus, OH 43207",
        "region": "Midwest",
        "inventory_value_usd": 37_600_000.0,
        "reliability_index": 0.929,
        "avg_lead_time_hours": 22.0,
        "capacity_units": 82_000,
        "contract_sla": "24h Ohio Valley delivery, 48h Northeast, 98.5% fill rate, "
                        "I-70/I-71 crossroads, automotive/food dual facility",
        "tags": ["warehouse", "grain", "ohio", "columbus"],
    },
    {
        "location_id": "loc-wi-milwaukee",
        "name": "Milwaukee Grain Warehouse",
        "type": "warehouse",
        "coordinates": {"lat": 43.0389, "lon": -87.9065},
        "address": "3600 Port Washington Rd, Milwaukee, WI 53212",
        "region": "Midwest",
        "inventory_value_usd": 29_800_000.0,
        "reliability_index": 0.914,
        "avg_lead_time_hours": 26.0,
        "capacity_units": 66_000,
        "contract_sla": "36h Great Lakes region, 48h Midwest, 98% fill rate, "
                        "Lake Michigan port access, corn syrup and dairy specialty",
        "tags": ["warehouse", "grain", "dairy", "wisconsin", "milwaukee"],
    },
    {
        "location_id": "loc-in-indianapolis",
        "name": "Indianapolis Agri Center",
        "type": "warehouse",
        "coordinates": {"lat": 39.7684, "lon": -86.1581},
        "address": "4200 S High School Rd, Indianapolis, IN 46241",
        "region": "Midwest",
        "inventory_value_usd": 33_400_000.0,
        "reliability_index": 0.924,
        "avg_lead_time_hours": 20.0,
        "capacity_units": 74_000,
        "contract_sla": "24h Indiana delivery, 48h Midwest, 98.5% fill rate, "
                        "I-70/I-65 interchange, FedEx/UPS hub adjacency",
        "tags": ["warehouse", "grain", "produce", "indiana", "indianapolis"],
    },
    {
        "location_id": "loc-ga-atlanta",
        "name": "Atlanta Intermodal Food Hub",
        "type": "warehouse",
        "coordinates": {"lat": 33.7490, "lon": -84.3880},
        "address": "1200 Jonesboro Rd SE, Atlanta, GA 30315",
        "region": "South",
        "inventory_value_usd": 47_100_000.0,
        "reliability_index": 0.941,
        "avg_lead_time_hours": 16.0,
        "capacity_units": 102_000,
        "contract_sla": "24h Southeast delivery, 48h national, 99% fill rate, "
                        "Hartsfield-Jackson cargo adjacency, CSX/NS rail",
        "tags": ["warehouse", "produce", "grain", "georgia", "atlanta", "rail-access"],
    },
    {
        "location_id": "loc-ky-louisville",
        "name": "Louisville Agri Crossroads",
        "type": "warehouse",
        "coordinates": {"lat": 38.2527, "lon": -85.7585},
        "address": "4400 Produce Dr, Louisville, KY 40218",
        "region": "South",
        "inventory_value_usd": 38_200_000.0,
        "reliability_index": 0.932,
        "avg_lead_time_hours": 22.0,
        "capacity_units": 84_000,
        "contract_sla": "24h Ohio Valley delivery, 48h regional, 98.5% fill rate, "
                        "UPS Worldport adjacency, I-64/I-65/I-71 crossroads, Ohio River barge",
        "tags": ["warehouse", "grain", "produce", "kentucky", "louisville", "barge"],
    },
    {
        "location_id": "loc-ok-oklahoma-city",
        "name": "Oklahoma City Grain Depot",
        "type": "warehouse",
        "coordinates": {"lat": 35.4676, "lon": -97.5164},
        "address": "2800 SE 59th St, Oklahoma City, OK 73129",
        "region": "South",
        "inventory_value_usd": 21_600_000.0,
        "reliability_index": 0.887,
        "avg_lead_time_hours": 32.0,
        "capacity_units": 50_000,
        "contract_sla": "48h regional, 72h national, 97% fill rate, wheat and grain sorghum, "
                        "BNSF rail, tornado contingency SLA",
        "tags": ["warehouse", "grain", "wheat", "sorghum", "oklahoma", "rail-access"],
    },
    {
        "location_id": "loc-mi-detroit",
        "name": "Detroit Agri Logistics Park",
        "type": "warehouse",
        "coordinates": {"lat": 42.3314, "lon": -83.0458},
        "address": "4800 Junction Ave, Detroit, MI 48210",
        "region": "Midwest",
        "inventory_value_usd": 27_900_000.0,
        "reliability_index": 0.901,
        "avg_lead_time_hours": 24.0,
        "capacity_units": 62_000,
        "contract_sla": "24h Great Lakes regional, 48h Northeast, 98% fill rate, "
                        "Ambassador Bridge proximity, Canadian grain import handling",
        "tags": ["warehouse", "grain", "michigan", "detroit", "cross-border"],
    },

    # ── Additional Regional Suppliers ─────────────────────────────────────────

    {
        "location_id": "loc-tx-amarillo",
        "name": "Amarillo Panhandle Elevator",
        "type": "supplier",
        "coordinates": {"lat": 35.2220, "lon": -101.8313},
        "address": "3700 SE 27th Ave, Amarillo, TX 79118",
        "region": "South",
        "inventory_value_usd": 13_700_000.0,
        "reliability_index": 0.863,
        "avg_lead_time_hours": 46.0,
        "capacity_units": 32_000,
        "contract_sla": "72h standard delivery, 96% fill rate, High Plains grain origin, "
                        "BNSF rail, wind/dust storm force majeure",
        "tags": ["grain", "wheat", "sorghum", "elevator", "texas", "panhandle"],
    },
    {
        "location_id": "loc-mt-billings",
        "name": "Billings Hi-Line Grain",
        "type": "supplier",
        "coordinates": {"lat": 45.7833, "lon": -108.5007},
        "address": "2100 Wyoming Ave, Billings, MT 59102",
        "region": "West",
        "inventory_value_usd": 8_900_000.0,
        "reliability_index": 0.821,
        "avg_lead_time_hours": 64.0,
        "capacity_units": 20_000,
        "contract_sla": "96h standard delivery, 94% fill rate, Montana spring wheat specialty, "
                        "blizzard/wildfire dual force majeure, BNSF Hi-Line access",
        "tags": ["grain", "spring-wheat", "elevator", "montana", "rail-access"],
    },
    {
        "location_id": "loc-ar-little-rock",
        "name": "Little Rock River Grain Hub",
        "type": "supplier",
        "coordinates": {"lat": 34.7465, "lon": -92.2896},
        "address": "7200 Scott Hamilton Dr, Little Rock, AR 72209",
        "region": "South",
        "inventory_value_usd": 16_800_000.0,
        "reliability_index": 0.878,
        "avg_lead_time_hours": 38.0,
        "capacity_units": 39_000,
        "contract_sla": "48h regional delivery, 97% fill rate, Arkansas River barge access, "
                        "rice and soybean specialty, UP rail connection",
        "tags": ["grain", "rice", "soybeans", "arkansas", "barge", "rail-access"],
    },
    {
        "location_id": "loc-ms-jackson",
        "name": "Jackson Delta Grain Hub",
        "type": "supplier",
        "coordinates": {"lat": 32.2988, "lon": -90.1848},
        "address": "5200 Clinton Blvd, Jackson, MS 39209",
        "region": "South",
        "inventory_value_usd": 14_300_000.0,
        "reliability_index": 0.856,
        "avg_lead_time_hours": 44.0,
        "capacity_units": 33_000,
        "contract_sla": "72h delivery, 96% fill rate, Mississippi Delta cotton/soybeans, "
                        "CN railroad access, flood season SLA extension",
        "tags": ["grain", "cotton", "soybeans", "mississippi", "delta", "rail-access"],
    },
]

# Deduplicate by location_id (belt-and-suspenders against copy-paste errors)
_seen_ids: set[str] = set()
_deduped: list[dict] = []
for _node in ERP_NODES:
    if _node["location_id"] not in _seen_ids:
        _seen_ids.add(_node["location_id"])
        _deduped.append(_node)
ERP_NODES = _deduped


# ─────────────────────────────────────────────────────────────────────────────
# DEMO WEATHER THREATS — synthetic threats whose polygons cover the ERP nodes
# ─────────────────────────────────────────────────────────────────────────────
#
# These ensure the Watcher Agent always produces threat_correlations on a cold
# start, so the full pipeline can demonstrate end-to-end autonomous operation.

DEMO_THREATS: list[dict] = [
    {
        "threat_id": "demo-winter-storm-central-plains",
        "source": "noaa",
        "event_type": "winter_storm",
        "severity": "severe",
        "certainty": "likely",
        "urgency": "expected",
        "headline": "Winter Storm Warning — Heavy snow and ice across Central Plains",
        "description": (
            "A powerful winter storm system is moving across Kansas, Nebraska, "
            "and Iowa producing 8-14 inches of snow with ice accumulations up to "
            "0.5 inches. Travel is strongly discouraged on I-70, I-80, and I-35 "
            "corridors. Grain elevator operations and truck logistics will be "
            "severely impacted for 48-72 hours."
        ),
        "affected_zone": {
            "type": "Polygon",
            "coordinates": [[
                [-102.0, 37.0], [-91.0, 37.0], [-91.0, 43.5],
                [-102.0, 43.5], [-102.0, 37.0],
            ]],
        },
        "centroid": {"lat": 40.25, "lon": -96.5},
        "status": "active",
    },
    {
        "threat_id": "demo-hurricane-watch-gulf-coast",
        "source": "noaa",
        "event_type": "hurricane",
        "severity": "extreme",
        "certainty": "possible",
        "urgency": "future",
        "headline": "Hurricane Watch — Gulf Coast from Corpus Christi to Mobile",
        "description": (
            "A tropical system in the Gulf of Mexico is expected to strengthen to "
            "hurricane force within 48 hours. Storm surge of 6-10 feet possible "
            "along the coast. Port operations at Houston, New Orleans, and Mobile "
            "should prepare for suspension. Barge traffic on the Mississippi River "
            "corridor may be halted."
        ),
        "affected_zone": {
            "type": "Polygon",
            "coordinates": [[
                [-98.0, 27.0], [-87.0, 27.0], [-87.0, 31.5],
                [-98.0, 31.5], [-98.0, 27.0],
            ]],
        },
        "centroid": {"lat": 29.25, "lon": -92.5},
        "status": "active",
    },
    {
        "threat_id": "demo-wildfire-california-central-valley",
        "source": "noaa",
        "event_type": "wildfire",
        "severity": "severe",
        "certainty": "observed",
        "urgency": "immediate",
        "headline": "Red Flag Warning — California Central Valley and Sierra Foothills",
        "description": (
            "Extreme fire weather conditions with offshore winds gusting to 60 mph "
            "and single-digit relative humidity. Active wildfire complexes threaten "
            "cold-chain distribution infrastructure in the San Joaquin and "
            "Sacramento Valleys. Air quality advisories in effect for Fresno, "
            "Bakersfield, and Modesto."
        ),
        "affected_zone": {
            "type": "Polygon",
            "coordinates": [[
                [-122.5, 34.5], [-117.5, 34.5], [-117.5, 39.0],
                [-122.5, 39.0], [-122.5, 34.5],
            ]],
        },
        "centroid": {"lat": 36.75, "lon": -120.0},
        "status": "active",
    },
    {
        "threat_id": "demo-tornado-watch-southern-plains",
        "source": "noaa",
        "event_type": "tornado",
        "severity": "extreme",
        "certainty": "possible",
        "urgency": "expected",
        "headline": "Tornado Watch — Oklahoma, Texas Panhandle, and Western Missouri",
        "description": (
            "Conditions are favourable for supercell thunderstorms capable of "
            "producing strong tornadoes (EF2+), destructive hail up to 3 inches, "
            "and damaging winds exceeding 80 mph. Several grain elevators and "
            "warehouse facilities are in the watch area."
        ),
        "affected_zone": {
            "type": "Polygon",
            "coordinates": [[
                [-103.0, 33.0], [-94.0, 33.0], [-94.0, 37.5],
                [-103.0, 37.5], [-103.0, 33.0],
            ]],
        },
        "centroid": {"lat": 35.25, "lon": -98.5},
        "status": "active",
    },
    {
        "threat_id": "demo-flood-warning-mississippi-corridor",
        "source": "noaa",
        "event_type": "flood",
        "severity": "moderate",
        "certainty": "likely",
        "urgency": "expected",
        "headline": "Flood Warning — Mississippi River from Memphis to New Orleans",
        "description": (
            "The Mississippi River is expected to reach major flood stage at "
            "Memphis and Baton Rouge within 72 hours. Barge traffic is restricted. "
            "Low-lying port and warehouse facilities should activate flood "
            "contingency plans."
        ),
        "affected_zone": {
            "type": "Polygon",
            "coordinates": [[
                [-92.5, 29.0], [-88.0, 29.0], [-88.0, 36.0],
                [-92.5, 36.0], [-92.5, 29.0],
            ]],
        },
        "centroid": {"lat": 32.5, "lon": -90.25},
        "status": "active",
    },
    {
        "threat_id": "demo-thunderstorm-great-lakes",
        "source": "noaa",
        "event_type": "severe_thunderstorm",
        "severity": "moderate",
        "certainty": "likely",
        "urgency": "immediate",
        "headline": "Severe Thunderstorm Warning — Great Lakes Region",
        "description": (
            "A line of severe thunderstorms with embedded rotation is crossing "
            "the Great Lakes states. Damaging winds up to 70 mph and large hail "
            "expected. Chicago intermodal operations, Milwaukee port, and Detroit "
            "logistics park may experience delays."
        ),
        "affected_zone": {
            "type": "Polygon",
            "coordinates": [[
                [-89.0, 40.5], [-82.0, 40.5], [-82.0, 44.5],
                [-89.0, 44.5], [-89.0, 40.5],
            ]],
        },
        "centroid": {"lat": 42.5, "lon": -85.5},
        "status": "active",
    },
]

# Mapping: threat_id → list of ERP location_ids inside that threat polygon.
# Used to set weather_threat_id on supply-latency-logs with cause == "weather".
_THREAT_ZONE_MEMBERS: dict[str, list[str]] = {
    "demo-winter-storm-central-plains": [
        "loc-ks-hutchinson", "loc-ks-dodge-city", "loc-ks-salina",
        "loc-ia-ames", "loc-ia-sioux-city", "loc-ia-cedar-rapids",
        "loc-ne-lincoln", "loc-ne-columbus",
        "loc-il-bloomington", "loc-il-peoria",
        "loc-mo-st-joseph",
    ],
    "demo-hurricane-watch-gulf-coast": [
        "loc-tx-houston-port", "loc-tx-corpus-christi", "loc-tx-beaumont",
        "loc-la-new-orleans", "loc-la-baton-rouge",
        "loc-ms-gulfport", "loc-al-mobile",
    ],
    "demo-wildfire-california-central-valley": [
        "loc-ca-fresno", "loc-ca-bakersfield", "loc-ca-modesto",
        "loc-ca-stockton", "loc-ca-salinas",
        "loc-ca-sacramento", "loc-ca-san-jose",
    ],
    "demo-tornado-watch-southern-plains": [
        "loc-ok-oklahoma-city", "loc-tx-amarillo",
        "loc-ks-hutchinson", "loc-ks-dodge-city",
        "loc-mo-st-joseph",
    ],
    "demo-flood-warning-mississippi-corridor": [
        "loc-la-new-orleans", "loc-la-baton-rouge",
        "loc-ms-gulfport", "loc-tn-memphis",
        "loc-ms-jackson", "loc-al-mobile",
    ],
    "demo-thunderstorm-great-lakes": [
        "loc-il-chicago", "loc-il-bloomington", "loc-il-peoria",
        "loc-wi-milwaukee", "loc-mi-detroit",
        "loc-oh-toledo", "loc-oh-columbus",
        "loc-in-indianapolis",
    ],
}

# Reverse lookup: location_id → threat_id (first match).
_LOCATION_TO_THREAT: dict[str, str] = {}
for _tid, _locs in _THREAT_ZONE_MEMBERS.items():
    for _loc in _locs:
        if _loc not in _LOCATION_TO_THREAT:
            _LOCATION_TO_THREAT[_loc] = _tid


# ─────────────────────────────────────────────────────────────────────────────
# Lookup tables for log generation
# ─────────────────────────────────────────────────────────────────────────────

_CARRIERS: dict[str, list[str]] = {
    "truck": [
        "JB Hunt Transport", "Schneider National", "Werner Enterprises",
        "Swift Transportation", "Old Dominion Freight", "XPO Logistics",
        "Knight Transportation", "Landstar System",
    ],
    "rail": [
        "BNSF Railway", "Union Pacific Railroad", "CSX Transportation",
        "Norfolk Southern", "Canadian National", "Kansas City Southern",
    ],
    "sea": [
        "Cargill Ocean Transport", "ADM Shipping", "Louis Dreyfus Armateurs",
        "Bunge Marine", "Pacific Basin Shipping",
    ],
    "air": [
        "FedEx Freight", "UPS Supply Chain Solutions", "Atlas Air Cargo",
        "Ameriflight",
    ],
}

_TRANSPORT_BY_TYPE: dict[str, list[str]] = {
    "supplier":            ["truck", "truck", "truck", "rail", "rail"],
    "port":                ["truck", "rail",  "sea",   "sea",  "sea"],
    "distribution_center": ["truck", "truck", "truck", "rail", "air"],
    "warehouse":           ["truck", "truck", "rail",  "rail"],
}

# (mean_delay_hours, std_dev) for each disruption cause
_DISRUPTION_PROFILES: dict[str, tuple[float, float]] = {
    "none":       (0.30, 0.80),
    "traffic":    (2.50, 1.50),
    "mechanical": (5.00, 2.50),
    "weather":    (11.0, 5.00),
    "customs":    (16.0, 7.00),
}

# Disruption probability weights [none, traffic, mechanical, weather, customs]
_DISRUPTION_WEIGHTS = [0.68, 0.14, 0.06, 0.08, 0.04]
_DISRUPTION_CAUSES  = ["none", "traffic", "mechanical", "weather", "customs"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_es_client() -> Elasticsearch:
    if settings.elastic_cloud_id:
        return Elasticsearch(
            cloud_id=settings.elastic_cloud_id,
            api_key=settings.elastic_api_key,
            request_timeout=60,
        )
    url = settings.elastic_url or "http://localhost:9200"
    api_key = settings.elastic_api_key or None
    return Elasticsearch(hosts=[url], api_key=api_key, request_timeout=60)


def _ensure_index(es: Elasticsearch, index_name: str, mapping_file: str) -> None:
    if es.indices.exists(index=index_name):
        print(f"  [ok]     index '{index_name}' already exists")
        return
    mapping_path = PROJECT_ROOT / "elasticsearch" / "mappings" / mapping_file
    body = json.loads(mapping_path.read_text(encoding="utf-8"))
    es.indices.create(index=index_name, body=body)
    print(f"  [created] index '{index_name}'")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ─────────────────────────────────────────────────────────────────────────────
# ERP Locations seeder
# ─────────────────────────────────────────────────────────────────────────────

def seed_erp_locations(
    es: Elasticsearch,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Index ERP_NODES into erp-locations.  Returns number of docs written."""

    if force and not dry_run:
        try:
            es.delete_by_query(
                index="erp-locations",
                body={"query": {"match_all": {}}},
                refresh=True,
            )
            print("  Wiped existing erp-locations documents.")
        except Exception as exc:
            print(f"  Warning: could not wipe erp-locations: {exc}")
    elif not force:
        count = es.count(index="erp-locations", body={"query": {"match_all": {}}})["count"]
        if count > 0:
            print(f"  Skipping: {count} documents already in erp-locations "
                  "(use --force to re-seed).")
            return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    actions = []
    for node in ERP_NODES:
        doc = {**node, "active": True, "country_code": "US", "last_updated": now_iso}
        # contract_sla_vector is omitted — requires a live E5-small model endpoint
        actions.append({
            "_index": "erp-locations",
            "_id":    node["location_id"],
            "_source": doc,
        })

    if dry_run:
        print(f"  [dry-run] would index {len(actions)} ERP location documents")
        return len(actions)

    success, errors = es_bulk(es, actions, raise_on_error=False, refresh=True)
    if errors:
        print(f"  Warning: {len(errors)} bulk errors during erp-locations seeding")
    print(f"  Indexed {success} ERP location documents.")
    return success


# ─────────────────────────────────────────────────────────────────────────────
# Weather-threats seeder
# ─────────────────────────────────────────────────────────────────────────────

def seed_weather_threats(
    es: Elasticsearch,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Index DEMO_THREATS into weather-threats.  Returns number of docs written.

    Synthetic threats have polygons that cover the seeded ERP nodes so the
    Watcher Agent always finds threat_correlations on a cold start.
    """
    if force and not dry_run:
        try:
            es.delete_by_query(
                index="weather-threats",
                body={"query": {"prefix": {"threat_id": "demo-"}}},
                refresh=True,
            )
            print("  Wiped existing demo weather-threats documents.")
        except Exception as exc:
            print(f"  Warning: could not wipe demo threats: {exc}")
    elif not force:
        try:
            count = es.count(
                index="weather-threats",
                body={"query": {"prefix": {"threat_id": "demo-"}}},
            )["count"]
            if count > 0:
                print(f"  Skipping: {count} demo threats already in weather-threats "
                      "(use --force to re-seed).")
                return 0
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    actions = []
    for threat in DEMO_THREATS:
        doc = {
            **threat,
            "effective": (now - timedelta(hours=6)).isoformat(),
            "expires": (now + timedelta(hours=72)).isoformat(),
            "onset": (now - timedelta(hours=3)).isoformat(),
            "nws_zone_ids": [],
            "raw_payload": {},
            "ingested_at": now.isoformat(),
        }
        actions.append({
            "_index": "weather-threats",
            "_id": threat["threat_id"],
            "_source": doc,
        })

    if dry_run:
        print(f"  [dry-run] would index {len(actions)} demo weather-threat documents")
        return len(actions)

    success, errors = es_bulk(es, actions, raise_on_error=False, refresh=True)
    if errors:
        print(f"  Warning: {len(errors)} bulk errors during weather-threats seeding")
    print(f"  Indexed {success} demo weather-threat documents.")
    return success


# ─────────────────────────────────────────────────────────────────────────────
# Supply-latency-logs seeder
# ─────────────────────────────────────────────────────────────────────────────

def _pick_transport_mode(node: dict, rng: random.Random) -> str:
    pool = _TRANSPORT_BY_TYPE.get(node["type"], ["truck"])
    return rng.choice(pool)


def _generate_log_doc(
    dest_node: dict,
    supplier_node: dict,
    ts: datetime,
    rng: random.Random,
    day_idx: int,
) -> dict:
    """Build one supply-latency-log document with realistic delay distribution."""

    mode = _pick_transport_mode(dest_node, rng)
    carrier = rng.choice(_CARRIERS[mode])

    # Expected transit: scale by haversine distance + mode baseline
    dist_km = _haversine_km(
        supplier_node["coordinates"]["lat"], supplier_node["coordinates"]["lon"],
        dest_node["coordinates"]["lat"],    dest_node["coordinates"]["lon"],
    )
    # avg speed by mode (km/h equivalent including loading): truck=60, rail=40, sea=18, air=500
    speed_map = {"truck": 60.0, "rail": 40.0, "sea": 18.0, "air": 500.0}
    transit_base = dist_km / speed_map[mode]
    # Add loading/handling time
    handling = {"truck": 2.0, "rail": 6.0, "sea": 12.0, "air": 1.5}[mode]
    expected_transit = round(transit_base + handling + rng.gauss(0, 1.5), 2)
    expected_transit = max(1.0, expected_transit)

    # Pick disruption event
    cause = rng.choices(_DISRUPTION_CAUSES, weights=_DISRUPTION_WEIGHTS, k=1)[0]

    # customs only makes sense for sea/air
    if cause == "customs" and mode not in ("sea", "air"):
        cause = "traffic"

    # Generate delay from disruption profile
    mean_d, std_d = _DISRUPTION_PROFILES[cause]
    raw_delay = rng.gauss(mean_d, std_d)
    # Seasonal amplification: Oct–Mar weather delays are 40% worse
    if cause == "weather" and ts.month in (10, 11, 12, 1, 2, 3):
        raw_delay *= 1.4
    delay_hours = round(max(0.0, raw_delay), 2)

    actual_transit = round(expected_transit + delay_hours, 2)

    # Shipment value: proportional to destination inventory, randomised ±30%
    base_value = dest_node["inventory_value_usd"] * 0.003   # ~0.3% of inventory per shipment
    shipment_value = round(base_value * rng.uniform(0.7, 1.3), 2)

    # Transport cost: per-km rate by mode + handling fee
    rate_per_km = {"truck": 3.50, "rail": 1.20, "sea": 0.35, "air": 18.0}[mode]
    cost_usd = round(dist_km * rate_per_km + handling * 150 + rng.gauss(0, 200), 2)
    cost_usd = max(200.0, cost_usd)

    on_time = delay_hours <= 2.0

    return {
        "@timestamp":            ts.isoformat(),
        "location_id":           dest_node["location_id"],
        "supplier_id":           supplier_node["location_id"],
        "route_id":              f"rt-{dest_node['location_id'][:8]}-{supplier_node['location_id'][:8]}",
        "origin":                {
            "lat": supplier_node["coordinates"]["lat"],
            "lon": supplier_node["coordinates"]["lon"],
        },
        "destination":           {
            "lat": dest_node["coordinates"]["lat"],
            "lon": dest_node["coordinates"]["lon"],
        },
        "expected_transit_hours": expected_transit,
        "actual_transit_hours":   actual_transit,
        "delay_hours":            delay_hours,
        "shipment_value_usd":     shipment_value,
        "disruption_cause":       cause,
        "weather_threat_id":      (
            _LOCATION_TO_THREAT.get(dest_node["location_id"])
            or _LOCATION_TO_THREAT.get(supplier_node["location_id"])
            if cause == "weather" else None
        ),
        "transport_mode":         mode,
        "carrier":                carrier,
        "cost_usd":               cost_usd,
        "on_time":                on_time,
    }


def seed_supply_latency_logs(
    es: Elasticsearch,
    nodes: list[dict],
    force: bool = False,
    dry_run: bool = False,
    days: int = 90,
    routes_per_node: int = 4,
) -> int:
    """
    Generate `days` × `routes_per_node` × len(nodes) log documents and bulk-index
    them into `supply-latency-logs` (TSDS) in ascending-timestamp order.

    Returns number of docs written.
    """
    if force and not dry_run:
        # TSDS does not support delete_by_query directly on data streams,
        # so we roll over / recreate. Safest: delete the backing index and recreate.
        try:
            es.indices.delete(index="supply-latency-logs", ignore_unavailable=True)
            print("  Deleted supply-latency-logs index for re-seed.")
            _ensure_index(es, "supply-latency-logs", "supply-latency-logs.json")
        except Exception as exc:
            print(f"  Warning: could not reset supply-latency-logs: {exc}")
    elif not force:
        try:
            count = es.count(
                index="supply-latency-logs",
                body={"query": {"match_all": {}}},
            )["count"]
            if count > 0:
                print(f"  Skipping: {count} documents already in supply-latency-logs "
                      "(use --force to re-seed).")
                return 0
        except Exception:
            pass  # index may not exist yet

    # Build a fast lookup: location_id → node
    node_by_id = {n["location_id"]: n for n in nodes}
    node_ids    = [n["location_id"] for n in nodes]

    # Assign each destination node a fixed set of "feeder" supplier nodes
    # (deterministic, using seeded RNG)
    rng = random.Random(42)
    routes: list[tuple[dict, dict]] = []  # (dest_node, supplier_node)
    for dest in nodes:
        candidates = [nid for nid in node_ids if nid != dest["location_id"]]
        rng.shuffle(candidates)
        suppliers = candidates[:routes_per_node]
        for sid in suppliers:
            routes.append((dest, node_by_id[sid]))

    # Generate one document per route per day, spread over the last `days` days
    now_utc  = datetime.now(timezone.utc)
    day_zero = now_utc - timedelta(days=days)

    total_docs = len(routes) * days
    print(f"  Generating {len(routes)} routes × {days} days = {total_docs} documents …")

    if dry_run:
        print(f"  [dry-run] would index {total_docs} supply-latency-log documents")
        return total_docs

    # Collect all actions, sort by timestamp so TSDS ingest is in order
    actions: list[dict] = []
    for day_idx in range(days):
        day_start = day_zero + timedelta(days=day_idx)
        for route_idx, (dest, supplier) in enumerate(routes):
            # Deterministic, unique hour offset per (route_idx, day_idx) avoids TSDS _id collisions
            hour_offset   = (route_idx * 7 + day_idx * 3) % 22      # 0–21
            minute_offset = (route_idx * 13 + day_idx * 5) % 60     # 0–59
            second_offset = (route_idx * 17 + day_idx * 11) % 60    # 0–59
            ts = day_start.replace(
                hour=hour_offset,
                minute=minute_offset,
                second=second_offset,
                microsecond=0,
            )

            doc = _generate_log_doc(dest, supplier, ts, rng, day_idx)
            actions.append({
                "_index":  "supply-latency-logs",
                "_source": doc,
            })

    # Sort ascending by @timestamp (TSDS best-practice)
    actions.sort(key=lambda a: a["_source"]["@timestamp"])

    # Bulk index in chunks of 500
    CHUNK = 500
    total_success = 0
    for i in range(0, len(actions), CHUNK):
        chunk = actions[i : i + CHUNK]
        success, errors = es_bulk(es, chunk, raise_on_error=False, refresh=False)
        total_success += success
        if errors:
            print(f"  Warning: {len(errors)} errors in chunk {i // CHUNK + 1}")
        pct = min(100, round((i + CHUNK) / len(actions) * 100))
        print(f"  Progress: {pct:3d}%  ({min(i + CHUNK, len(actions))}/{len(actions)})",
              end="\r", flush=True)

    # Final refresh so the data is immediately searchable
    es.indices.refresh(index="supply-latency-logs")
    print(f"\n  Indexed {total_success} supply-latency-log documents.")
    return total_success


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AegisChain demo data seeder — populates erp-locations, "
                    "weather-threats, and supply-latency-logs for a live globe view.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Wipe existing data and re-seed from scratch.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview document counts without writing anything.",
    )
    parser.add_argument(
        "--locations-only", action="store_true",
        help="Seed only erp-locations (skip threats and latency logs).",
    )
    parser.add_argument(
        "--threats-only", action="store_true",
        help="Seed only weather-threats (skip locations and latency logs).",
    )
    parser.add_argument(
        "--logs-only", action="store_true",
        help="Seed only supply-latency-logs (skip locations and threats).",
    )
    parser.add_argument(
        "--days", type=int, default=90,
        help="Number of historical days to generate (default: 90).",
    )
    parser.add_argument(
        "--routes-per-node", type=int, default=4,
        help="Number of supplier routes per destination node (default: 4).",
    )
    args = parser.parse_args()

    print("─" * 60)
    print("  AegisChain Demo Data Seeder")
    print("─" * 60)

    # Validate Elasticsearch configuration
    if not settings.elastic_url and not settings.elastic_cloud_id:
        print(
            "\nERROR: No Elasticsearch connection configured.\n"
            "  Copy backend/.env.example → backend/.env and set either:\n"
            "    ELASTIC_CLOUD_ID  + ELASTIC_API_KEY   (Elastic Cloud)\n"
            "    ELASTIC_URL       + ELASTIC_API_KEY   (self-hosted)\n"
        )
        sys.exit(1)

    print(f"\n  Connecting to Elasticsearch …", end=" ", flush=True)
    es = _build_es_client()
    try:
        info = es.info()
        print(f"ok  (v{info['version']['number']})")
    except Exception as exc:
        print(f"FAILED\n\n  Connection error: {exc}\n")
        sys.exit(1)

    # Ensure indices exist
    print("\n  Ensuring indices …")
    _ensure_index(es, "erp-locations",       "erp-locations.json")
    _ensure_index(es, "weather-threats",     "weather-threats.json")
    _ensure_index(es, "supply-latency-logs", "supply-latency-logs.json")

    # Determine which data sets to seed
    only_flag = args.locations_only or args.threats_only or args.logs_only
    seed_locations = args.locations_only or not only_flag
    seed_threats   = args.threats_only   or not only_flag
    seed_logs      = args.logs_only      or not only_flag

    # ── ERP Locations ─────────────────────────────────────────────────────
    if seed_locations:
        print(f"\n  Seeding erp-locations ({len(ERP_NODES)} nodes) …")
        n_locs = seed_erp_locations(es, force=args.force, dry_run=args.dry_run)
        print(f"  Done: {n_locs} location document(s) processed.")

    # ── Weather Threats ───────────────────────────────────────────────────
    if seed_threats:
        print(f"\n  Seeding weather-threats ({len(DEMO_THREATS)} demo threats) …")
        n_threats = seed_weather_threats(es, force=args.force, dry_run=args.dry_run)
        print(f"  Done: {n_threats} threat document(s) processed.")

    # ── Supply-latency-logs ───────────────────────────────────────────────
    if seed_logs:
        print(f"\n  Seeding supply-latency-logs "
              f"({args.days} days × {args.routes_per_node} routes/node) …")
        n_logs = seed_supply_latency_logs(
            es,
            nodes=ERP_NODES,
            force=args.force,
            dry_run=args.dry_run,
            days=args.days,
            routes_per_node=args.routes_per_node,
        )
        print(f"  Done: {n_logs} log document(s) processed.")

    print("\n" + "─" * 60)
    print("  Seed complete.  Start the backend and open the dashboard.")
    print("─" * 60 + "\n")


if __name__ == "__main__":
    main()
