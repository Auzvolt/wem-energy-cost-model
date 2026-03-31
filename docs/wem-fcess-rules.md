# WEM FCESS Rules and Co-Optimisation Reference

> **Last updated:** March 2026 | **Applies from:** WEM Reform commencement October 2023

## 1. Overview

The Western Australian Wholesale Electricity Market (WEM) underwent major reform commencing **1 October 2023**. The reformed market operates across the South West Interconnected System (SWIS) and includes a **co-optimised** real-time dispatch mechanism covering energy and five Frequency Co-optimised Essential System Services (FCESS).

**Regulatory authority:** AEMO WA (dispatch operator)  
**Economic regulator:** Economic Regulation Authority (ERA) of Western Australia  
**Reference node:** Perth Southern Terminal

---

## 2. The Five FCESS Products

| # | Product Name | Code | Unit | Time Frame | Description |
|---|-------------|------|------|------------|-------------|
| 1 | **Regulation Raise** | `reg_raise` | MW | Continuous | AGC-based upward adjustment of facility MW output to maintain SWIS frequency at 50 Hz |
| 2 | **Regulation Lower** | `reg_lower` | MW | Continuous | AGC-based downward adjustment of facility MW output to maintain SWIS frequency at 50 Hz |
| 3 | **Contingency Reserve Raise** | `cont_raise` | MW | Fast 6s / Slow 60s / Delayed 5min | Reserve to respond to sudden loss of generation; facilities must respond within specified time frames |
| 4 | **Contingency Reserve Lower** | `cont_lower` | MW | Fast 6s / Slow 60s / Delayed 5min | Reserve to respond to sudden excess generation or loss of load |
| 5 | **RoCoF Control Service** | `rocof` | MW·s | Continuous | Synchronous inertia to slow the Rate of Change of Frequency during a contingency event |

### 2.1 Notes on RoCoF Control Service

- Measured in **MW·s** (megawatt-seconds of kinetic energy from rotating mass)
- Currently restricted to **synchronous inertia providers only** (BESS cannot currently provide RCS unless their inverter provides synthetic inertia via a certified method)
- ERA set the offer price ceiling at **$0/MW·s/hr** from 1 March 2024, based on the view that the Short Run Marginal Cost of inertia is zero once a facility is committed for energy or other FCESS
- For modelling purposes: treat RoCoF MCP as **$0** for all periods from March 2024 onwards

### 2.2 Offer Price Ceilings

- Set by the ERA for each of the five FCESS markets
- During initial 5-month period (Oct 2023 – Feb 2024): single ceiling of **$300/MW·s/hr** applied to all FCESS (per WEM Rules clause 1.60.5)
- From March 2024: individual ceilings per product; RoCoF ceiling = $0
- ERA reviews ceilings every 3 years; annual indexation possible between reviews

