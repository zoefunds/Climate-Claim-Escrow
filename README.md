# Climate Claim Escrow — Greenwash Bond

A standalone GenLayer Intelligent Contract primitive that makes bounded
environmental claims financially accountable. It is deliberately designed to
avoid fake precision: the contract never estimates carbon tonnes or creates a
synthetic impact score. It adjudicates only `SUPPORTED`,
`PARTIALLY_SUPPORTED`, `NOT_SUPPORTED`, or `EVIDENCE_CONFLICT`.

## Lifecycle

1. A claimant funds `create_claim` with GEN.
2. Claimants, challengers, and neutral parties submit reports, registries,
   maps, field photos, and source URLs (capped per claim and per submitter).
3. After a deadline and audit window, validators independently render/fetch
   sources and apply a bounded evidence verdict. `request_reaudit` allows a
   fresh round (bounded by `MAX_AUDIT_ROUNDS`) if new evidence lands after a
   verdict, instead of settling on a stale audit.
4. `settle_from_audit` deterministically releases the bond. It is separate
   from the nondeterministic audit.
5. Every non-terminal dead end has an explicit exit: `cancel_claim` (pre-audit
   withdrawal), `claim_unreviewed_timeout` (nobody ever audited),
   `claim_stalled_conflict_timeout` (stuck on `EVIDENCE_CONFLICT`).

The contract holds `claim_bond_wei` as the stated term and
`claim_bond_deposited` as its actual custody ledger. Every payout zeroes and
persists the ledger before calling the sole GEN emission helper
(checks-effects-interactions).

## Evidence and consensus

Web evidence uses rendered text first (`web.render(..., mode="text")`) with an
HTTP fallback, so JavaScript-heavy disclosure sites can be assessed. Photos use
GenLayer vision and store only the consensus-reviewed observation, never raw
image blobs. Every non-deterministic block (text audit, visual relevance) has
a validator that independently re-fetches sources and reruns the task itself
before comparing decision fields to the leader's — never a leader-output-only
schema check, and never a fuzzy tolerance band on a value that moves funds.
`EVIDENCE_CONFLICT` is the sole exception: it is treated as agreement whenever
*both* independent runs land on it, and it is deliberately non-settleable
(only refundable via timeout) so contradictory evidence never gets forced
into a payout.

Errors inside non-deterministic blocks are classified with `[EXPECTED]`,
`[EXTERNAL]`, `[TRANSIENT]`, and `[LLM_ERROR]` prefixes so validators know
whether to require an exact match, tolerate shared network noise, or always
disagree (forcing round rotation instead of freezing bad state).

No method anywhere accepts a caller-supplied clock; every timing check reads
`gl.message_raw["datetime"]`, the consensus-agreed block time.

## Commands

```bash
python3 -m py_compile contracts/greenwash_bond.py
pytest -q test/test_greenwash_bond_static.py
```

Deploy [contracts/greenwash_bond.py](contracts/greenwash_bond.py) with no
constructor arguments. Payable writes must supply native GEN as `value` in
wei; validate `value_credited: true` in the transaction receipt before relying
on escrow state.

## Project isolation

This folder is independent from `promise-to-proof-registry`: it has a separate
contract class, storage namespace, source tree, and deployment target.

## References

- [GenLayer Skills](https://skills.genlayer.com/)
- [Web Access](https://docs.genlayer.com/developers/intelligent-contracts/features/web-access)
- [Image Processing](https://docs.genlayer.com/developers/intelligent-contracts/features/image-processing)
- [Value Transfers](https://docs.genlayer.com/developers/intelligent-contracts/features/value-transfers)
- [Testing Intelligent Contracts](https://docs.genlayer.com/developers/intelligent-contracts/testing)
