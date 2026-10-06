import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import api  # noqa: E402
import config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from generate_examples import ROUTES, generate  # noqa: E402
from main import (CoreEngine, InputLimitError, PolicyNotFoundError,  # noqa: E402
                  UnknownRouteError, apply_action, mask_value)
from policy import PolicyError, PolicyStore  # noqa: E402

FIXTURE = json.loads((config.INPUT_DIR / "fintech_support_ticket.json").read_text())
LLM = ("third_party_llm", "customer_support")
FRAUD = ("internal_fraud_system", "fraud_investigation")
MKT = ("marketing_analytics", "aggregate_analysis")


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    """One engine for the whole session (spaCy + Presidio are heavy); tests reset its policy copy as needed."""
    tmp = tmp_path_factory.mktemp("engine")
    shutil.copy(config.POLICY_FILE, tmp / "policies.yaml")
    return CoreEngine(policy_path=tmp / "policies.yaml", audit_path=tmp / "audit.jsonl")


def run(engine, data, route):
    return engine.process_record(data, *route)


def verhoeff_aadhaar(base11: str) -> str:
    d = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
         [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
    p = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],
         [4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
    inv = [0,4,3,2,1,5,6,7,8,9]
    c = 0
    for i, ch in enumerate(reversed(base11)):
        c = d[c][p[(i + 1) % 8][int(ch)]]
    return base11 + str(inv[c])


# ---------------------------------------------------------------- original behaviours
def test_composite_linkage(engine):
    risk, fields = engine.analyze_linkage_risk({"age": 43, "city": "Pune", "occupation": "Doctor", "unrelated": "data"})
    assert risk == 0.85 and "age" in fields


def test_semantic_detection(engine):
    assert "medical_context" in engine.analyze_semantics("Patient requires treatment for high blood pressure.")


def test_differential_outputs(engine):
    data = {"name": "Test User", "bank_account": "12345", "amount": 100}
    assert run(engine, data, FRAUD)["data"]["bank_account"] == "12345"
    assert run(engine, data, LLM)["data"]["bank_account"] == "[REDACTED]"


# ---------------------------------------------------------------- Bug 1: policy/runtime consistency
def test_bug1_fraud_route_matches_policy(engine):
    r = run(engine, {"bank_account": "123456789012", "government_id": "GOV-482913"}, FRAUD)
    assert r["data"] == {"bank_account": "123456789012", "government_id": "[BLOCKED]"}
    by = {e["field"]: e for e in r["explanations"]}
    assert by["government_id"]["policy_rule"] and not by["government_id"]["fallback_used"]
    assert r["metadata"]["policy"]["found"] and r["metadata"]["policy"]["hash"] == engine.policy_store.hash


def test_bug1_explicit_vs_fallback_distinguishable(engine):
    r = engine.process_record({"bank_account": "1", "age": 40, "name": "A B"}, "third_party_llm", "fraud_investigation",
                              require_policy=False)
    assert r["metadata"]["policy"]["found"] is False
    assert all(e["fallback_used"] for e in r["explanations"] if e["field"] == "bank_account")


# ---------------------------------------------------------------- Bug 2: renamed fields / value patterns
@pytest.mark.parametrize("key", ["bank_account", "account_number", "account_no", "acct_no", "accountNumber",
                                 "Bank_Account", "beneficiary_account", "IBAN"])
@pytest.mark.parametrize("value", ["12345", "1234-5678-9012", "50100123456789"])
def test_bug2_bank_aliases_never_raw(engine, key, value):
    assert run(engine, {key: value}, LLM)["data"][key] != value


@pytest.mark.parametrize("key", ["government_id", "gov_id", "national_id", "identity_number", "id_number", "GovernmentID", "ssn"])
def test_bug2_gov_aliases_never_raw(engine, key):
    assert run(engine, {key: "GOV-88221"}, LLM)["data"][key] == "[BLOCKED]"


def test_bug2_value_patterns_in_neutral_field(engine):
    aadhaar = verhoeff_aadhaar("23456789012")
    out = run(engine, {"ref1": "GOV-482913", "ref2": "ABCDE1234F", "ref3": aadhaar, "ref4": "078-05-1120"}, LLM)["data"]
    assert all(v == "[BLOCKED]" for v in out.values()), out


# ---------------------------------------------------------------- Bug 3: unsafe policies
@pytest.fixture()
def client(engine, monkeypatch):
    """API client bound to the shared engine, with its policy file reset to the committed policy."""
    path = engine.policy_store.path
    shutil.copy(config.POLICY_FILE, path)
    engine.reload_policies()
    engine.audit_path.unlink(missing_ok=True)
    monkeypatch.setattr(api, "engine", engine)
    monkeypatch.setenv("BOUNDARY_ADMIN_KEY", "k")
    c = TestClient(api.app, headers={"X-API-Key": "k"})
    c.eng, c.tmp = engine, path.parent
    yield c
    shutil.copy(config.POLICY_FILE, path)
    engine.reload_policies()


@pytest.mark.parametrize("field", ["bank_account", "government_id", "medical_context", "account_number", "gov_id"])
def test_bug3_unsafe_allow_rejected_and_not_persisted(client, field):
    before = (client.tmp / "policies.yaml").read_bytes()
    r = client.post("/save-policy", json={"destination": "third_party_llm", "purpose": "customer_support", "rules": {field: "ALLOW"}})
    assert r.status_code == 422 and r.json()["detail"]["violations"]
    assert (client.tmp / "policies.yaml").read_bytes() == before


def test_bug3_safe_allow_for_trusted_destination_ok(client):
    r = client.post("/save-policy", json={"destination": "internal_fraud_system", "purpose": "fraud_investigation",
                                          "rules": {"bank_account": "ALLOW"}})
    assert r.status_code == 200


def test_bug3_invalid_action_and_route_rejected(client):
    assert client.post("/save-policy", json={"destination": "third_party_llm", "purpose": "customer_support",
                                             "rules": {"name": "DROP_IT"}}).status_code == 422
    assert client.post("/save-policy", json={"destination": "nope", "purpose": "customer_support", "rules": {"name": "MASK"}}).status_code == 422


def test_bug3_poisoned_policy_file_refuses_to_load(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("third_party_llm:\n  customer_support:\n    bank_account: ALLOW\n")
    with pytest.raises(PolicyError):
        PolicyStore(p)


def test_save_merges_by_default_and_replace_is_explicit(client):
    client.post("/save-policy", json={"destination": "marketing_analytics", "purpose": "aggregate_analysis", "rules": {"name": "BLOCK"}})
    rules = client.eng.policies["marketing_analytics"]["aggregate_analysis"]
    assert rules["name"] == "BLOCK" and rules["phone"] == "REMOVE" and rules["email"] == "REMOVE"
    client.post("/save-policy", json={"destination": "marketing_analytics", "purpose": "aggregate_analysis",
                                      "rules": {"name": "REMOVE"}, "replace": True})
    assert client.eng.policies["marketing_analytics"]["aggregate_analysis"] == {"name": "REMOVE"}


def test_save_policy_changes_hash_and_is_audited(client):
    h0 = client.eng.policy_store.hash
    r = client.post("/save-policy", json={"destination": "third_party_llm", "purpose": "customer_support", "rules": {"city": "GENERALIZE"}})
    assert r.json()["previous_hash"] == h0 != r.json()["policy_hash"] == client.eng.policy_store.hash
    assert "policy_saved" in (client.tmp / "audit.jsonl").read_text()


# ---------------------------------------------------------------- Bug 4: unsupported combinations
def test_bug4_combinations(engine):
    with pytest.raises(PolicyNotFoundError, match="No policy configured"):
        run(engine, {"a": "b"}, ("third_party_llm", "fraud_investigation"))
    with pytest.raises(UnknownRouteError):
        run(engine, {"a": "b"}, ("third_party_lml", "customer_support"))
    with pytest.raises(UnknownRouteError):
        run(engine, {"a": "b"}, ("third_party_llm", "made_up"))


def test_bug4_api_returns_clear_422_and_routes(client):
    r = client.post("/protect", json={"data": {"a": "b"}, "destination": "marketing_analytics", "purpose": "fraud_investigation"})
    assert r.status_code == 422 and "No policy configured" in r.json()["detail"]
    routes = client.get("/routes").json()["destinations"]
    assert routes["third_party_llm"] == ["customer_support"] and "fraud_investigation" not in routes["marketing_analytics"]


# ---------------------------------------------------------------- Bug 5: residual risk re-check
FIVE_QI = {"age": 43, "city": "Pune", "occupation": "Doctor", "postal_code": "411001", "region": "Maharashtra"}


@pytest.mark.parametrize("route", [LLM, MKT])
def test_bug5_final_payload_within_limit(engine, route):
    r = run(engine, FIVE_QI, route)
    ra = r["metadata"]["risk_assessment"]
    assert ra["within_limit"] and ra["overall_risk"] <= config.MAX_RESIDUAL_RISK
    assert ra["linkage_risk"] == 0.85 and ra["residual_linkage_risk"] < ra["linkage_risk"]


def test_bug5_escalation_is_explained(engine):
    r = run(engine, FIXTURE, LLM)
    assert r["metadata"]["risk_assessment"]["escalations"] >= 1
    assert any(e["escalated"] and "ESCALATED" in e["reason"] for e in r["explanations"])
    assert r["data"]["age"] == "40-49"


def test_bug5_trusted_destination_not_over_escalated(engine):
    assert run(engine, FIXTURE, FRAUD)["metadata"]["risk_assessment"]["escalations"] == 0


# ---------------------------------------------------------------- Bug 6: committed outputs match policies
def test_bug6_committed_examples_match_current_policy(engine):
    fresh = generate(engine)
    for dest in ROUTES:
        committed = json.loads((config.OUTPUT_DIR / f"{dest}.json").read_text())
        got = fresh[dest]
        assert committed["metadata"]["policy"]["hash"] == got["metadata"]["policy"]["hash"], \
            f"{dest}.json is stale: run `python src/generate_examples.py`"
        strip = lambda d: {k: v for k, v in d.items() if k != "free_text_note"}   # semantic backend may differ by env
        assert strip(committed["data"]) == strip(got["data"])


# ---------------------------------------------------------------- additional pipeline fixes
def test_nested_and_list_values_are_protected(engine):
    out = run(engine, {"customer": {"name": "Rahul Sharma", "bank_account": "123456789012", "government_id": "GOV-482913"},
                       "contacts": ["rahul@example.com", "+919876543210"], "mobile": 9876543210}, LLM)["data"]
    assert out["customer"] == {"name": "[REDACTED]", "bank_account": "[REDACTED]", "government_id": "[BLOCKED]"}
    assert out["contacts"] == ["[BLOCKED]", "[BLOCKED]"] and out["mobile"] == "[BLOCKED]"


def test_unknown_action_fails_closed():
    assert apply_action("secret", "DROP_IT", "x")[0] == "[BLOCKED]"
    assert apply_action("secret", "redact", "x")[0] == "[REDACTED]"
    assert apply_action("secret", None, "x")[0] == "[BLOCKED]"


def test_mask_and_generalize_do_not_crash(engine):
    assert mask_value("") == "***" and mask_value("a@b.com") == "a***@b.com" and mask_value("1234567890123456").endswith("3456")
    for v in ["", 0, "abc", [], {}, True]:
        run(engine, {"age": v, "city": "Pune"}, LLM)   # age=MASK: must never raise
    assert apply_action("abc", "GENERALIZE", "age")[1] == "REDACT"        # unsupported -> fail closed
    assert apply_action("411001", "GENERALIZE", "postal_code")[0] == "411***"
    assert apply_action(43, "GENERALIZE", "age")[0] == "40-49"


def test_semantic_detection_on_any_field(engine):
    r = run(engine, {"notes": "Patient was diagnosed with diabetes and had a cardiology appointment."}, MKT)
    assert "notes" not in r["data"]       # medical_context: REMOVE in the marketing policy


def test_linkage_is_case_alias_insensitive_and_ignores_nulls(engine):
    assert engine.analyze_linkage_risk({"Age": 43, "City": "Pune", "ZIP": "411001"})[0] == 0.85
    assert engine.analyze_linkage_risk({"age": None, "city": None, "occupation": None, "x": 1})[0] == 0.0
    assert engine.analyze_linkage_risk({"age": "", "city": " "})[0] == 0.0


def test_benign_operational_fields_not_blocked(engine):
    benign = {"transaction_id": "TXN-847291", "error_code": "PAY-402", "created_at": "2026-10-05", "country": "India",
              "order_ref": "ORD-1234567", "status": "pending", "amount": 18450}
    assert run(engine, benign, LLM)["data"] == benign


def test_strictest_matching_rule_wins(engine):
    # field rule free_text_note=MASK (fraud route) vs nothing else; marketing: medical_context=REMOVE beats no field rule
    r = run(engine, {"free_text_note": "Patient diagnosed at the hospital."}, MKT)
    assert "free_text_note" not in r["data"]


def test_input_limits(engine):
    deep = cur = {}
    for _ in range(config.MAX_DEPTH + 3):
        cur["x"] = {}
        cur = cur["x"]
    with pytest.raises(InputLimitError):
        run(engine, deep, LLM)


def test_audit_records_every_request_and_never_raw_values(engine):
    engine.audit_path.unlink(missing_ok=True)
    run(engine, {"merchant": "Example Store", "amount": 5}, LLM)                          # all-benign
    run(engine, {"name": None, "bank_account": "999988887777"}, LLM)
    text = engine.audit_path.read_text()
    rows = [json.loads(l) for l in text.splitlines()]
    assert sum(r["type"] == "request" for r in rows) == 2
    assert all(r["policy_hash"] == engine.policy_store.hash for r in rows if r["type"] != "event")
    assert "999988887777" not in text and "Example Store" not in text


# ---------------------------------------------------------------- API hardening
def test_cors_rejects_foreign_origin_allows_local(client):
    h = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    evil = client.options("/save-policy", headers={"Origin": "https://evil.example", **h})
    assert "access-control-allow-origin" not in evil.headers
    ok = client.options("/save-policy", headers={"Origin": "http://localhost:5000", **h})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5000"


def test_admin_endpoints_need_key(client, monkeypatch):
    body = {"destination": "third_party_llm", "purpose": "customer_support", "rules": {"city": "ALLOW"}}
    assert TestClient(api.app).post("/save-policy", json=body).status_code == 401
    assert TestClient(api.app, headers={"X-API-Key": "wrong"}).post("/save-policy", json=body).status_code == 401
    monkeypatch.delenv("BOUNDARY_ADMIN_KEY")
    assert TestClient(api.app).post("/save-policy", json=body).status_code == 403   # non-loopback client, no key


def test_cross_site_simple_post_cannot_change_policy(client):
    before = (client.tmp / "policies.yaml").read_bytes()
    r = TestClient(api.app).post("/save-policy", content='{"destination":"third_party_llm"}',
                                 headers={"Origin": "https://evil.example", "Content-Type": "text/plain"})
    assert r.status_code in (401, 403, 422) and (client.tmp / "policies.yaml").read_bytes() == before


def test_engine_not_ready_is_503(monkeypatch):
    monkeypatch.setattr(api, "engine", None)
    c = TestClient(api.app)
    assert c.get("/health").status_code == 503
    assert c.post("/protect", json={"data": {}, "destination": "x", "purpose": "y"}).status_code == 503


def test_health_and_protect_ok(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["policy_hash"] == client.eng.policy_store.hash
    r = client.post("/protect", json={"data": {"name": "Test User", "bank_account": "12345"}, "destination": "third_party_llm",
                                      "purpose": "customer_support"})
    assert r.status_code == 200 and r.json()["data"]["bank_account"] == "[REDACTED]"


def test_generate_policy_validates_input_and_clamps_unsafe_proposals(client, monkeypatch):
    bad = {"app_context": "x", "destination": "third_party_llm", "purpose": "customer_support", "sample_fields": ["ok", "bad;drop"]}
    assert client.post("/generate-policy", json=bad).status_code == 422

    class FakeOllama:
        @staticmethod
        def chat(**kw):
            payload = json.dumps({"rules": [{"field": "bank_account", "action": "allow", "reason": "needed"},
                                            {"field": "city", "action": "GENERALIZE", "reason": "ok"}]})
            return iter([{"message": {"content": payload}}])

    monkeypatch.setattr(api, "ollama", FakeOllama)
    good = {**bad, "sample_fields": ["bank_account", "city"]}
    rules = {r["field"]: r for r in client.post("/generate-policy", json=good).json()["rules"]}
    assert rules["bank_account"]["action"] == "BLOCK" and "clamped" in rules["bank_account"]["reason"]
    assert rules["city"]["action"] == "GENERALIZE"
