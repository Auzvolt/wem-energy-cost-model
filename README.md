# WEM Energy Cost Modelling Tool

A full-stack energy cost modelling application for the Western Australian Wholesale Energy Market (SWIS), combining real-time AEMO WA data, Pyomo optimisation, and an interactive Streamlit interface.

## Architecture

```
wem-energy-cost-model/
├── app/                   # Streamlit UI
├── pipeline/              # AEMO WA data ingestion & processing
├── optimisation/          # Pyomo dispatch optimisation engine
├── assets/                # Energy asset library (generators, storage, loads)
├── financial/             # Financial modelling (LCOE, NPV, revenue)
├── db/                    # PostgreSQL schema & migrations
├── tests/                 # Pytest test suite
├── .env.example           # Required environment variables
└── pyproject.toml         # Dependencies & tooling config
```

## Key Features

- **Data Pipeline**: Ingests AEMO WA SCADA, price, and facility data via public APIs
- **Asset Library**: Configurable generators, battery storage, and demand response assets
- **Optimisation Engine**: Pyomo-based least-cost dispatch and scheduling
- **Financial Modelling**: LCOE, NPV, IRR, and revenue stack analysis
- **Interactive UI**: Streamlit dashboard with scenario comparison and export

## Requirements

- Python 3.11+
- PostgreSQL 15+
- Solver: CBC (open-source, bundled via `cylp` or `coinor-cbc`)

## Setup

```bash
cp .env.example .env
# Fill in your database credentials and API keys
pip install -e ".[dev]"
python -m db.migrate
streamlit run app/main.py
```

## Environment Variables

See `.env.example` for all required variables.
