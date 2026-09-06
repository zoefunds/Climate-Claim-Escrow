# Testing Greenwash Bond

## Static suite

No network required; checks the source for required guards/patterns.

```bash
pytest -q tests/static/test_greenwash_bond_static.py
genvm-lint check contracts/greenwash_bond.py --json
```

## Live integration suite

`tests/integration/test_live_lifecycle.py` drives every non-admin write
method against a real deployed contract on StudioNet: real GEN escrow, real
accounts, a real fetched photograph for visual evidence, and real web/LLM
consensus rounds. It does not exercise `set_paused`, `transfer_ownership`, or
`update_domain_rules` -- those are owner-only and require the deployer's key.

The `genlayer` CLI's `write` command cannot attach GEN value to a
transaction (`payable` calls are unreachable through it in any released
version, checked through `0.40.0-rc2`), so `create_claim` and
`open_challenge` can only be driven through `gltest`
(`get_contract_factory(...).build_contract(address, account).method(...).transact(value=...)`),
not the CLI.

```bash
cd climate-claim-escrow
python3 -m pytest tests/integration/test_live_lifecycle.py -v -s -m integration
```

Config: [`gltest.config.yaml`](../gltest.config.yaml) points at StudioNet
(gasless -- no funding needed). Test accounts are freshly generated,
encrypted keystores under `tests/.keys/` (gitignored -- never committed,
since the decryption password lives in the test file itself).

Each test creates its own claim and is independent, but they share three
accounts, so run them sequentially rather than in parallel to avoid nonce
collisions:

- `test_full_audit_and_settlement_lifecycle_live` -- create → submit_evidence
  → submit_visual_evidence → mark_ready_for_audit → audit_claim →
  settle_from_audit (only when the verdict is terminal).
- `test_amend_challenge_and_reaudit_live` -- amend_claim → submit_evidence →
  supersede_evidence → open_challenge → mark_ready_for_audit → audit_claim →
  submit_evidence → request_reaudit.
- `test_cancel_claim_live` -- create → cancel_claim on an untouched OPEN
  claim.
- `test_claim_unreviewed_timeout_live` -- create with a short recovery
  window, genuinely wait it out, claim_unreviewed_timeout.
- `test_conflict_and_stalled_conflict_timeout_live` -- submits genuinely
  contradictory evidence and only exercises `claim_stalled_conflict_timeout`
  if the audit actually lands on `EVIDENCE_CONFLICT` (LLM adjudication is
  nondeterministic, so this documents rather than forces the outcome).

`EVIDENCE_CONFLICT` must never be settleable via `settle_from_audit` --
only refundable via `claim_stalled_conflict_timeout` after the recovery
window. The suite above exercises both the conflict path and a pre-audit
amendment plus a live challenger bond, so corrected claims are never treated
as original, immutable statements.
