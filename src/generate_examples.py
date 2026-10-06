"""Regenerate data/output/*.json from the current policies (no audit side effects).

Run after ANY change to policies.yaml:  python src/generate_examples.py
tests/test_boundary.py fails if the committed examples are stale.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from main import CoreEngine

ROUTES = {
    "internal_fraud_system": "fraud_investigation",
    "third_party_llm": "customer_support",
    "marketing_analytics": "aggregate_analysis",
}


def generate(engine=None):
    engine = engine or CoreEngine(audit_enabled=False)
    record = json.loads((config.INPUT_DIR / "fintech_support_ticket.json").read_text())
    return {d: engine.process_record(record, d, p, audit_id=f"example-{d}") for d, p in ROUTES.items()}


if __name__ == "__main__":
    for dest, result in generate().items():
        (config.OUTPUT_DIR / f"{dest}.json").write_text(json.dumps(result, indent=2) + "\n")
        print("wrote", config.OUTPUT_DIR / f"{dest}.json")
