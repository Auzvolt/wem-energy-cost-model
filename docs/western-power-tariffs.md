# Western Power Network Tariff Reference

> **Last updated:** March 2026 | **Applicable price list:** 2025/26 (ERA-approved 16 May 2025)

## 1. Regulatory Framework

| Item | Detail |
|------|--------|
| **Network operator** | Western Power (ATCO Gas Australia distributes gas; Western Power is the electricity network operator) |
| **Regulatory period** | Access Arrangement 6 (AA6) |
| **Approved by** | Economic Regulation Authority (ERA) of Western Australia |
| **Tariff Structure Statement** | Approved by ERA on 31 March 2023 |
| **2025/26 Price List** | ERA-approved 16 May 2025 |
| **Price list source** | [ERA approved 2025/26 price list](https://www.erawa.com.au/sites/default/files/24789/era-approved-2025-26-price-list-for-the-western-power-network.pdf) |
| **Western Power network page** | [Network Access Prices](https://www.westernpower.com.au/about/what-we-do/regulation/network-access-prices) |

Tariffs are charged to **retailers and generators** with contractual relationships with Western Power. End consumers pay network charges embedded in their retail tariffs.

---

## 2. Key Business Tariff Codes

| Tariff | Type | Status | Notes |
|--------|------|--------|-------|
| **RT1** | Residential flat rate | Open | Anytime energy rate |
| **RT2** | Small business TOU | Open | On-peak / off-peak energy rates |
| **RT5** | Medium business demand | Open | Demand charge (kW or kVA) + energy + rolling 12-month max demand |
| **RT7** | Large business HV demand | Open | High voltage, CMD-based, ENUC for excess demand |
| **RT8** | Large business LV demand | Open | Low voltage equivalent of RT7 |
| **RT10** | Transmission-connected | Open | For large loads connected at transmission level |
| **RT13** | HV Storage (BESS) | Open (new from Jul 2023) | High voltage battery storage; introduced in AA5 |
| **RT14** | LV Storage (BESS) | Open (new from Jul 2023) | Low voltage battery storage; introduced in AA5 |

> **Note:** Some tariffs were closed to new nominations:
> - Marked `^`: Closed from 1 July 2019
> - Marked `*`: Closed from 1 July 2023  
> - Marked `**`: New from 1 July 2023 (AA5/AA6)
>
> Verify availability for new connections against the current Price List.

---

## 3. Tariff Component Structure

A typical business network tariff has the following bill components:

| Component | Unit | Applicability |
|-----------|------|--------------|
| **Fixed / Administration charge** | $/day or $/year | All tariffs |
| **Demand charge** | $/kW or $/kVA per month | RT5, RT7, RT8, RT10, RT13, RT14 |
| **Peak energy charge** | c/kWh | TOU tariffs (RT2, RT5 TOU variants) |
| **Off-peak energy charge** | c/kWh | TOU tariffs |
| **Anytime energy charge** | c/kWh | Non-TOU tariffs (RT1, RT7 energy component) |
| **Metering charge** | $/day | Applicable tariffs with interval metering |
| **ENUC (Excess Network Usage Charge)** | $/kW excess | RT7, RT8, RT10 where CMD is nominated |

### 3.1 Contracted Maximum Demand (CMD)

- Customers on demand tariffs (RT5, RT7, RT8, RT10) **nominate** a CMD for their connection point
- Some tariffs use the **rolling 12-month maximum half-hourly demand** for billing
- If the metered half-hourly demand exceeds CMD, **ENUC** applies:
  - ENUC is calculated by multiplying excess demand (kW) by the ENUC rate
  - The exceedance is **retained in billing for a full 12 months** (strong incentive to avoid demand spikes)
  - Customers may apply for a reduced CMD if permanent load reduction measures are in place
- CMD can be varied via a **Capacity (Swap) Allocation** under the Business Exit Service

### 3.2 BESS Tariffs (RT13 / RT14)

New storage tariffs introduced in AA5 (from 1 July 2023) specifically for battery energy storage systems:
- RT13: High Voltage connection
- RT14: Low Voltage connection
- These tariffs reflect the bidirectional nature of BESS (both importing and exporting energy)
- Developers should obtain current rates from the 2025/26 Price List PDF

---

## 4. Time-of-Use Period Definitions

> **⚠️ Important:** Exact TOU windows are defined in **Table 8.1** of the ERA-approved Price List PDF.  
> The values below are indicative based on standard WA practice; always verify against the current Price List.

All times in **AWST (Australian Western Standard Time, UTC+8)**.  
Western Australia does **not** observe daylight saving time.

| Period | Days | Hours (AWST) |
|--------|------|-------------|
| **On-Peak** | Monday – Friday (excl. public holidays) | 07:00 – 23:00 |
| **Off-Peak** | Monday – Friday (excl. public holidays) | 23:00 – 07:00 |
| **Off-Peak** | Saturday, Sunday, WA public holidays | All day |

### 4.1 Implementation Notes

- Use the **AEST/AWST distinction** carefully — WA is always UTC+8 with no DST
- Public holidays are the gazetted Western Australian public holidays
- Some tariffs define additional **Shoulder** periods — check the Price List
- For load profiling: 30-minute interval data (half-hourly) maps directly to the Western Power billing intervals

---

## 5. Loss Factor Framework

### 5.1 Overview

Western Power calculates two types of loss factors applied to electricity transmitted through the network:

| Type | Abbreviation | Applies to | Source |
|------|-------------|-----------|--------|
| Transmission Loss Factor | TLF | Per connection point / bus | Western Power → published by AEMO |
| Distribution Loss Factor (average) | DLF | Per reference service category | Western Power → published by AEMO |
| Distribution Loss Factor (individual) | DLF | Per specific connection point | Available on request (at retailer's cost) |

### 5.2 Calculation and Publication

- Annual revision: apply from **1 July** each financial year (July–June)
- AEMO publishes within **2 business days** of receiving from Western Power
- TLFs calculated based on half-hour data for the whole system over the whole financial year
- Movements >0.025 from prior year require an explanation in the annual Loss Factor Report
- **Reference node:** Perth Southern Terminal (post-reform)

### 5.3 Applying Loss Factors

Loss-adjusted energy quantity:
```
adjusted_kWh = metered_kWh × TLF × DLF
```

Impact on pricing:
- Higher demand at a node → higher TLF (more losses) → higher effective cost
- Higher generation at a node → lower TLF (fewer losses)
- Network reconfigurations can shift loss factors significantly

### 5.4 Data Sources

| Resource | URL |
|---------|-----|
| Annual Loss Factor Reports | https://www.aemo.com.au/energy-systems/electricity/wholesale-electricity-market-wem/data-wem/loss-factors |
| 2023/24 Loss Factor Report (PDF) | https://www.aemo.com.au/-/media/files/electricity/wem/data/loss-factors/2024/2023-24-loss-factor-report.pdf |
| Loss Factor Procedure | Published on Western Power website |

---

## 6. Tariff Calculation Pseudocode

The following pseudocode models a business network tariff bill (e.g., RT7 or RT8):

```python
for each month m:
    days = days_in_month(m)
    
    # Fixed charges
    fixed_charge = days * daily_admin_rate  # $/day
    metering_charge = days * daily_meter_rate  # $/day
    
    # Demand charge — peak half-hourly demand during on-peak windows
    peak_demand_kw = max(
        half_hourly_kw[ti]
        for ti in month_intervals(m)
        if is_on_peak(ti)
    )
    demand_charge = peak_demand_kw * demand_rate_per_kw  # $/kW/month
    
    # Excess Network Usage Charge (if demand > CMD)
    if peak_demand_kw > contracted_maximum_demand_kw:
        excess_kw = peak_demand_kw - contracted_maximum_demand_kw
        # ENUC retained in next 12 monthly bills
        monthly_enuc_amortised = excess_kw * enuc_rate / 12
    else:
        monthly_enuc_amortised = 0
    
    # Energy charges (with loss factor adjustment)
    kwh_on_peak = sum(
        kwh_import[ti] * tlf * dlf
        for ti in month_intervals(m)
        if is_on_peak(ti)
    )
    kwh_off_peak = sum(
        kwh_import[ti] * tlf * dlf
        for ti in month_intervals(m)
        if not is_on_peak(ti)
    )
    energy_charge = (
        kwh_on_peak * on_peak_rate_cents_per_kwh / 100
        + kwh_off_peak * off_peak_rate_cents_per_kwh / 100
    )
    
    monthly_bill = (
        fixed_charge
        + metering_charge
        + demand_charge
        + monthly_enuc_amortised
        + energy_charge
    )
```

---

## 7. Implementation Notes for Developers

1. **Tariff rates** (c/kWh, $/kW) require parsing the **ERA-approved Price List PDF**. Rates change annually. Store as configuration in `tariff_schedules` table with `effective_from` / `effective_to` date fields.

2. **RT13/RT14** (storage tariffs) are the relevant tariffs for BESS modelling. Obtain current rates from the 2025/26 Price List.

3. **TOU windows** are best stored as a list of `{day_type, start_time, end_time, period_type}` records in the `tariff_config` JSON field, parameterized by tariff code.

4. **Loss factors** should be stored in the `loss_factors` table with `financial_year`, `connection_point_id`, and separate `tlf`/`dlf` columns. Look up by year and connection point at billing time.

5. **ENUC** is complex to implement correctly because the exceedance is retained for 12 months. Maintain a rolling window of maximum demand per month for each site.

6. **Western Australia has no DST** — all timestamps should be stored as UTC and converted to AWST (UTC+8) for TOU calculations. Use `Australia/Perth` timezone identifier.

7. The **Price List PDF** must be parsed manually or by document extraction. Consider maintaining a `tariff_schedules` YAML or JSON seed file that is updated annually.
