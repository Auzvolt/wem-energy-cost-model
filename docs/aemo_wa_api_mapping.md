# AEMO WA Public Data Portal — API Mapping

> Covers issues #2 (wholesale price APIs), #3 (FCESS APIs), #4 (capacity mechanism APIs).
>
> Base portal: <https://data.wa.aemo.com.au/>
> Public CSV base URL: `https://data.wa.aemo.com.au/public/public-data/dataFiles/`

---

## 1. Wholesale Energy Price APIs (Issue #2)

### 1.1 Balancing Summary (5-min interval MCPs — post-reform Oct 2023+)

| Field | Value |
|---|---|
| **Endpoint pattern** | `GET https://data.wa.aemo.com.au/public/public-data/dataFiles/balancing-summary/BalancingSummary_{YYYYMMDD}.csv` |
| **Frequency** | One file per trading day |
| **Format** | CSV (comma-separated, UTF-8) |
| **Availability** | From ~2023-10-01 onwards (post WEM reform) |
| **Rate limits** | No documented limit; AEMO recommends < 1 req/sec to avoid blocks |
| **Pagination** | None — one file per day |

**Key fields:**

| CSV Column | Type | Units | Description |
|---|---|---|---|
| `TradingDate` | date | AWST | Trading date (AWST) |
| `TradingInterval` | int | — | 1–288 (5-min intervals per day, AWST) |
| `IntervalStart` | datetime | AWST | Start of 5-min dispatch interval |
| `BalancingPrice` | float | AUD/MWh | Market Clearing Price (MCP) for energy |
| `ForecastGeneration` | float | MW | Forecast generation |
| `ActualGeneration` | float | MW | Actual metered generation |
| `Load` | float | MW | Actual system load |
| `Reserve` | float | MW | Reserve margin |
| `Surplus` | float | MW | Generation surplus |

**Notes:**
- All timestamps in AWST (UTC+8); stored in DB as UTC
- Pre-reform data uses a different file/schema; see legacy endpoints below
- MCP can be negative (floor: AUD –1,000/MWh) or high (cap: AUD 500/MWh pre-reform, AUD 17,500/MWh post-reform)

### 1.2 Legacy Balancing Summary (pre-reform, < 2023-10-01)

| Field | Value |
|---|---|
| **Endpoint pattern** | `GET https://data.wa.aemo.com.au/public/public-data/dataFiles/trading-report/TradingReport_{YYYYMMDD}.csv` |
| **Interval** | 30-min trading intervals (48 per day) |
| **Key column** | `BalancingPrice` (AUD/MWh) |

---

## 2. FCESS Ancillary Service Price APIs (Issue #3)

Post-WEM reform, five FCESS products are co-optimised in the 5-min dispatch. Each product has its own CSV file series.

### 2.1 Products

| Product Code | Description | Type |
|---|---|---|
| `REGULATION_RAISE` | Frequency regulation raise (AGC) | Continuous |
| `REGULATION_LOWER` | Frequency regulation lower (AGC) | Continuous |
| `CONTINGENCY_RESERVE_RAISE` | Contingency reserve raise (trip) | Contingency |
| `CONTINGENCY_RESERVE_LOWER` | Contingency reserve lower (trip) | Contingency |
| `ROCOF_CONTROL_SERVICE` | Rate-of-Change-of-Frequency control | Contingency |

### 2.2 Clearing Price Endpoint

| Field | Value |
|---|---|
| **Endpoint pattern** | `GET https://data.wa.aemo.com.au/public/public-data/dataFiles/fcess-prices/{product-slug}/FCESSPrice_{PRODUCT}_{YYYYMMDD}.csv` |
| **Product slug** | lowercase, hyphens (e.g. `regulation-raise`, `rocof-control-service`) |
| **Frequency** | One file per product per trading day |
| **Format** | CSV (comma-separated, UTF-8) |

**Key fields:**

| CSV Column | Type | Units | Description |
|---|---|---|---|
| `TradingDate` | date | AWST | Trading date |
| `TradingInterval` | int | — | 1–288 (5-min intervals) |
| `IntervalStart` | datetime | AWST | 5-min interval start |
| `ClearingPrice` | float | AUD/MW/h | Clearing price for the product |
| `AvailabilityPrice` | float | AUD/MW/h | Availability price (capacity payment) |
| `EnabledVolume` | float | MW | Volume enabled in dispatch |
| `RequiredVolume` | float | MW | Required volume for the product |

