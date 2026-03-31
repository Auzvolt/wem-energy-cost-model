# WEM Energy Cost Modelling Tool

A full-stack Python application for modelling energy costs in the Western Australian Wholesale Electricity Market (WEM). It combines a live AEMO WA data pipeline, a linear/mixed-integer programming optimisation engine, an interactive Streamlit dashboard, a PostgreSQL database, and PDF/Excel export capabilities.

## Components

| Component | Description |
|-----------|-------------|
| **Data Pipeline** | Fetches market data from the AEMO WA Open Data API (dispatch intervals, facility prices, load forecasts) |
| **LP/MILP Optimiser** | Pyomo-based linear and mixed-integer programming model for least-cost dispatch and energy procurement |
| **Streamlit UI** | Interactive web dashboard for scenario configuration, results visualisation, and report generation |
| **PostgreSQL** | Stores market data, scenarios, optimisation results, and audit history via SQLAlchemy + Alembic |
| **PDF/Excel Exports** | ReportLab-based PDF reports and openpyxl-based Excel workbooks for stakeholder delivery |

## Prerequisites

- Python ≥ 3.11
- PostgreSQL ≥ 14
- A solver compatible with Pyomo (e.g. [GLPK](https://www.gnu.org/software/glpk/) or [CBC](https://github.com/coin-or/Cbc))

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/auzvolt/wem-energy-cost-model.git
cd wem-energy-cost-model
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your DATABASE_URL and AEMO_API_KEY
```

### 4. Initialise the database

```bash
alembic upgrade head
```

### 5. Run the Streamlit app

```bash
streamlit run app/main.py
```

## Development

### Run tests

```bash
pytest
```

### Lint and type-check

```bash
ruff check .
mypy app/
```

### Create a new migration

```bash
alembic revision --autogenerate -m "description_of_change"
```

## Project Structure

```
app/
  config.py          — environment variable loading
  main.py            — Streamlit entry point
  db/
    models.py        — SQLAlchemy ORM models
    session.py       — DB session factory
  pipeline/
    aemo_client.py   — AEMO WA API client
  optimiser/
    lp_model.py      — Pyomo LP/MILP model
  exports/
    pdf_export.py    — PDF report generation
    excel_export.py  — Excel workbook export
migrations/          — Alembic migration scripts
tests/               — pytest test suite
```

## License

MIT
