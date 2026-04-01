# Developer Guide — WEM Energy Cost Modelling Tool

This guide is for developers contributing to or extending the WEM Energy Cost Modelling Tool.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Streamlit UI (app/)                         │
│  pages/  ←→  ui/  ←→  optimisation/  ←→  pipeline/  ←→  exports/  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ SQLAlchemy async
                         ┌──────▼──────┐
                         │  PostgreSQL  │
                         │  (Alembic)  │
                         └─────────────┘
```

### Module Map

| Module | Responsibility |
|--------|---------------|
| `app/config.py` | Load env vars into `Settings` dataclass |
| `app/streamlit_app.py` | Streamlit entry point, auth gate, page routing |
| `app/db/models.py` | SQLAlchemy ORM models |
| `app/db/session.py` | Async `AsyncSession` factory |
| `app/pipeline/aemo_client.py` | AEMO WA Open Data API base client |
| `app/pipeline/ingest.py` | Market data ingestion orchestrator |
| `app/pipeline/transform.py` | Raw → normalised data transforms |
| `app/pipeline/interval_import.py` | NEM12 / CSV interval meter import |
| `app/pipeline/forward_price_connector.py` | Forward price curve fetcher |
| `app/pipeline/backfill.py` | Historical data backfill |
| `app/pipeline/capacity_price_connector.py` | Capacity market price fetcher |
| `app/pipeline/fcess_connector.py` | FCESS data fetcher |
| `app/pipeline/wholesale_price_connector.py` | Spot price fetcher |
| `app/pipeline/health.py` | Pipeline health checks |
| `app/pipeline/scheduler.py` | Background ingestion scheduler |
| `app/pipeline/alerts.py` | Alert dispatch (log / email / Slack) |
| `app/optimisation/engine.py` | `WEMModel` Pyomo base class |
| `app/optimisation/bess.py` | BESS charge/discharge LP |
| `app/optimisation/solar.py` | Solar PV generation model |
| `app/optimisation/genset.py` | Diesel/gas genset MILP |
| `app/optimisation/capacity.py` | Capacity credit (RCM) model |
| `app/optimisation/fcess.py` | FCESS obligation model |
| `app/optimisation/dispatch.py` | Economic dispatch |
| `app/optimisation/auto_size.py` | Automated asset sizing |
| `app/optimisation/ev_fleet.py` | EV fleet smart-charging |
| `app/optimisation/load_flex.py` | Load flexibility / demand response |
| `app/optimisation/rcm.py` | Reserve Capacity Mechanism |
| `app/assets/models.py` | Asset dataclasses (Generator, Battery, DemandResponse) |
| `app/assets/defaults.py` | Default asset parameters |
| `app/assets/repository.py` | Asset CRUD operations |
| `app/assumptions/models.py` | `AssumptionSet` / `AssumptionEntry` dataclasses |
| `app/assumptions/seeds.py` | WA default assumption data with source citations |
| `app/assumptions/io.py` | JSON / Excel import and export |
| `app/assumptions/audit.py` | Assumption change audit trail |
| `app/exports/pdf_export.py` | ReportLab PDF generation |
| `app/exports/excel_export.py` | openpyxl Excel workbook generation |
| `app/financial/` | Cashflow, NPV, IRR, stakeholder value |
| `app/simulation/` | Monte Carlo and sensitivity analysis |
| `app/tariff/` | Western Power network tariff models |
| `app/ui/auth.py` | Streamlit login/logout |
| `app/ui/nav.py` | Sidebar navigation |
| `app/ui/charts.py` | Reusable Plotly chart components |
| `app/ui/comparison.py` | Scenario comparison UI |
| `app/ui/interval_upload.py` | Interval meter upload UI |
| `app/ui/assumptions.py` | Assumption import/export UI |

---

## How to Add a New Asset Type

### 1. Add the asset dataclass

In `app/assets/models.py`, define a new dataclass following the existing pattern:

```python
@dataclass
class HydrogenElectrolyserAsset:
    name: str
    rated_power_kw: float
    efficiency_kwh_per_kg: float = 55.0
    # ... other parameters
