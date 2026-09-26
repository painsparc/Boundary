import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

from main import CoreEngine
import pytest

@pytest.fixture(scope="module")
def engine():
    return CoreEngine()

def test_composite_linkage(engine):
    data = {"age": 43, "city": "Pune", "occupation": "Doctor", "unrelated": "data"}
    risk, fields = engine.analyze_linkage_risk(data)
    assert risk == 0.85
    assert "age" in fields

def test_semantic_detection(engine):
    text = "Patient requires treatment for high blood pressure."
    cats = engine.analyze_semantics(text)
    assert "medical_context" in cats

def test_differential_outputs(engine):
    data = {"name": "Test User", "bank_account": "12345", "amount": 100}
    
    # Internal allows bank
    res_fraud = engine.process_record(data, "internal_fraud_system", "fraud_investigation")
    assert res_fraud["data"]["bank_account"] == "12345"
    
    # LLM redacts bank
    res_llm = engine.process_record(data, "third_party_llm", "customer_support")
    assert res_llm["data"]["bank_account"] == "[REDACTED]"