**Source:** [ERA FCESS Offer Price Ceilings](https://www.erawa.com.au/electricity/wholesale-electricity-market/price-setting/market-price-limits/frequency-co-optimised-essential-system-services-offer-price-ceiling)

---

## 3. Dispatch Intervals and Settlement

### 3.1 Time Granularity

| Concept | Duration | Purpose |
|---------|----------|---------|
| **Dispatch Interval (DI)** | 5 minutes | SCED co-optimisation run; MCP determined for energy + all 5 FCESS |
| **Trading Interval (TI)** | 30 minutes | Energy settlement interval; 6 × DI averaged for Reference Trading Price |
| **Trading Day** | 24 hours | Settlement reporting unit |
| **Trading Week** | 7 days (Mon–Sun) | Settlement payment cycle |

### 3.2 Energy vs FCESS Settlement

- **Energy:** Settled at the **Reference Trading Price** = time-weighted average of six 5-min MCPs within a 30-min Trading Interval
- **FCESS:** Settled at the **5-minute MCP** for each product in each Dispatch Interval — NOT averaged to 30 minutes
- This difference is critical for modelling BESS revenue stacking: FCESS revenue is always calculated at 5-min resolution

### 3.3 Settlement Timeline

- Settlement runs ~**4 weeks after the end of the relevant Trading Week**
- Settlement adjustments possible up to **12 months** after the relevant Trading Week
- Weekly settlement cycle (Market Participants net settlement account)
- Prudential requirements apply to Market Participants

---

## 4. Co-Optimisation Mechanics (SCED)

### 4.1 WEM Dispatch Engine (WEM-DE)

AEMO operates the **Security-Constrained Economic Dispatch (SCED)** engine which:

1. Co-optimises energy and all 5 FCESS products simultaneously every 5 minutes
2. Considers all facility bids/offers, network transmission constraints, and grid security requirements
3. Solves for the least-cost dispatch that meets demand **and** all FCESS requirements simultaneously
4. Publishes Market Clearing Prices (MCPs) for energy and each FCESS product per DI

### 4.2 Key Constraints

| Constraint | Detail |
|-----------|--------|
| Self-commit market | WEM-DE cannot force facilities online (except fast-start facilities). Facilities self-schedule and submit offers into the RTM. |
| FCESS accreditation | Facilities must be accredited for each FCESS product before submitting offers. Accreditation parameters set the MW capability per product. |
| Uplift payments | A facility constrained on for FCESS below its energy offer price may receive Uplift Payments as compensation. |
| SESSM | Supplementary ESS Mechanism — AEMO or ERA can procure FCESS via longer-term contracts when RTM supply is insufficient |
| NCESS | Non-Co-optimised ESS (replaces older Network Control Services) — procured separately by network operators |

### 4.3 Price Formation

- **Energy MCP floor:** -$1,000/MWh
- **Energy MCP cap:** $1,000/MWh (dynamically adjusted ±$100/MWh by AEMO based on market conditions as at Dec 2025)
- Prices are calculated at the **Perth Southern Terminal** reference node
- Facility prices adjust for transmission loss factors (TLF) relative to the reference node

### 4.4 Pre-Dispatch and Week-Ahead

| Product | Description |
|---------|-------------|
| Pre-dispatch | ~30-min ahead look using current facility availability and forecasts; provides indicative prices |
| Week-ahead dispatch | Published to give facilities a 7-day forward view |

---

## 5. Reserve Capacity Mechanism (RCM)

### 5.1 Structure

- **Capacity Year:** October–September (e.g., 2024-25 = 1 Oct 2024 – 30 Sep 2025)
- AEMO procures capacity **2 years in advance** (e.g., 2026-27 capacity procured in 2024)
- Facilities receive **Facility Capacity Credits (FCC)** based on their ability to deliver during the system peak

### 5.2 BESS Obligation

- BESS must meet the **6-hour Electric Storage Resources Obligation Interval (ESROI)**
- Batteries shorter than 6 hours receive proportionally reduced FCC
- Degradation and round-trip efficiency losses further reduce credits
- Monthly capacity payments based on FCCs × Benchmark Reserve Capacity Price (BRCP)

### 5.3 Cost Recovery

| Cost type | Recovery mechanism |
|-----------|-------------------|
| Contingency Reserve Raise | Causer-pays (based on extent a participant created the contingency need) |
| Regulation Raise/Lower | Proportional to energy volumes |
| NCESS (AEMO-procured) | Proportional to energy volumes |
| NCESS (Network-procured) | Not recovered via market settlement |

---

## 6. BESS Participation in FCESS

### 6.1 Accreditation Requirements

| FCESS Product | BESS Eligibility | Key Requirements |
|--------------|-----------------|-----------------|
| Regulation Raise | ✅ Yes | AGC operation; SCADA/communications; Performance Requirements |
| Regulation Lower | ✅ Yes | AGC operation; SCADA/communications; Performance Requirements |
| Contingency Raise | ✅ Yes | High-resolution time-synchronised measurements; AGC 'Assist' mode |
| Contingency Lower | ✅ Yes | High-resolution time-synchronised measurements; AGC 'Assist' mode |
| RoCoF Control Service | ❌ No (currently) | Requires synchronous inertia — BESS excluded unless synthetic inertia method certified |

### 6.2 Real-World Examples (as at Q3 2024)

- **Kwinana BESS 1:** Accredited for Contingency and Regulation FCESS in July 2024; earns majority of RTM revenue from FCESS
- **Kwinana BESS 2** (225 MW / 900 MWh): Commissioned late 2024
- **Collie BESS 1** (219 MW / 877 MWh): Commissioned late 2024
- Over 1.3 GW of new BESS under construction as at Q3 2024; ~1.5 GW expected by end 2025

---

## 7. AEMO WA Data Sources

### 7.1 Public Data Portal (no authentication required)

| Data type | URL pattern | Format | Granularity |
|-----------|-------------|--------|-------------|
| Balancing/energy prices | `https://data.wa.aemo.com.au/public/public-data/dataFiles/balancing-summary/` | CSV | 5-min DI |
| FCESS dispatch prices | `https://data.wa.aemo.com.au/public/public-data/dataFiles/dispatch-interval/` | CSV | 5-min DI |
| Capacity credits | `https://data.wa.aemo.com.au/public/public-data/dataFiles/capacity-credits/` | CSV | Annual/monthly |
| Facility SCADA | `https://data.wa.aemo.com.au/public/public-data/dataFiles/facility-scada/` | CSV | 5-min |

> **Note:** Exact paths and file naming conventions (`{category}_{YYYYMMDD}.csv`) should be verified by browsing the public data directory. The above are indicative based on AEMO's standard organization.

### 7.2 APIM REST API (participant registration required)

| API | Endpoint | Auth |
|-----|---------|------|
| WEM Dispatch Case v2 | `https://dev.aemo.com.au/WEM-Dispatch-Case-v2-API` | APIM subscription key + DigiCert certificate |
| Rate limits | 50 calls/min, 250 calls/5min | 10 MB max payload |

### 7.3 Other Resources

- [AEMO WEM Market Data](https://aemo.com.au/en/energy-systems/electricity/wholesale-electricity-market-wem/data-wem/market-data-wa)
- [FCESS Summary — AEMO](https://aemo.com.au/en/energy-systems/electricity/wholesale-electricity-market-wem/system-operations/essential-system-services/summary-of-frequency-co-optimised-essential-system-services)
- [APIM Endpoints Summary PDF](https://www.aemo.com.au/-/media/files/electricity/wem/participant_information/guides-and-useful-information/summary-of-wem-api-endpoints.pdf)
- [WEM Market Design Summary](https://www.aemo.com.au/-/media/files/initiatives/wem-reform-program/wem-reform-market-design-summary.pdf)
- [Loss Factors](https://www.aemo.com.au/energy-systems/electricity/wholesale-electricity-market-wem/data-wem/loss-factors)

---

## 8. Implementation Notes

1. **Post-reform data** (Oct 2023+) uses 5-min DIs — this is the only period with FCESS pricing
2. Database should store **all 6 products** (energy + 5 FCESS) with separate price rows per DI
3. RoCoF revenue is effectively **$0 from March 2024** — handle as zero-fill or special product code
4. FCESS settlement at 5-min resolution; energy settlement at 30-min (averaged Reference Trading Price)
5. Contingency Raise has **Fast/Slow/Delayed sub-products** — check whether AEMO publishes separate prices for each or a blended price
6. For BESS optimisation: co-optimisation means the model must simultaneously optimise energy + Reg + Contingency bids, subject to state-of-charge constraints
