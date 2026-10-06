"""Boundary configuration: routes, trust model, limits and field vocabularies."""
import os
from pathlib import Path

# ---------------------------------------------------------------- paths
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
LOGS_DIR = BASE_DIR / "logs"
POLICY_FILE = Path(os.environ.get("BOUNDARY_POLICY_FILE", BASE_DIR / "src" / "policies.yaml"))
AUDIT_FILE = Path(os.environ.get("BOUNDARY_AUDIT_LOG", LOGS_DIR / "audit.jsonl"))

# ---------------------------------------------------------------- trust model
# Only these destinations / purposes exist. Anything else is rejected, never defaulted.
DESTINATION_TRUST = {
    "internal_fraud_system": 0.95,
    "third_party_llm": 0.40,
    "marketing_analytics": 0.60,
}
PURPOSE_SCOPE = {
    "fraud_investigation": 0.20,  # narrow, high justification
    "customer_support": 0.50,     # medium
    "aggregate_analysis": 0.80,   # broad, low justification for PII
}

# Security invariant: below this destination trust, the categories in
# NO_ALLOW_CATEGORIES may never be configured as ALLOW (enforced on load AND save).
SENSITIVE_ALLOW_MIN_TRUST = 0.90
NO_ALLOW_CATEGORIES = {"bank_account", "government_id", "medical_context", "financial_context"}

# ---------------------------------------------------------------- decision thresholds
ZERO_TRUST_RISK_THRESHOLD = 0.5   # no rule + field risk >= this  ->  BLOCK
MAX_RESIDUAL_RISK = 0.5           # post-transformation risk limit; above it Boundary escalates
PRESIDIO_MIN_SCORE = 0.4
SEMANTIC_THRESHOLD = 0.45

# ---------------------------------------------------------------- request limits
MAX_DEPTH = 10
MAX_LEAVES = 5000
MAX_ANALYZE_CHARS = 20000

# ---------------------------------------------------------------- linkage (quasi-identifiers)
QUASI_IDENTIFIERS = {"age", "city", "occupation", "region", "postal_code"}
LINKAGE_TABLE = {0: 0.0, 1: 0.2, 2: 0.5}   # 3+ -> LINKAGE_MAX
LINKAGE_MAX = 0.85

# ---------------------------------------------------------------- field-name vocabulary
# Keys are normalised (snake_case, lower-case) before lookup, so accountNumber,
# Account-Number and ACCOUNT_NUMBER all resolve to the canonical name below.
FIELD_ALIASES = {
    "bank_account": {
        "bank_account", "bank_account_number", "bank_acct", "account_number", "account_no",
        "account_num", "acct_no", "acct_number", "beneficiary_account",
        "beneficiary_account_number", "iban", "card_number", "credit_card", "debit_card",
    },
    "government_id": {
        "government_id", "gov_id", "govt_id", "national_id", "national_identity_number",
        "identity_number", "id_number", "aadhaar", "aadhaar_number", "aadhar", "pan",
        "pan_number", "ssn", "social_security_number", "passport", "passport_number",
        "tax_id", "driver_license", "driving_license", "voter_id",
    },
    "phone": {"phone", "phone_number", "mobile", "mobile_number", "telephone", "cell", "cell_phone"},
    "email": {"email", "email_address", "e_mail"},
    "name": {"name", "full_name", "first_name", "last_name", "customer_name"},
    "age": {"age", "age_years"},
    "city": {"city", "town"},
    "region": {"region", "state", "province"},
    "postal_code": {"postal_code", "zip", "zip_code", "zipcode", "pincode", "pin_code", "postcode"},
    "occupation": {"occupation", "job", "job_title", "profession", "designation"},
}
HIGH_RISK_FIELDS = {"bank_account": 0.95, "government_id": 0.95}
SENSITIVE_FIELD_RISK = {"phone": 0.8, "email": 0.8, "name": 0.8}

# ---------------------------------------------------------------- Presidio mapping
ENTITY_CATEGORY = {
    "PERSON": "name", "EMAIL_ADDRESS": "email", "PHONE_NUMBER": "phone",
    "US_BANK_NUMBER": "bank_account", "IBAN_CODE": "bank_account", "CREDIT_CARD": "bank_account",
    "US_SSN": "government_id", "US_PASSPORT": "government_id", "US_DRIVER_LICENSE": "government_id",
    "IN_PAN": "government_id", "IN_AADHAAR": "government_id", "IN_PASSPORT": "government_id",
    "IN_VOTER": "government_id", "UK_NHS": "government_id", "UK_NINO": "government_id",
}
ENTITY_RISK = {"LOCATION": 0.3, "NRP": 0.3, "URL": 0.3}   # everything else defaults to 0.8
IGNORED_ENTITIES = {"DATE_TIME"}                           # far too noisy to act on
DEFAULT_ENTITY_RISK = 0.8

# Value patterns that identify a government ID regardless of the field name
# (the default Presidio registry has no India recognisers). Each pattern must match the whole value.
GOV_ID_VALUE_PATTERNS = {
    "gov_prefixed": r"(?i:(?:GOV|GOVT)[-_ ]?\d{4,})",
    "in_pan": r"[A-Z]{5}[0-9]{4}[A-Z]",
    "in_aadhaar": r"[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}",   # also requires a valid Verhoeff checksum
    "us_ssn": r"(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}",
}

for _d in (INPUT_DIR, OUTPUT_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
