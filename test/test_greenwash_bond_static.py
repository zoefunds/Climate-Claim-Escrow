import ast
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "contracts" / "greenwash_bond.py"


def test_contract_parses_and_declares_genvm_collections():
    tree = ast.parse(SOURCE.read_text())
    contract = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GreenwashBond")
    annotations = {n.target.id: ast.unparse(n.annotation) for n in contract.body if isinstance(n, ast.AnnAssign)}
    assert annotations["claims"] == "TreeMap[str, str]"
    assert annotations["evidence"] == "TreeMap[str, str]"
    assert annotations["claim_ids"] == "DynArray[str]"


def test_schema_and_escrow_guards_are_present():
    source = SOURCE.read_text()
    assert "@gl.public.write.payable\n    def create_claim" in source
    assert "@gl.public.write.payable\n    def open_challenge" in source
    assert source.count("emit_transfer(") == 1
    assert 'claim["claim_bond_deposited"] = "0"' in source
    assert 'return gl.message_raw["datetime"]' in source


def test_web_visual_and_bounded_verdict_paths_exist():
    source = SOURCE.read_text()
    assert 'gl.nondet.web.render(url, mode="text", wait_after_loaded="2s")' in source
    assert "gl.nondet.exec_prompt(prompt, images=[image_data]" in source
    for verdict in ("SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "EVIDENCE_CONFLICT"):
        assert verdict in source
