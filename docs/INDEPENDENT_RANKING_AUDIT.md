# Archived C3 ranking and evidence reconciliation

The main C3 results were solved before this audit. This work derives a **new,
falsifiable and narrow** check of all 15 paired cases against both published
CSV tables, without fitting or re-solving any model.

Run:

```bash
python scripts/audit_ranking_evidence.py --output outputs/ranking_evidence_audit.json
python -m pytest -q tests/test_ranking_evidence.py
```

The audit independently reconstructs the solved cost delta, relative cost
delta, cheapest technology and runner-up for every temperature/load-profile
condition from the **stored per-solver objectives and KPI values**. It
rejects any missing/duplicate case, changed result, unsupported ranking or
non-optimal stored status. It publishes an additive *fixed-output surcharge*
margin: the difference between the cheapest stored annualised objective and
the second cheapest in the same comparison. This is the extra amount that
would tie the archived totals **if no scenario is re-optimised**.

**It is not** a CAPEX break-even, tariff sensitivity, uncertainty interval,
or proof that an alternative becomes economically optimal after a real
parameter change. Re-optimisation is necessary to answer those questions.
The original model also charges packed-bed blower energy but has no matched
parasitic-cost model for PCM or molten salt, and material/input cost citations
have unequal evidence depth. The original 300 °C and 400 °C cases happen to
have repeated numerical results; these must not be counted as six independent
physical replications. This check confirms saved-solver arithmetic and does
not independently validate thermal properties, measured plant performance,
or the source literature.

The script is deterministic, uses the Python standard library, and performs
no network access. The test suite includes altered objective, delta and
ranking negative controls.