```

Add default parameters to `app/assets/defaults.py`.

### 2. Add the Pyomo optimisation model

Create `app/optimisation/electrolyser.py` following the pattern in `app/optimisation/bess.py`:

- Define variables: power consumption, hydrogen production
- Add constraints: rated power limit, ramp limits if applicable
- Define the cost contribution to the objective function
- Export a function `add_electrolyser_to_model(model, asset)` that augments the `WEMModel`

### 3. Wire into the optimisation engine

In `app/optimisation/engine.py`, import and call your new `add_electrolyser_to_model()` function when building the model. The engine aggregates all asset contributions before solving.

### 4. Add to the Streamlit UI

In `app/pages/2_📋_Project_Designer.py`, add a new option to the asset type selector and render a configuration form for the new asset's parameters.

### 5. Write tests

Add `tests/test_electrolyser.py` following `tests/test_bess.py` as a template. Test the model builds without error, constraints are correctly enforced, and edge cases (zero capacity, fully constrained period) are handled.

---

## How to Add a New Western Power Tariff

Western Power network tariffs are defined in two places:

1. **`app/assumptions/seeds.py`** — the `WA_TARIFF_SCHEDULES` list contains one entry per tariff. Each entry has fields: `tariff_code`, `tariff_name`, `network_charge_dollar_per_kwh`, `capacity_charge_dollar_per_kw_month`, and `applicable_regions`. Add a new dict to this list following the existing pattern, with source citation comments pointing to the Western Power Network Tariff Schedule.

2. **`app/tariff/`** — if the new tariff has a novel structure (e.g. time-of-use charging, demand windows different from existing tariffs), add a new tariff class in `app/tariff/` implementing the charge calculation logic.

After adding, run `pytest tests/test_tariff.py` to verify the tariff calculations are correct.

---

## How to Add a New AEMO Data Connector

All AEMO WA connectors follow the `BaseAEMOClient` pattern defined in `app/pipeline/aemo_client.py`.

To add a new connector (e.g. for a new AEMO endpoint):

1. Create `app/pipeline/my_new_connector.py`
2. Subclass `BaseAEMOClient` (or the closest existing connector)
3. Override the `fetch()` method to call the specific AEMO endpoint
4. Implement `transform()` to normalise the raw API response into the internal schema
5. Call your connector from `app/pipeline/ingest.py` in the ingestion orchestrator

Example skeleton:

```python
from app.pipeline.aemo_client import BaseAEMOClient

class MyNewConnector(BaseAEMOClient):
    ENDPOINT = "/public/Market/MyEndpoint/list"

    async def fetch(self, from_date: str, to_date: str) -> list[dict]:
        params = {"fromDate": from_date, "toDate": to_date}
        return await self._get(self.ENDPOINT, params=params)

    def transform(self, raw: list[dict]) -> list[MySchema]:
        return [MySchema.from_api_row(row) for row in raw]
```

The base class handles retry logic (via `tenacity`), authentication headers, rate limiting, and error logging.

Write tests in `tests/test_my_new_connector.py` using `unittest.mock` to patch the HTTP client, following `tests/test_aemo_client.py` as a template.

---

## Database Migration Workflow

The project uses **Alembic** for database migrations.

### Creating a new migration

```bash
# 1. Make your ORM model changes in app/db/models.py
# 2. Generate the migration
alembic revision --autogenerate -m "add_electrolyser_table"

# 3. Review the generated file in migrations/versions/
#    Verify the upgrade() and downgrade() functions are correct

# 4. Apply the migration
alembic upgrade head

# 5. Run tests to confirm nothing broke
pytest --cov=app
```

### Migration file naming

Alembic auto-generates a hex revision ID. The message you pass with `-m` becomes the description. Keep descriptions concise and snake_cased (e.g. `add_electrolyser_table`, `add_index_on_dispatch_timestamp`).

### Important: migration lock

**When a migration is in progress, do not start other development tasks that touch the DB schema.** Migrations are a development lock — finish and commit the migration before branching off schema-dependent features.

### Alembic with Supabase (production)

For production (Supabase), use the **direct connection** URL (not the transaction pooler) when running migrations:

```bash
DATABASE_URL=postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres alembic upgrade head
```

---

## Testing

### Running the test suite

```bash
pytest --cov=app
```

This runs all tests in `tests/` and reports coverage for the `app/` package.

### Running a specific test file

```bash
pytest tests/test_bess.py -v
```

### Coverage threshold

Coverage is tracked via the CI pipeline. Keep `app/` coverage above 80%. New modules should have accompanying tests before merging.

### Test conventions

- Tests live in `tests/` and mirror the `app/` module structure
- Use `unittest.mock.AsyncMock` for async functions and `MagicMock` for sync
- Use `pytest.fixture` for shared setup
- Tests must be deterministic — avoid `time.sleep()`, network calls, or file-system side-effects without mocking

### Lint and type-check before committing

```bash
ruff check .
ruff format --check .
mypy app/
```

Fix all errors before committing. The CI pipeline enforces clean lint, format, and mypy.

---

## Deployment

See [docs/deployment.md](deployment.md) for full deployment instructions (Streamlit Community Cloud + Supabase PostgreSQL).

---

## Contributing

1. Branch from `main` using the naming convention `feat/issue-<N>-<short-description>`
2. Write tests first (TDD)
3. Keep PRs small — one issue per PR
4. Run `ruff`, `mypy`, and `pytest` before pushing
5. Link the PR to its GitHub issue with `Closes #N` in the PR description
