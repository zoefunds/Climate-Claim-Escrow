# Testing Greenwash Bond

Run the static suite first:

```bash
pytest -q test/test_greenwash_bond_static.py
genvm-lint check contracts/greenwash_bond.py --json
```

For a real test, create a small funded claim with an official, stable source;
submit a document URL; wait for `audit_at`; call `mark_ready_for_audit`,
`audit_claim`, and—only for a terminal verdict—`settle_from_audit`. Confirm
that the settlement read returns `claim_bond_deposited: "0"` and inspect the
triggered transfer receipt.

Test `EVIDENCE_CONFLICT` independently: it must not be settleable. Also test a
pre-audit amendment and a challenger bond to ensure the contract does not treat
corrected claims as original, immutable statements.
