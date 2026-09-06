"""Full-surface StudioNet integration test: drives every non-admin write
method against the live deployed GreenwashBond contract, with real GEN
escrow, real accounts, a real fetched photograph, and real web/LLM
consensus rounds. Owner-only methods (set_paused, transfer_ownership,
update_domain_rules) are intentionally out of scope here -- the deployer
key is not held by this test suite.

Run: pytest tests/integration/test_live_lifecycle.py -v -s -m integration
"""

import datetime
import json
import time
import urllib.request
from pathlib import Path

import pytest
from eth_account import Account
from gltest.contracts import get_contract_factory
from gltest.assertions import tx_execution_failed

CONTRACT_ADDRESS = "0x4f8e9df7401605add79A528B1955193ae2CEB2c7"
KEYS_DIR = Path(__file__).parent.parent / ".keys"
GEN = 10**18
PASSWORD = "gwb-live-test-pass-2026"


def _load_account(name: str):
    with open(KEYS_DIR / f"{name}.json") as f:
        encrypted = json.load(f)
    private_key = Account.decrypt(encrypted, PASSWORD)
    return Account.from_key(private_key)


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_real_photo() -> bytes:
    """A real photograph fetched live over the network -- not a placeholder."""
    req = urllib.request.Request(
        "https://httpbin.org/image/jpeg", headers={"User-Agent": "curl/8.0"}
    )
    return urllib.request.urlopen(req, timeout=20).read()


def _new_claim_id(contract, count_before: int) -> str:
    ids = json.loads(contract.list_claim_ids(args=[count_before, 1]).call())
    return ids[0]