**Notes:**
- Settlement interval is aligned with energy (same 5-min grid)
- Clearing price applies to enabled volume; availability price to total availability offer
- FCESS prices are independent per product (no cross-product netting in WEM)
- Price floors/caps per product are specified in the WEM Rules (Market Rules Part 7)

### 2.3 FCESS Availability Submission

| Field | Value |
|---|---|
| **Endpoint pattern** | `GET https://data.wa.aemo.com.au/public/public-data/dataFiles/fcess-availability/{product-slug}/FCESSAvailability_{PRODUCT}_{YYYYMMDD}.csv` |
| **Purpose** | Participant availability offers for FCESS products |

---

## 3. Reserve Capacity Mechanism APIs (Issue #4)

### 3.1 Capacity Credit Prices

| Field | Value |
|---|---|
| **Endpoint pattern** | `GET https://data.wa.aemo.com.au/public/public-data/dataFiles/capacity-credit-prices/CapacityCreditPrices_{YYYY}.csv` |
| **Frequency** | Annual (one file per capacity year) |
| **Format** | CSV |

**Key fields:**

| CSV Column | Type | Units | Description |
|---|---|---|---|
| `CapacityYear` | int | — | Capacity year (WEM year runs Oct–Sep) |
| `CapacityPrice` | float | AUD/MW/year | Administered/cleared capacity price |
| `ReserveCapacityTarget` | float | MW | RCM target (total system) |
| `TotalCreditsIssued` | float | MW | Total capacity credits issued |

### 3.2 Capacity Credit Assignments

| Field | Value |
|---|---|
| **Endpoint pattern** | `GET https://data.wa.aemo.com.au/public/public-data/dataFiles/capacity-credits/CapacityCredits_{YYYY}.csv` |
| **Frequency** | Annual |

**Key fields:**

| CSV Column | Type | Units | Description |
|---|---|---|---|
| `ParticipantName` | str | — | Market participant name |
| `FacilityName` | str | — | Registered facility |
| `CreditsIssuedMW` | float | MW | Capacity credits issued |
| `EligibleCapacityMW` | float | MW | Certified reserve capacity |
| `DSP` | bool | — | Demand Side Programme flag |

### 3.3 Reserve Capacity Obligations

| Field | Value |
|---|---|
| **Endpoint pattern** | `GET https://data.wa.aemo.com.au/public/public-data/dataFiles/reserve-capacity-obligations/RCO_{YYYY}.csv` |
| **Frequency** | Annual |
| **Purpose** | Per-retailer RCM obligations (MW) |

---

## 4. Pagination & Rate Limits

| Property | Detail |
|---|---|
| **Pagination** | None — each file is a complete day/year |
| **Rate limits** | Not formally published; empirically ~1–2 req/sec is safe |
| **Auth** | None required — all public endpoints |
| **CORS** | Files served from S3-backed CDN; CORS headers present |
| **Retry** | HTTP 404 = data not yet published; HTTP 429 = throttled (rare) |
| **Max lookback** | Wholesale price: from ~2006; post-reform: from 2023-10-01 |

---

## 5. Implementation References

These endpoints are already partially implemented in the pipeline:

| File | Coverage |
|---|---|
| `app/pipeline/aemo_client.py` | `AsyncAEMOClient` — httpx-based async downloader with retry |
| `app/pipeline/wholesale_price_connector.py` | Energy MCP + FCESS fetch (5-min post-reform) |
| `app/pipeline/fcess_connector.py` | FCESS product prices |

---

## 6. Sample Data Fixtures

See `tests/fixtures/` for sample CSVs used in unit tests:

| Fixture | Contents |
|---|---|
| `tests/fixtures/interval_data/` | Sample BalancingSummary and FCESS price CSVs |
| `tests/fixtures/bills/` | Sample retailer bill data |

Sample fixture data is synthetic (generated to match schema) — not sourced from live AEMO API due to sandbox network restrictions.
