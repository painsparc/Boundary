import os
from pathlib import Path

# Directory Routing
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
LOGS_DIR = BASE_DIR / "logs"
POLICY_FILE = BASE_DIR / "src" / "policies.yaml"

# Ensure directories exist
for directory in [INPUT_DIR, OUTPUT_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Trust Engine Baselines
DESTINATION_TRUST = {
    "internal_fraud_system": 0.95,
    "third_party_llm": 0.40,
    "marketing_analytics": 0.60
}

PURPOSE_SCOPE = {
    "fraud_investigation": 0.20,  # Narrow, high justification
    "customer_support": 0.50,     # Medium
    "aggregate_analysis": 0.80    # Broad, low justification for PII
}

# Linkage Risk Engine
QUASI_IDENTIFIERS = {"age", "city", "occupation", "region", "postal_code"}