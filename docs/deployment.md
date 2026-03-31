# Deployment Guide

This document describes how to deploy the WEM Energy Cost Modelling Tool to
**Streamlit Community Cloud** with a cloud-hosted **PostgreSQL** database.

---

## Overview

| Layer | Service |
|-------|---------|
| Frontend / App | Streamlit Community Cloud (free tier) |
| Database | Supabase free tier **or** Neon free tier |
| Source control | GitHub — `auzvolt/wem-energy-cost-model` |

Streamlit Community Cloud redeploys automatically on every push to `main`.

---

## 1. Provision a Cloud PostgreSQL Database

### Option A — Supabase (recommended)

1. Sign in at <https://supabase.com> and create a new project.
2. Wait for the project to initialise, then navigate to **Project Settings →
   Database**.
3. Copy the **Connection string (URI)** — it looks like:
   ```
   postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres
   ```
4. Keep this value; you will need it in step 4.

> **Tip:** Supabase exposes a connection pooler on port 6543.  Use the direct
> port 5432 URI for Alembic migrations and the pooler URI for the running app
> if you want PgBouncer support.

### Option B — Neon

1. Sign in at <https://neon.tech> and create a new project.
2. Copy the connection string from the dashboard:
   ```
   postgresql://neondb_owner:<password>@<host>.neon.tech/neondb?sslmode=require
   ```

---

## 2. Run Alembic Migrations Against the Cloud Database

On your local machine (with the virtual environment activated):

```bash
# Export the cloud DATABASE_URL temporarily
export DATABASE_URL="postgresql://..."   # paste your cloud URI here

# Apply all migrations
alembic upgrade head
```

All 9 tables will be created.  Verify in the Supabase / Neon dashboard under
**Table Editor**.

---

## 3. Fork / Connect the Repository on Streamlit Community Cloud

1. Sign in at <https://share.streamlit.io>.
2. Click **New app**.
3. Select repository: `auzvolt/wem-energy-cost-model`, branch: `main`.
4. Set **Main file path** to `app/streamlit_app.py`.
5. Click **Advanced settings** — do **not** add secrets here yet; see step 4.
6. Click **Deploy** — the first build will likely fail because secrets are
   missing.  That is expected.

---

## 4. Configure Secrets in Streamlit Community Cloud

In the Streamlit Cloud dashboard, open your app → **⋮ menu → Settings →
Secrets**.  Paste the following TOML block, filling in real values:

```toml
DATABASE_URL = "postgresql://..."        # cloud DB URI from step 1
AEMO_API_BASE_URL = "https://data.wa.aemo.com.au"
AEMO_API_KEY = ""                        # leave blank for public-data access
AUTH_COOKIE_KEY = "<random 32-byte hex>" # generate: python -c "import secrets; print(secrets.token_hex(32))"
LOG_LEVEL = "INFO"
```

> **Security:** Never commit real secret values to source control.  The
> `.env.example` file contains only placeholder values and is safe to commit.

After saving, Streamlit Cloud will automatically redeploy the app.

---

## 5. Verify the Deployment (Smoke Test)

Once the app is running, confirm the following:

- [ ] App loads without import errors or DB connection errors
- [ ] You can log in (create a user account if first run)
- [ ] You can create a new project / scenario
- [ ] You can run a simulation (uses synthetic price data if AEMO data is not
      yet ingested)
- [ ] Results page renders correctly with charts and a summary table
- [ ] You can export a PDF report and an Excel workbook

---

## 6. Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `AEMO_API_BASE_URL` | ✅ | `https://data.wa.aemo.com.au` | AEMO WA Open Data base URL |
| `AEMO_API_KEY` | ✗ | `""` | AEMO APIM subscription key (public data: leave blank) |
| `AUTH_COOKIE_KEY` | ✅ | — | Secret key for session cookie signing |
| `LOG_LEVEL` | ✗ | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 7. Local Development

```bash
# Clone and set up
git clone https://github.com/auzvolt/wem-energy-cost-model.git
cd wem-energy-cost-model
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — set DATABASE_URL to a local or cloud PostgreSQL instance

# Initialise the database
alembic upgrade head

# Run
streamlit run app/streamlit_app.py
```

---

## 8. Updating the Application

```bash
git push origin main
```

Streamlit Community Cloud detects the push and redeploys automatically.
Migrations are **not** run automatically — if a release includes a new
migration, run `alembic upgrade head` manually against the cloud database
before (or immediately after) pushing to `main`.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `sqlalchemy.exc.OperationalError` on startup | Bad `DATABASE_URL` | Double-check the URI in Streamlit secrets; ensure the DB allows inbound connections |
| `ModuleNotFoundError` on deploy | Missing package in `requirements.txt` | Add the package and push |
| Auth loop / session errors | Missing or wrong `AUTH_COOKIE_KEY` | Set a valid random secret in Streamlit secrets |
| AEMO API 401 | Wrong or missing `AEMO_API_KEY` | Set the key, or leave blank for public-data-only endpoints |
