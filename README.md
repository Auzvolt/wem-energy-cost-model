# WEM Energy Cost Modelling Tool

![Coverage](https://img.shields.io/badge/coverage-unknown-lightgrey)

A full-stack Python application for modelling energy costs in the Western Australian Wholesale Electricity Market (WEM). It combines a live AEMO WA data pipeline, a linear/mixed-integer programming optimisation engine, an interactive Streamlit dashboard, a PostgreSQL database, and PDF/Excel export capabilities.

## Live App

> **Deployed on Streamlit Community Cloud:**  
> <https://auzvolt-wem-energy-cost-model.streamlit.app>  
> *(URL active after first deployment — see [docs/deployment.md](docs/deployment.md))*

## Architecture

```mermaid
graph LR
    A[AEMO WA Open Data API] -->|fetch dispatch/price data| B(pipeline/ingest)
    B -->|store raw & transformed| C[(PostgreSQL)]
    C -->|load scenarios & market data| D(Pyomo LP/MILP Engine)
    D -->|optimised dispatch & costs| E[Streamlit UI]
    E -->|generate| F[PDF / Excel Reports]
```

## Components

| Component | Description |
|-----------|-------------|
| **Data Pipeline** | Fetches market data from the AEMO WA Open Data API (dispatch intervals, facility prices, load forecasts, FCESS, forward prices) |
| **LP/MILP Optimiser** | Pyomo-based linear and mixed-integer programming model for least-cost dispatch, BESS scheduling, EV fleet, genset, and load flexibility |
| **Streamlit UI** | Interactive web dashboard for scenario configuration, results visualisation, and report generation |
| **PostgreSQL** | Stores market data, scenarios, optimisation results, and audit history via SQLAlchemy + Alembic |
| **PDF/Excel Exports** | ReportLab-based PDF reports and openpyxl-based Excel workbooks for stakeholder delivery |

## Prerequisites

- Python ≥ 3.11
- PostgreSQL ≥ 14
- A solver compatible with Pyomo (e.g. [GLPK](https://www.gnu.org/software/glpk/) or [CBC](https://github.com/coin-or/Cbc))

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/auzvolt/wem-energy-cost-model.git
cd wem-energy-cost-model
```

### 2. Install dependencies

**Recommended — using [uv](https://github.com/astral-sh/uv):**

```bash
uv sync
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

**Alternative — using pip:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, AUTH_COOKIE_KEY, and any optional vars
```

See the [Environment Variables](#environment-variables) table below for a full description.

### 4. Initialise the database

```bash
alembic upgrade head
```

### 5. Run the Streamlit app

```bash
streamlit run app/streamlit_app.py
```

> **Entrypoint:** `app/streamlit_app.py` is the single application entrypoint.  
> When deploying to Streamlit Community Cloud, set **Main file path** to `app/streamlit_app.py`.

## Environment Variables

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@localhost:5432/wem_energy` | ✅ Required |
| `AEMO_API_BASE_URL` | AEMO WA Open Data base URL | `https://data.wa.aemo.com.au` | Optional (has default) |
| `AEMO_API_KEY` | AEMO APIM subscription key | *(leave blank for public data)* | Optional |
| `AUTH_COOKIE_KEY` | 32-byte hex secret for session cookies | `python -c "import secrets; print(secrets.token_hex(32))"` | ✅ Required |
| `LOG_LEVEL` | Python log level | `INFO` | Optional (default: `INFO`) |
| `PIPELINE_SCHEDULE_CRON` | Cron expression for ingestion schedule (UTC) | `0 22 * * *` (= 06:00 AWST daily) | Optional |
| `PIPELINE_REFRESH_MINUTES` | Polling interval for scheduler loop mode | `60` | Optional |
| `ALERT_CHANNEL` | Alert delivery channel | `log` / `email` / `slack` | Optional (default: `log`) |
| `SMTP_HOST` | SMTP server hostname | `smtp.example.com` | When `ALERT_CHANNEL=email` |
| `SMTP_PORT` | SMTP server port | `587` | When `ALERT_CHANNEL=email` |
| `ALERT_EMAIL_FROM` | Sender address for alert emails | `alerts@example.com` | When `ALERT_CHANNEL=email` |
| `ALERT_EMAIL_TO` | Recipient address for alert emails | `team@example.com` | When `ALERT_CHANNEL=email` |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL | `https://hooks.slack.com/services/…` | When `ALERT_CHANNEL=slack` |

## Deployment

For full deployment instructions (Streamlit Community Cloud + Supabase PostgreSQL), see **[docs/deployment.md](docs/deployment.md)**.

## Development

### Run tests

```bash
pytest --cov=app
```

### Lint and type-check

```bash
ruff check .
ruff format --check .
mypy app/
```

### Create a new database migration

```bash
alembic revision --autogenerate -m "description_of_change"
alembic upgrade head
```

## Project Structure

```
app/
  config.py               — environment variable loading (Settings class)
  streamlit_app.py        — Streamlit entry point
  main.py                 — legacy entry point (redirects to streamlit_app)
  assets/
    models.py             — asset dataclasses (GeneratorAsset, BatteryAsset, DemandResponseAsset)
    defaults.py           — default asset parameters
    repository.py         — asset CRUD operations
  assumptions/
    models.py             — AssumptionSet / AssumptionEntry dataclasses
    seeds.py              — WA default assumption data (tariffs, BESS, solar, capex)
    io.py                 — JSON and Excel import/export
    audit.py              — assumption change audit trail
  db/
    models.py             — SQLAlchemy ORM models
    session.py            — async DB session factory
  exports/
    pdf_export.py         — ReportLab PDF report generation
    excel_export.py       — openpyxl Excel workbook export
  financial/              — cashflow, NPV, IRR, stakeholder value models
  models/                 — shared domain models (scenario, project, site)
  optimisation/
    engine.py             — WEMModel Pyomo base class
    bess.py               — BESS charge/discharge LP model
    solar.py              — Solar PV generation model
    genset.py             — Diesel/gas genset model
    capacity.py           — Capacity credit (RCM) model
    fcess.py              — FCESS obligations model
    dispatch.py           — Economic dispatch model
    auto_size.py          — Automated asset sizing
    ev_fleet.py           — EV fleet smart-charging model
    load_flex.py          — Load flexibility / demand response model
    rcm.py                — Reserve Capacity Mechanism model
  pages/
    1_📥_Data_Status.py   — Pipeline health and last ingest times
    2_📋_Project_Designer.py — Asset and scenario configuration
    3_📈_Results.py       — Optimisation outputs and dispatch schedules
    4_📊_Reports.py       — PDF/Excel report generation
    5_⚙️_Assumptions.py  — Assumption library (admin only)
  pipeline/
    aemo_client.py        — AEMO WA API client (base class + implementations)
    ingest.py             — Market data ingestion orchestrator
    transform.py          — Raw → normalised data transformation
    interval_import.py    — NEM12 / CSV interval meter import
    forward_price_connector.py — Forward price curve connector
    backfill.py           — Historical data backfill tool
    capacity_price_connector.py — Capacity market price connector
    fcess_connector.py    — FCESS data connector
    wholesale_price_connector.py — Spot price connector
    health.py             — Pipeline health checks
    scheduler.py          — Background ingestion scheduler
    alerts.py             — Alert dispatch (log/email/Slack)
    schemas.py            — Pipeline data schemas
  simulation/             — Monte Carlo and sensitivity analysis
  tariff/                 — Western Power network tariff models
  ui/
    auth.py               — Streamlit authentication (login/logout)
    nav.py                — Sidebar navigation
    session.py            — Session state key constants
    charts.py             — Reusable Plotly chart components
    comparison.py         — Scenario comparison UI
    interval_upload.py    — Interval meter upload UI
    assumptions.py        — Assumption import/export UI
docs/
  deployment.md           — Deployment guide (Streamlit Cloud + PostgreSQL)
  user-guide.md           — End-user guide
  developer-guide.md      — Developer and contributor guide
  aemo_wa_api_mapping.md  — AEMO API field mapping reference
  wem-fcess-rules.md      — FCESS rules reference
  western-power-tariffs.md — Western Power tariff schedule reference
migrations/               — Alembic migration scripts
tests/                    — pytest test suite
.streamlit/
  config.toml             — Streamlit server and theme configuration
```

## License

MIT
