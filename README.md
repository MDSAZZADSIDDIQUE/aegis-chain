# AegisChain — Autonomous Cognitive Supply Chain Immune System

AegisChain is a next-generation supply chain management platform that uses autonomous agents and real-time data to monitor, predict, and mitigate disruptions.

## Project Structure

- `backend/`: FastAPI application (Python)
- `frontend/`: Next.js application (React/TypeScript)
- `elasticsearch/`: Configuration and mappings for the Elastic stack

## Prerequisites

- **Python 3.10+** (Backend)
- **Node.js 18+** (Frontend)
- **Elasticsearch 8.17+** (Cloud or Local)
- **Anthropic API Key** (for agentic reasoning)
- **Mapbox Token** (for geospatial visualization)

## Getting Started

### 1. Backend Setup

1.  Navigate to the `backend/` directory:
    ```bash
    cd backend
    ```
2.  Create and activate a virtual environment:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate  # Windows
    # source venv/bin/activate  # macOS/Linux
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Configure environment variables:
    -   Copy `.env.example` to `.env`.
    -   Fill in your `ELASTIC_CLOUD_ID`, `ELASTIC_API_KEY`, `ANTHROPIC_API_KEY`, etc.
5.  Seed local data (Optional):
    ```bash
    python scripts/seed_demo_data.py
    ```
6.  Run the server:
    ```bash
    python run_server.py
    ```
    The API will be available at [http://localhost:8000](http://localhost:8000).

### 2. Frontend Setup

1.  Navigate to the `frontend/` directory:
    ```bash
    cd frontend
    ```
2.  Install dependencies:
    ```bash
    npm install
    ```
3.  Configure environment variables:
    -   Copy `.env.example` to `.env`.
    -   Set `NEXT_PUBLIC_MAPBOX_TOKEN` and `NEXT_PUBLIC_API_URL`.
4.  Run the development server:
    ```bash
    npm run dev
    ```
    The app will be available at [http://localhost:3000](http://localhost:3000).

## Infrastructure

The project uses Elasticsearch for real-time threat indexing and anomaly detection. Ensure your Elastic cluster is reachable and configured via the backend `.env`.