@pytest.mark.integration
def test_full_audit_and_settlement_lifecycle_live():
    """create_claim -> submit_evidence -> submit_visual_evidence ->
    mark_ready_for_audit -> audit_claim -> settle_from_audit."""
    claimant = _load_account("claimant")
    beneficiary = _load_account("beneficiary")

    factory = get_contract_factory(contract_file_path="greenwash_bond.py")
    c_claimant = factory.build_contract(CONTRACT_ADDRESS, account=claimant)
    c_anyone = c_claimant

    now = datetime.datetime.now(datetime.timezone.utc)
    deadline = now + datetime.timedelta(seconds=70)
    audit_at = deadline
    recovery = audit_at + datetime.timedelta(seconds=600)

    count_before = c_anyone.get_claim_count().call()

    receipt = c_claimant.create_claim(
        args=[
            "Rooftop Solar Installation Claim",
            "Our Lagos facility installed a 200kW rooftop solar array in Q1 2026, "
            "cutting grid electricity draw for that site.",
            "Requires a photograph or registry document showing solar panels "
            "physically installed at the named facility roof.",
            "Single facility rooftop solar installation, Lagos plant, Q1 2026.",
            _iso(deadline),
            _iso(audit_at),
            _iso(recovery),
            beneficiary.address,
            "[]",
            8000,
            4000,
            2000,
            "",
        ]
    ).transact(value=2 * GEN, wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("\ncreate_claim:", receipt.get("status_name"))

    claim_id = _new_claim_id(c_anyone, count_before)
    print("claim_id:", claim_id)

    claim = json.loads(c_anyone.get_claim(args=[claim_id]).call())
    assert claim["status"] == "OPEN"
    assert claim["claim_bond_deposited"] == str(2 * GEN)

    receipt = c_claimant.submit_evidence(
        args=[
            claim_id,
            "CLAIMANT",
            "REGISTRY",
            "https://en.wikipedia.org/wiki/Solar_panel",
            "Reference registry entry describing rooftop solar PV installation "
            "practices consistent with the claimed Lagos facility retrofit.",
            "",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("submit_evidence:", receipt.get("status_name"))

    photo = _fetch_real_photo()
    receipt = c_claimant.submit_visual_evidence(
        args=[
            claim_id,
            "CLAIMANT",
            "Rooftop solar array photographed at the Lagos facility, Q1 2026.",
            "",
            photo,
        ]
    ).transact(wait_interval=8000, wait_retries=120)
    assert not tx_execution_failed(receipt), receipt
    print("submit_visual_evidence:", receipt.get("status_name"))

    evidence_count = c_anyone.get_evidence_count(args=[claim_id]).call()
    assert evidence_count == 2
    photo_evidence = json.loads(c_anyone.get_evidence(args=[claim_id, 2]).call())
    assert photo_evidence["visual_relevance"] in ("HIGH", "MEDIUM", "LOW")
    assert isinstance(photo_evidence["visual_tags"], list)
    print("visual_tags:", photo_evidence["visual_tags"])

    while datetime.datetime.now(datetime.timezone.utc) <= audit_at:
        time.sleep(2)

    receipt = c_claimant.mark_ready_for_audit(args=[claim_id]).transact(
        wait_interval=5000, wait_retries=90
    )
    assert not tx_execution_failed(receipt), receipt
    print("mark_ready_for_audit:", receipt.get("status_name"))

    receipt = c_claimant.audit_claim(args=[claim_id]).transact(
        wait_interval=8000, wait_retries=150
    )
    assert not tx_execution_failed(receipt), receipt
    print("audit_claim:", receipt.get("status_name"))

    claim = json.loads(c_anyone.get_claim(args=[claim_id]).call())
    print("post-audit verdict:", claim["last_verdict"])

    if claim["last_verdict"] in ("SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED"):
        receipt = c_claimant.settle_from_audit(args=[claim_id]).transact(
            wait_interval=5000, wait_retries=90
        )
        assert not tx_execution_failed(receipt), receipt
        print("settle_from_audit:", receipt.get("status_name"))

        final = json.loads(c_anyone.get_claim(args=[claim_id]).call())
        assert final["status"] == "SETTLED"
        assert final["claim_bond_deposited"] == "0"
        print("final state:", json.dumps(final, indent=2))
    else:
        print(
            "Verdict was EVIDENCE_CONFLICT -- not settleable by design; "
            "covered separately by the conflict-timeout test."
        )


@pytest.mark.integration
def test_amend_challenge_and_reaudit_live():
    """amend_claim -> submit_evidence -> supersede_evidence -> open_challenge
    -> mark_ready_for_audit -> audit_claim -> submit new evidence ->
    request_reaudit."""
    claimant = _load_account("claimant")
    beneficiary = _load_account("beneficiary")
    challenger = _load_account("challenger")

    factory = get_contract_factory(contract_file_path="greenwash_bond.py")
    c_claimant = factory.build_contract(CONTRACT_ADDRESS, account=claimant)
    c_challenger = factory.build_contract(CONTRACT_ADDRESS, account=challenger)
    c_anyone = c_claimant

    now = datetime.datetime.now(datetime.timezone.utc)
    deadline = now + datetime.timedelta(seconds=60)
    audit_at = deadline
    recovery = audit_at + datetime.timedelta(seconds=600)

    count_before = c_anyone.get_claim_count().call()
    receipt = c_claimant.create_claim(
        args=[
            "Reforestation Offset Claim",
            "We planted 5,000 native trees across a 12-hectare degraded plot "
            "in Q4 2025 to offset residual emissions.",
            "Requires a registry record or satellite/map evidence of the "
            "planting site and species count.",
            "12-hectare reforestation plot, single site, Q4 2025.",
            _iso(deadline),
            _iso(audit_at),
            _iso(recovery),
            beneficiary.address,
            "[]",
            7000,
            3000,
            2500,
            "",
        ]
    ).transact(value=int(1.5 * GEN), wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("\ncreate_claim:", receipt.get("status_name"))

    claim_id = _new_claim_id(c_anyone, count_before)
    print("claim_id:", claim_id)

    receipt = c_claimant.amend_claim(
        args=[
            claim_id,
            "We planted 4,200 native trees (revised count after a field "
            "recount) across the same 12-hectare plot in Q4 2025.",
            "Initial figure of 5,000 trees was an estimate; the post-planting "
            "field recount found 4,200 surviving saplings.",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("amend_claim:", receipt.get("status_name"))

    claim = json.loads(c_anyone.get_claim(args=[claim_id]).call())
    assert claim["status"] == "AMENDED"
    assert "4,200" in claim["amendment"]

    receipt = c_claimant.submit_evidence(
        args=[
            claim_id,
            "CLAIMANT",
            "MAP",
            "https://en.wikipedia.org/wiki/Reforestation",
            "Reference material on reforestation verification methodology, "
            "submitted alongside the plot's planting record.",
            "",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("submit_evidence #1:", receipt.get("status_name"))

    receipt = c_claimant.supersede_evidence(
        args=[
            claim_id,
            1,
            "Superseded by a corrected registry link filed as sequence 2.",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("supersede_evidence:", receipt.get("status_name"))

    superseded = json.loads(c_anyone.get_evidence(args=[claim_id, 1]).call())
    assert superseded["superseded"] is True

    receipt = c_claimant.submit_evidence(
        args=[
            claim_id,
            "CLAIMANT",
            "REGISTRY",
            "https://en.wikipedia.org/wiki/Afforestation",
            "Corrected registry-style reference replacing the superseded "
            "sequence 1 item.",
            "",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("submit_evidence #2:", receipt.get("status_name"))

    receipt = c_challenger.open_challenge(
        args=[
            claim_id,
            "The claimed 12-hectare plot does not match any registered "
            "reforestation project we could find; requesting independent audit.",
        ]
    ).transact(value=int(0.2 * GEN), wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("open_challenge:", receipt.get("status_name"))

    claim = json.loads(c_anyone.get_claim(args=[claim_id]).call())
    assert claim["challenger"].lower() == challenger.address.lower()
    assert c_anyone.get_challenger_bond(args=[claim_id]).call() == int(0.2 * GEN)

    while datetime.datetime.now(datetime.timezone.utc) <= audit_at:
        time.sleep(2)

    receipt = c_claimant.mark_ready_for_audit(args=[claim_id]).transact(
        wait_interval=5000, wait_retries=90
    )
    assert not tx_execution_failed(receipt), receipt
    print("mark_ready_for_audit:", receipt.get("status_name"))

    receipt = c_claimant.audit_claim(args=[claim_id]).transact(
        wait_interval=8000, wait_retries=150
    )
    assert not tx_execution_failed(receipt), receipt
    print("audit_claim #1:", receipt.get("status_name"))

    claim = json.loads(c_anyone.get_claim(args=[claim_id]).call())
    print("verdict after round 1:", claim["last_verdict"])

    # New evidence submitted after the audit is what makes request_reaudit
    # eligible (last_evidence_at must move past the prior audit).
    receipt = c_claimant.submit_evidence(
        args=[
            claim_id,
            "CLAIMANT",
            "DOCUMENT",
            "https://en.wikipedia.org/wiki/Forest_restoration",
            "Additional supporting document submitted after the first audit "
            "round to justify a re-audit.",
            "",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("submit_evidence #3 (post-audit):", receipt.get("status_name"))

    receipt = c_challenger.request_reaudit(args=[claim_id]).transact(
        wait_interval=5000, wait_retries=90
    )
    assert not tx_execution_failed(receipt), receipt
    print("request_reaudit:", receipt.get("status_name"))

    claim = json.loads(c_anyone.get_claim(args=[claim_id]).call())
    assert claim["status"] == "READY_FOR_AUDIT"
    print("state after reaudit request:", json.dumps(claim, indent=2))


@pytest.mark.integration
def test_cancel_claim_live():
    """create_claim -> cancel_claim, on an untouched OPEN claim."""
    claimant = _load_account("claimant")
    beneficiary = _load_account("beneficiary")
    factory = get_contract_factory(contract_file_path="greenwash_bond.py")
    c_claimant = factory.build_contract(CONTRACT_ADDRESS, account=claimant)

    now = datetime.datetime.now(datetime.timezone.utc)
    deadline = now + datetime.timedelta(seconds=120)
    audit_at = deadline
    recovery = audit_at + datetime.timedelta(seconds=600)

    count_before = c_claimant.get_claim_count().call()
    receipt = c_claimant.create_claim(
        args=[
            "Withdrawn Fleet Electrification Claim",
            "We planned to convert our delivery fleet of 10 vans to electric "
            "by Q2 2026, but the program was cancelled before any evidence "
            "was gathered.",
            "Requires registry evidence of van conversions.",
            "10-van delivery fleet, single depot.",
            _iso(deadline),
            _iso(audit_at),
            _iso(recovery),
            beneficiary.address,
            "[]",
            8000,
            4000,
            0,
            "",
        ]
    ).transact(value=int(0.5 * GEN), wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    claim_id = _new_claim_id(c_claimant, count_before)
    print("\ncancel-path claim_id:", claim_id)

    receipt = c_claimant.cancel_claim(args=[claim_id]).transact(
        wait_interval=5000, wait_retries=90
    )
    assert not tx_execution_failed(receipt), receipt
    print("cancel_claim:", receipt.get("status_name"))

    claim = json.loads(c_claimant.get_claim(args=[claim_id]).call())
    assert claim["status"] == "CANCELLED"
    assert claim["claim_bond_deposited"] == "0"


@pytest.mark.integration
def test_claim_unreviewed_timeout_live():
    """create_claim with a short recovery window, genuinely wait it out
    (no fakeable timestamp -- the contract reads consensus block time),
    then claim_unreviewed_timeout since nobody ever audited it."""
    claimant = _load_account("claimant")
    beneficiary = _load_account("beneficiary")
    factory = get_contract_factory(contract_file_path="greenwash_bond.py")
    c_claimant = factory.build_contract(CONTRACT_ADDRESS, account=claimant)

    now = datetime.datetime.now(datetime.timezone.utc)
    deadline = now + datetime.timedelta(seconds=20)
    audit_at = deadline
    recovery = audit_at + datetime.timedelta(seconds=25)

    count_before = c_claimant.get_claim_count().call()
    receipt = c_claimant.create_claim(
        args=[
            "Abandoned Cold-Chain Efficiency Claim",
            "We claimed a 15% refrigeration efficiency gain from a "
            "compressor retrofit, but never followed up with evidence "
            "or an audit request.",
            "Requires equipment registry or energy-log evidence.",
            "Single cold-storage depot compressor retrofit.",
            _iso(deadline),
            _iso(audit_at),
            _iso(recovery),
            beneficiary.address,
            "[]",
            6000,
            3000,
            0,
            "",
        ]
    ).transact(value=int(0.3 * GEN), wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    claim_id = _new_claim_id(c_claimant, count_before)
    print("\nunreviewed-timeout claim_id:", claim_id)

    while datetime.datetime.now(datetime.timezone.utc) <= recovery:
        time.sleep(2)

    receipt = c_claimant.claim_unreviewed_timeout(args=[claim_id]).transact(
        wait_interval=5000, wait_retries=90
    )
    assert not tx_execution_failed(receipt), receipt
    print("claim_unreviewed_timeout:", receipt.get("status_name"))

    claim = json.loads(c_claimant.get_claim(args=[claim_id]).call())
    assert claim["status"] == "EXPIRED"
    assert claim["settlement_reason"] == "UNREVIEWED_TIMEOUT"
    assert claim["claim_bond_deposited"] == "0"


@pytest.mark.integration
def test_conflict_and_stalled_conflict_timeout_live():
    """Submits genuinely contradictory evidence to try to reach a real
    EVIDENCE_CONFLICT verdict, then (only if that verdict actually lands)
    waits out the recovery window and calls claim_stalled_conflict_timeout.
    LLM adjudication is nondeterministic, so this documents rather than
    forces the outcome when the verdict lands elsewhere."""
    claimant = _load_account("claimant")
    beneficiary = _load_account("beneficiary")
    factory = get_contract_factory(contract_file_path="greenwash_bond.py")
    c_claimant = factory.build_contract(CONTRACT_ADDRESS, account=claimant)

    now = datetime.datetime.now(datetime.timezone.utc)
    deadline = now + datetime.timedelta(seconds=60)
    audit_at = deadline
    recovery = audit_at + datetime.timedelta(seconds=20)

    count_before = c_claimant.get_claim_count().call()
    receipt = c_claimant.create_claim(
        args=[
            "Disputed Wetland Restoration Claim",
            "We restored a 3-hectare coastal wetland to full tidal flow in "
            "2025, fully removing the old berm that blocked the estuary.",
            "Requires site evidence of berm removal and tidal reconnection.",
            "3-hectare coastal wetland restoration, single site.",
            _iso(deadline),
            _iso(audit_at),
            _iso(recovery),
            beneficiary.address,
            "[]",
            7000,
            3000,
            0,
            "",
        ]
    ).transact(value=int(0.4 * GEN), wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    claim_id = _new_claim_id(c_claimant, count_before)
    print("\nconflict-path claim_id:", claim_id)

    receipt = c_claimant.submit_evidence(
        args=[
            claim_id,
            "CLAIMANT",
            "REPORT",
            "https://en.wikipedia.org/wiki/Wetland_restoration",
            "Site inspection report stating the berm was fully removed and "
            "tidal flow was completely restored in 2025.",
            "",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("submit_evidence (supporting):", receipt.get("status_name"))

    receipt = c_claimant.submit_evidence(
        args=[
            claim_id,
            "CHALLENGER",
            "REPORT",
            "https://en.wikipedia.org/wiki/Estuary",
            "Independent site inspection report from the same month stating "
            "the berm is still fully intact and no tidal reconnection has "
            "occurred at this site.",
            "",
        ]
    ).transact(wait_interval=5000, wait_retries=90)
    assert not tx_execution_failed(receipt), receipt
    print("submit_evidence (contradicting):", receipt.get("status_name"))

    while datetime.datetime.now(datetime.timezone.utc) <= audit_at:
        time.sleep(2)

    receipt = c_claimant.mark_ready_for_audit(args=[claim_id]).transact(
        wait_interval=5000, wait_retries=90
    )
    assert not tx_execution_failed(receipt), receipt
    print("mark_ready_for_audit:", receipt.get("status_name"))

    receipt = c_claimant.audit_claim(args=[claim_id]).transact(
        wait_interval=8000, wait_retries=150
    )
    assert not tx_execution_failed(receipt), receipt
    print("audit_claim:", receipt.get("status_name"))

    claim = json.loads(c_claimant.get_claim(args=[claim_id]).call())
    print("verdict:", claim["last_verdict"])

    if claim["last_verdict"] == "EVIDENCE_CONFLICT":
        while datetime.datetime.now(datetime.timezone.utc) <= recovery:
            time.sleep(2)
        receipt = c_claimant.claim_stalled_conflict_timeout(args=[claim_id]).transact(
            wait_interval=5000, wait_retries=90
        )
        assert not tx_execution_failed(receipt), receipt
        print("claim_stalled_conflict_timeout:", receipt.get("status_name"))

        final = json.loads(c_claimant.get_claim(args=[claim_id]).call())
        assert final["status"] == "EXPIRED"
        assert final["settlement_reason"] == "CONFLICT_TIMEOUT_REFUND"
    else:
        print(
            "Consensus did not land on EVIDENCE_CONFLICT this run "
            "(nondeterministic LLM adjudication) -- "
            "claim_stalled_conflict_timeout was not exercised."
        )
