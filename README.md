# WEM Energy Cost Modelling Tool

A full-stack Python application for modelling energy costs in the Western Australian Wholesale Electricity Market (WEM). It combines a live AEMO WA data pipeline, a linear/mixed-integer programming optimisation engine, an interactive Streamlit dashboard, a PostgreSQL database, and PDF/Excel export capabilities.

## Live App

> **Deployed on Streamlit Community Cloud:**  
> <https://auzvolt-wem-energy-cost-model.streamlit.app>  
> *(URL active after first deployment — see [docs/deployment.md](docs/deployment.md))*

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
pip install -r requirements.txt -r requirements-dev.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, AEMO_API_KEY, and AUTH_COOKIE_KEY
```

See `.env.example` for a full description of every variable.

### 4. Initialise the database

```bash
alembic upgrade head
```

### 5. Run the Streamlit app

```bash
streamlit run app/streamlit_app.py
```

> **Entrypoint:** `app/streamlit_app.py` is the single application entrypoint.
> When deploying to Streamlit Community Cloud, set **Main file path** to
> `app/streamlit_app.py`.

## Deployment

For full deployment instructions (Streamlit Community Cloud + Supabase PostgreSQL),
see **[docs/deployment.md](docs/deployment.md)**.

### Required secrets (Streamlit Cloud)

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `AEMO_API_BASE_URL` | AEMO WA Open Data base URL |
| `AEMO_API_KEY` | AEMO APIM subscription key (blank for public data) |
| `AUTH_COOKIE_KEY` | Random 32-byte hex secret for session cookies |
| `LOG_LEVEL` | Log level (`INFO` recommended) |

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
  streamlit_app.py   — Streamlit entry point
  main.py            — legacy entry point (redirects to streamlit_app)
  db/
    models.py        — SQLAlchemy ORM models
    session.py       — DB session factory
  pipeline/
    aemo_client.py   — AEMO WA API client
  optimisation/      — Pyomo LP/MILP models
  exports/
    pdf_export.py    — PDF report generation
    excel_export.py  — Excel workbook export
docs/
  deployment.md      — Deployment guide (Streamlit Cloud + PostgreSQL)
migrations/          — Alembic migration scripts
tests/               — pytest test suite
.streamlit/
  config.toml        — Streamlit server and theme configuration
```

## License

MIT
