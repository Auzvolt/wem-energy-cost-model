# Tariff Engine Bill Validation Results

**Date:** 2025-07-31  
**Fixtures:** Fully synthetic/anonymised — no real NMI numbers, customer names, or addresses

---

## Summary

| Tariff | Calculated Total (exc GST) | Billed Total (exc GST) | Difference | Result |
|--------|---------------------------|------------------------|------------|--------|
| RT2    | $1,370.48                 | $1,370.47              | 0.001%     | ✅ PASS |
| RT5    | $6,090.92                 | $6,088.99              | 0.032%     | ✅ PASS |

Both validation cases pass the ±1% tolerance threshold.

---

## RT2 — Small Business TOU Tariff

**Fixture:** `tests/fixtures/bills/RT2_synthetic_bill_202507.json`  
**Interval data:** `tests/fixtures/interval_data/RT2_synthetic_202507.csv`  
**Validation period:** 2025-07-01 to 2025-07-31 (31 days)

| Component | Calculated | Billed | Difference |
|-----------|-----------|--------|------------|
| Peak kWh  | 2,450.0   | 2,450.0 | 0.0% |
| Off-peak kWh | 1,850.0 | 1,850.0 | 0.0% |
| Peak energy charge | $968.00 | $967.99 | 0.001% |
| Off-peak energy charge | $337.26 | $337.25 | 0.003% |
| Daily supply charge | $57.48 | $57.48 | 0.000% |
| Metering charge | $7.75 | $7.75 | 0.000% |
| **Total exc GST** | **$1,370.48** | **$1,370.47** | **0.001%** |

**Notes:**
- Minor rounding difference ($0.01) attributable to floating-point precision in rate multiplication.
- Engine correctly identifies TOU windows (07:00–23:00 weekdays = peak; all other = off-peak).

---

## RT5 — Medium Business Demand TOU Tariff

**Fixture:** `tests/fixtures/bills/RT5_synthetic_bill_202507.json`  
**Interval data:** `tests/fixtures/interval_data/RT5_synthetic_202507.csv`  
**Validation period:** 2025-07-01 to 2025-07-31 (31 days)

| Component | Calculated | Billed | Difference |
|-----------|-----------|--------|------------|
| Peak kWh | 18,500.0 | 18,500.0 | 0.0% |
| Off-peak kWh | 12,200.0 | 12,200.0 | 0.0% |
| Max peak demand (kW) | 58.1 | 58.0 | 0.2% |
| Peak energy charge | $3,779.55 | $3,779.55 | 0.000% |
| Off-peak energy charge | $1,234.64 | $1,234.64 | 0.000% |
| Demand charge | $958.93 | $957.00 | 0.201% |
| Daily supply charge | $106.95 | $106.95 | 0.000% |
| Metering charge | $10.85 | $10.85 | 0.000% |
| **Total exc GST** | **$6,090.92** | **$6,088.99** | **0.032%** |

**Notes:**
- Demand charge difference (0.2%) arises because the synthetic interval data produces a measured
  peak demand of 58.1 kW, whereas the fixture assumes a rounded 58.0 kW for the billed demand.
  On real bills, Western Power rounds to the nearest whole kW for billing.
- To improve realism, the engine should round maximum demand to the nearest kW before applying the
  demand charge. This is tracked as a known limitation for issue #45.

---

## Known Limitations

1. **Demand rounding:** The engine uses exact interval kW values for demand billing; real bills
   typically round to nearest 0.5 or 1 kW. Difference is within tolerance (<1%) but may need
   tariff-specific rounding rules.
2. **Holiday treatment:** The engine does not currently exclude public holidays from peak windows.
   Western Power tariffs treat public holidays as off-peak equivalent. This is not tested in these
   synthetic fixtures but should be addressed for production accuracy.
3. **ENUC billing (RT7):** Not validated in this fixture set. RT7 CMD-based billing with excess
   use charges is more complex and requires a separate fixture with a CMD exceedance scenario.
