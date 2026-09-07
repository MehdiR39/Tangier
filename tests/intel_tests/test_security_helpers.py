from intel.chain.constants import PRIVILEGED_SIGNATURES
from intel.chain.erc20 import detect_eip1167
from intel.ingest.security import STATUS_ORDER, Check, SecurityReport, _abi_function_sigs, _names
from intel.utils.abi import bytecode_has_selector, selector


def test_abi_signatures_and_privileged_detection():
    abi = [
        {"type": "function", "name": "mint", "inputs": [{"type": "address"}, {"type": "uint256"}]},
        {"type": "function", "name": "setBlacklist", "inputs": [{"type": "address"}, {"type": "bool"}]},
        {"type": "function", "name": "balanceOf", "inputs": [{"type": "address"}]},
        {"type": "function", "name": "quote", "inputs": [{"type": "tuple", "components": [{"type": "address"}, {"type": "uint24"}]}]},
        {"type": "event", "name": "Transfer", "inputs": []},
    ]
    sigs = _abi_function_sigs(abi)
    assert "mint(address,uint256)" in sigs and "setBlacklist(address,bool)" in sigs and "quote((address,uint24))" in sigs
    assert "mint" in _names(sigs)
    hits = {PRIVILEGED_SIGNATURES[s][0] for s in sigs if s in PRIVILEGED_SIGNATURES}
    assert hits == {"mint", "blacklist"}
    assert PRIVILEGED_SIGNATURES["mint(address,uint256)"][1] == "FAIL"


def test_bytecode_scan_for_selectors():
    mint_sel = selector("mint(address,uint256)")
    assert mint_sel == "0x40c10f19"
    code = "0x6080604052" + "63" + mint_sel[2:] + "14610100"
    assert bytecode_has_selector(code, mint_sel)
    assert not bytecode_has_selector("0x6080604052", mint_sel)


def test_eip1167_detection_matches_saylormoon_clone():
    # deployed bytecode captured from Blockscout for SAYLORMOON (clone of DopplerERC20V1)
    code = "0x3d3d3d3d363d3d37363d733be8b97fd0e713b5abe0649fa830223b6b4bc5995af43d3d93803e602a57fd5bf3"
    assert detect_eip1167(code) == "0x3be8b97fd0e713b5abe0649fa830223b6b4bc599"
    assert detect_eip1167("0x6080604052") is None


def test_security_report_overall_never_upgrades_unknown():
    checks = [Check("a", "PASS", ""), Check("b", "UNKNOWN", "")]
    r = SecurityReport(checks, None, None, None, True, None, None, {})
    assert r.overall == "UNKNOWN"
    checks.append(Check("c", "WARN", ""))
    assert r.overall == "WARN"
    checks.append(Check("d", "FAIL", ""))
    assert r.overall == "FAIL" and [c.name for c in r.fails] == ["d"]
    assert STATUS_ORDER["UNKNOWN"] > STATUS_ORDER["PASS"]
