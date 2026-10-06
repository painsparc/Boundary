# Boundary

> **Context-aware sensitive-data protection at the system boundary.**

Boundary is a local data-protection prototype that evaluates structured application data before it crosses a software boundary and applies a configurable policy using detected sensitivity, composite quasi-identifier risk, destination, and purpose.

The central idea is simple:

> **Sensitive-data handling should depend on both the data and the context in which it is being used.**

Instead of applying one global rule to every sensitive field, Boundary can transform the same logical record differently for an internal system, a third-party LLM, or an analytics destination.

---

## Architecture

```text
Application / Service
        |
        | structured data
        v
+---------------------------+
|         BOUNDARY          |
|                           |
| Detection                 |
|  - Presidio               |
|  - semantic embeddings    |
|  - static field mappings  |
|                           |
| Risk assessment           |
|  - field sensitivity      |
|  - composite linkage      |
|                           |
| Context                   |
|  - destination trust      |
|  - purpose scope          |
|                           |
| Policy                    |
|  - YAML rules             |
|                           |
| Transformation            |
|  - ALLOW                  |
|  - MASK                   |
|  - REDACT                 |
|  - GENERALIZE             |
|  - REMOVE                 |
|  - BLOCK                  |
|                           |
| Explanation + audit       |
+-------------+-------------+
              |
              v
       Downstream system
````

---

# Problem

Applications routinely move the same information between software systems with very different trust levels and purposes:

* internal services
* fraud systems
* analytics pipelines
* external APIs
* third-party AI/LLM providers

A conventional privacy rule often reduces the problem to:

```text
sensitive -> redact
```

That is not always appropriate.

A bank account number may be necessary for a fraud investigation but unnecessary for a marketing analysis. Likewise, age, city, and occupation may each appear harmless in isolation but become more identifying when combined.

Boundary treats protection as a context-dependent runtime decision:

```text
data
  +
sensitivity
  +
linkage risk
  +
destination
  +
purpose
  +
configured policy
        |
        v
  protection action
        |
        v
 downstream payload
```

---

# Core capabilities

## 1. Sensitive-data detection

Boundary currently combines multiple detection signals.

### Microsoft Presidio

The engine invokes the Presidio analyzer on string values and incorporates detected entities into the field-risk calculation.

The current implementation can surface entity categories such as:

* `PERSON`
* `PHONE_NUMBER`
* `EMAIL_ADDRESS`
* `LOCATION`
* other categories supported by the configured Presidio analyzer

Presidio is one component of the decision pipeline rather than the complete policy engine.

### Static high-risk field mappings

The current prototype explicitly treats:

```text
government_id
bank_account
```

as high-risk fields.

### Semantic contextual detection

For free-text content, Boundary also uses:

```text
sentence-transformers
all-MiniLM-L6-v2
```

The model compares text embeddings against configured semantic anchor phrases.

Current semantic categories include:

```text
medical_context
financial_context
```

For example:

```text
"Patient requires treatment for high blood pressure."
```

can trigger `medical_context` through semantic similarity even without relying on a conventional PII pattern.

> The semantic layer is a compact embedding-based heuristic classifier, not a fine-tuned medical or financial classifier.

---

## 2. Composite / quasi-identifier risk

Boundary defines the following configurable quasi-identifiers:

```text
age
city
occupation
region
postal_code
```

The prototype considers combinations of these fields rather than only individual fields.

Current heuristic:

| Number of configured quasi-identifiers present | Linkage risk |
| ---------------------------------------------: | -----------: |
|                                              0 |         0.00 |
|                                              1 |         0.20 |
|                                              2 |         0.50 |
|                                             3+ |         0.85 |

For example:

```text
age + city + occupation
```

produces a higher linkage-risk signal than any one field alone.

> This is a prototype heuristic. It is not a formal population-level k-anonymity implementation and does not provide a statistical guarantee of re-identification resistance.

---

## 3. Destination-aware decisions

The current demonstration defines three destinations:

```text
internal_fraud_system
third_party_llm
marketing_analytics
```

Each destination has a locally configured trust baseline in `src/config.py`.

Example:

```python
DESTINATION_TRUST = {
    "internal_fraud_system": 0.95,
    "third_party_llm": 0.40,
    "marketing_analytics": 0.60
}
```

The trust value contributes to overall risk assessment and makes downstream contexts distinguishable.

---

## 4. Purpose-aware decisions

The current demonstration defines:

```text
fraud_investigation
customer_support
aggregate_analysis
```

Each purpose has a configured scope value:

```python
PURPOSE_SCOPE = {
    "fraud_investigation": 0.20,
    "customer_support": 0.50,
    "aggregate_analysis": 0.80
}
```

Purpose therefore participates in the decision context rather than being treated as external metadata.

---

## 5. Policy-driven transformation

Policies live outside the core engine in:

```text
src/policies.yaml
```

Supported transformation actions are:

| Action       | Behaviour                                  |
| ------------ | ------------------------------------------ |
| `ALLOW`      | Preserve the original value                |
| `MASK`       | Partially obscure the value                |
| `REDACT`     | Replace the value with `[REDACTED]`        |
| `GENERALIZE` | Reduce precision or specificity            |
| `REMOVE`     | Omit the field from the downstream payload |
| `BLOCK`      | Replace the value with `[BLOCKED]`         |

Rules are organized by destination and purpose.

Example:

```yaml
third_party_llm:
  customer_support:
    bank_account: REDACT
    government_id: BLOCK
    name: MASK
```

---

## 6. Explainable decisions

The engine returns field-level explanations containing information such as:

* field
* detected categories
* action
* risk
* reason
* detection method

Example:

```json
{
  "field": "bank_account",
  "categories": ["bank_account"],
  "action": "REDACT",
  "risk": 0.95,
  "reason": "Policy enforcement on detected category: bank_account",
  "detection_method": "static_mapping"
}
```

This makes decisions inspectable instead of producing only a final transformed payload.

---

## 7. Audit logging

Boundary appends decision records to:

```text
logs/audit.jsonl
```

The current audit records include fields such as:

* timestamp
* audit ID
* destination
* purpose
* field
* categories
* action
* risk
* reason
* detection method

The current implementation uses local JSONL logging rather than a centralized observability or audit service.

---

# Decision model

Every request runs through the same stages:

1. **Validate the route.** Unknown destinations/purposes are rejected (HTTP 422). A known pair with no configured policy is also rejected, rather than silently falling back.
2. **Walk the payload.** Nested objects and lists are scanned, not just top-level strings. `null` values are dropped. Field names are normalised (`accountNumber`, `Account-Number` and `acct_no` all resolve to `bank_account`).
3. **Detect.** Field-name aliases, value patterns (government-ID formats, Aadhaar with Verhoeff checksum), Presidio (score >= 0.4; `DATE_TIME` ignored, `LOCATION`/`NRP`/`URL` low-risk), and a semantic check on any multi-word string (embeddings when the model is available, plus an always-on keyword lexicon).
4. **Decide.** All matching policy rules (field name and detected categories) are collected and the **strictest action wins** (`ALLOW < MASK < GENERALIZE < REDACT < BLOCK < REMOVE`). With no rule, values with risk >= 0.5 are blocked (zero-trust fallback); the explanation says so.
5. **Transform.** Unknown actions fail closed (BLOCK). `GENERALIZE` on an unsupported field falls back to `REDACT`.
6. **Re-assess the final payload.** Residual risk is recomputed from what is actually left in the output:

```text
overall_risk =
    max_exposed_field_risk x (1 - destination_trust)
    +
    residual_linkage_risk x purpose_scope          (capped at 1.0)
```

If it exceeds `MAX_RESIDUAL_RISK` (0.5), Boundary escalates: exposed quasi-identifiers are generalised, then exposed sensitive fields are blocked, until the payload is within limit. Escalations are flagged in the explanations. `input_risk` reports the same formula on the raw input for comparison.

7. **Explain and audit.** Every request writes a `request` audit record (including all-benign ones); changed or high-risk fields get `field` records. Each record carries the policy hash. Raw values are never logged.

```text
                         Input
                           |
                           v
                 Detection / classification
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
      Presidio         Semantic         Static mapping
       signal           signal             signal
          +----------------+----------------+
                           |
                           v
                  Quasi-identifier check
                           |
                           v
                       Field risk
                           |
                           v
                  Destination + purpose
                           |
                           v
                      YAML policy
                           |
                 +---------+---------+
                 |                   |
                 v                   v
          explicit rule          no rule
                 |                   |
                 v                   v
              action        risk-based fallback
                                     |
                                     v
                            ALLOW / BLOCK /
                              transform
                                     |
                                     v
                            Explain + audit
```

When no explicit policy rule matches a sufficiently high-risk value, the engine applies the zero-trust fallback and blocks it (`fallback_used: true` in the explanation).

---

# End-to-end demonstration

The repository contains a synthetic fintech support-ticket fixture:

```text
data/input/fintech_support_ticket.json
```

It combines direct identifiers, financial fields, quasi-identifiers, transaction information, and free-text context.

Representative fields include:

```text
name
phone
email
age
city
occupation
government_id
bank_account
transaction_id
amount
free_text_note
```

The same logical record can then be evaluated against different contexts.

## Internal fraud system

```text
destination = internal_fraud_system
purpose     = fraud_investigation
```

The configured policy permits selected sensitive financial information for the demonstration workflow.

## Third-party LLM

```text
destination = third_party_llm
purpose     = customer_support
```

The configured policy is more restrictive.

The committed example output demonstrates transformations such as:

```text
name            -> MASK
phone           -> REDACT
email           -> MASK
government_id   -> BLOCK
bank_account    -> REDACT
free_text_note  -> REDACT
```

## Marketing analytics

```text
destination = marketing_analytics
purpose     = aggregate_analysis
```

The example policy removes direct identifiers and generalizes selected quasi-identifiers:

```text
age: 43
    -> 40-49

city: Pune
    -> Regional Area
```

The important behaviour is therefore:

> **The same input can produce different downstream representations depending on destination and purpose.**

---

# API

Boundary is exposed through a small FastAPI service in `src/api.py`.

## `GET /health`

Health endpoint.

Example:

```json
{
  "status": "ok",
  "offline_first": true,
  "semantic_backend": "lexicon",
  "policy_hash": "3f9c1a0b2d4e5f67"
}
```

Returns `503` until the engine has loaded. `semantic_backend` is `embedding+lexicon` when the MiniLM model could be loaded, otherwise `lexicon` (offline fallback).

## `GET /routes`

Lists which purposes have a policy for each destination (used by the UI dropdowns).

## `POST /protect`

Processes structured application data.

Request:

```json
{
  "data": {
    "name": "Test User",
    "age": 43,
    "city": "Pune",
    "occupation": "Doctor",
    "bank_account": "12345"
  },
  "destination": "third_party_llm",
  "purpose": "customer_support"
}
```

Returns `422` for an unknown destination/purpose, a pair with no policy, or an over-deep/over-large payload.

Response fields include:

```text
metadata
  -> destination, purpose, audit_id
  -> policy (hash, found, fallback_fields)
  -> risk_assessment (overall_risk = final payload, input_risk, linkage_risk,
                      residual_linkage_risk, residual_risk_limit, within_limit, escalations)

explanations

data
  -> transformed downstream payload
```

## `POST /generate-policy`

The endpoint accepts:

* application context
* destination
* purpose
* sample fields

It uses a locally running Ollama model to propose structured field-level actions. Input is validated (field-name charset, length limits), the context is passed as untrusted data, and any proposal that breaks a security invariant (for example `ALLOW` on `bank_account` for an untrusted destination) is clamped to `BLOCK`. Returns `503` if Ollama is unreachable.

## `POST /save-policy`

Validates and writes reviewed rules into `src/policies.yaml`, then hot-reloads the policy (the ML models are not reloaded).

* Rules are **merged** into the existing block by default; send `"replace": true` to replace the block.
* Actions must be one of `ALLOW, MASK, GENERALIZE, REDACT, BLOCK, REMOVE` (case-insensitive); destination and purpose must be known.
* **Security invariant:** `bank_account`, `government_id`, `medical_context` and `financial_context` can never be `ALLOW` for a destination with trust below 0.90. Violations return `422` with the list of problems and nothing is written. The same check runs when the policy file is loaded, so a hand-edited unsafe file refuses to load.
* Writes are atomic (temp file + `os.replace`) and serialised; the response includes `previous_hash` and `policy_hash`, and the change is audited.

`/save-policy` and `/generate-policy` are admin endpoints: they require the `X-API-Key` header when `BOUNDARY_ADMIN_KEY` is set, and are otherwise restricted to loopback clients.

---

# Local AI policy workflow

The presentation layer contains a setup workflow for generating a policy proposal with a locally running model.

```text
Application context
       +
Destination
       +
Purpose
       +
Sample fields
       |
       v
    Ollama
       |
       v
Structured proposal
       |
       v
Human review / editing
       |
       v
YAML policy
       |
       v
Engine reload
```

The current backend requests:

```text
llama3.2
```

through the Ollama Python client.

The model proposes a policy; the human reviews and confirms it before the rule set is persisted.

The runtime `/protect` path does not require a cloud API.

---

# Repository structure

```text
Boundary/
|
+-- data/
|   +-- input/
|   |   +-- fintech_support_ticket.json
|   |
|   +-- output/
|       +-- internal_fraud_system.json
|       +-- marketing_analytics.json
|       +-- third_party_llm.json
|
+-- logs/
|   +-- (audit.jsonl is written at runtime and git-ignored)
|
+-- presentation layer/
|   +-- boundary_frontend/
|       +-- lib/
|       |   +-- main.dart
|       +-- pubspec.yaml
|       +-- ...
|
+-- src/
|   +-- api.py
|   +-- client.py
|   +-- config.py
|   +-- fields.py
|   +-- generate_examples.py
|   +-- main.py
|   +-- policies.yaml
|   +-- policy.py
|   +-- semantic.py
|   +-- validators.py
|
+-- tests/
|   +-- test_boundary.py
|
+-- BUG_REPORT.md
+-- LICENSE
+-- REPRODUCIBILITY_VERIFICATION.md
+-- SETUP.md
+-- dump_project.py
+-- pytest.ini
+-- requirements.txt
+-- setup.ps1
```

### Core files

| File                                                 | Purpose                                                   |
| ---------------------------------------------------- | --------------------------------------------------------- |
| `src/main.py`                                        | Core `CoreEngine` implementation                          |
| `src/config.py`                                      | Paths, trust baselines, thresholds, field vocabularies    |
| `src/policy.py`                                      | Policy validation, security invariants, atomic saves      |
| `src/fields.py`                                      | Field-name normalisation and aliases                      |
| `src/semantic.py`                                    | Embedding + lexicon contextual detection                  |
| `src/generate_examples.py`                           | Regenerates `data/output/` (run after policy changes)     |
| `src/policies.yaml`                                  | Destination/purpose policy matrix                         |
| `src/api.py`                                         | FastAPI service                                           |
| `src/client.py`                                      | Python API demonstration client                           |
| `tests/test_boundary.py`                             | Core automated tests                                      |
| `data/input/fintech_support_ticket.json`             | Synthetic input fixture                                   |
| `data/output/`                                       | Example transformed outputs                               |
| `logs/audit.jsonl`                                   | Runtime audit records (git-ignored)                       |
| `presentation layer/boundary_frontend/lib/main.dart` | Flutter presentation layer                                |

---

# Running locally

> The current repository does not include a pinned Python dependency manifest, Dockerfile, or Docker Compose configuration. The commands below describe the current source tree.

## Python environment

Python 3.10+ is recommended.

Create an environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the packages used by the current backend:

```bash
pip install fastapi uvicorn pydantic pyyaml requests numpy presidio-analyzer sentence-transformers spacy ollama pytest
```

Install the English spaCy model expected by the development setup:

```bash
python -m spacy download en_core_web_lg
```

> Exact dependency versions are not currently pinned.

---

# Start the backend

From the repository root:

```bash
uvicorn src.api:app --reload
```

Default local endpoint:

```text
http://127.0.0.1:8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

---

# Run the example client

With the API running:

```bash
python src/client.py
```

The client sends a sample payload to:

```text
POST /protect
```

and prints the resulting JSON.

---

# Run tests

The suite (`tests/test_boundary.py`, ~70 cases) covers:

* the original behaviours: composite linkage, semantic detection, differential outputs per destination
* every item in `BUG_REPORT.md` (policy/runtime consistency, renamed fields and value patterns, unsafe-policy rejection, unsupported combinations, residual-risk re-check, stale example outputs)
* nested/list payloads, fail-closed actions, `MASK`/`GENERALIZE` edge cases, null and alias-insensitive linkage, false-positive guards on operational fields, input limits
* audit completeness (and that raw values are never logged), CORS, admin-endpoint protection, 503 when the engine is not ready, AI-proposal clamping

Tests use temporary policy and audit files, so they never modify tracked files.

Run:

```bash
pytest
```

---

# Flutter presentation layer

The Flutter UI is under:

```text
presentation layer/boundary_frontend/
```

Install dependencies:

```bash
cd "presentation layer/boundary_frontend"
flutter pub get
```

Run with a supported Flutter target:

```bash
flutter run
```

The current UI expects the backend at:

```text
http://127.0.0.1:8000
```

## Intercept mode

The interface allows you to:

1. enter structured data
2. select a destination
3. select a purpose
4. execute Boundary
5. inspect the transformed payload
6. inspect risk and field-level explanations

## Setup mode

The interface allows you to:

1. define application context
2. select destination and purpose
3. generate a local AI policy proposal
4. review/edit proposed field actions
5. save the policy
6. reload the engine

---

# Configuration

## Destination trust

Configured in:

```text
src/config.py
```

Example:

```python
DESTINATION_TRUST = {
    "internal_fraud_system": 0.95,
    "third_party_llm": 0.40,
    "marketing_analytics": 0.60
}
```

## Purpose scope

```python
PURPOSE_SCOPE = {
    "fraud_investigation": 0.20,
    "customer_support": 0.50,
    "aggregate_analysis": 0.80
}
```

## Quasi-identifiers

```python
QUASI_IDENTIFIERS = {
    "age",
    "city",
    "occupation",
    "region",
    "postal_code"
}
```

## Policy rules

Configured in:

```text
src/policies.yaml
```

The policy matrix is organized as:

```text
destination
    |
    +-- purpose
          |
          +-- field/category -> action
```

Rule keys are normalised and aliased, so `gov_id` and `GovernmentID` both configure `government_id`. After editing `policies.yaml`, run `python src/generate_examples.py` to refresh `data/output/`; the test suite fails if the committed examples are stale.

---

# Security considerations

Boundary is a data-processing component and should be treated accordingly.

For the current prototype:

* do not commit real personal data
* treat input/output files as potentially sensitive
* review audit logs before publishing them
* do not expose the API directly to an untrusted network
* `/protect` itself has no authentication; add authentication and authorization before any internet-facing deployment
* policy-changing endpoints require `X-API-Key` when `BOUNDARY_ADMIN_KEY` is set, otherwise they accept loopback clients only
* CORS allows only `localhost` / `127.0.0.1` origins by default; set `BOUNDARY_CORS_ORIGINS` (comma-separated) for others
* use proper secret management for production systems
* protect or replace local audit storage for production use (`BOUNDARY_AUDIT_LOG` overrides the path)

---

# Synthetic data

The demonstration uses synthetic data.

Primary input:

```text
data/input/fintech_support_ticket.json
```

Example outputs:

```text
data/output/internal_fraud_system.json
data/output/third_party_llm.json
data/output/marketing_analytics.json
```

The project does not require production customer data to demonstrate its core workflow.

---

# Limitations

Boundary is a prototype rather than a production privacy platform.

### Detection limitations

Sensitive-data detection is dependent on Presidio, field-name aliases, a few value patterns, and the semantic heuristic. False positives and false negatives are possible; names outside the alias list holding values that match no pattern (for example a free-form account reference) are only caught if Presidio or the semantic layer flags them.

### Linkage-risk limitations

The current linkage score is based only on the count of configured quasi-identifiers present in the record.

It does not:

* query a population reference dataset
* calculate actual uniqueness
* implement formal k-anonymity
* guarantee resistance to re-identification

### Semantic limitations

The semantic classifier uses a compact embedding model with manually selected anchor phrases, plus a keyword lexicon that always runs. When the model cannot be downloaded the engine runs lexicon-only (reported by `/health`). It is not trained specifically for every domain.

### Policy limitations

The YAML grammar and transformation functions are intentionally small. `GENERALIZE` is implemented for `age`, `city`, `region` and `postal_code`; other fields fall back to `REDACT`. Residual-risk escalation can override an explicit `ALLOW`/`MASK` on quasi-identifiers.

### Destination limitations

Destination trust is locally configured. It is not dynamically verified against an external trust registry.

### Compliance limitations

Boundary does not itself provide compliance with GDPR, India's DPDP Act, HIPAA, PCI DSS, SOC 2, or any other framework.

A deployment would require a separate assessment of its threat model, controls, data flows, and legal obligations.

---

# Reproducibility status

The repository currently contains:

* source code
* configuration
* synthetic input data
* example outputs
* tests
* presentation-layer source
* audit records

Dependencies are pinned in `requirements.txt`, and `pytest` runs the suite offline (the embedding model is optional).

The repository still does **not** contain a Python lockfile, Dockerfile, Docker Compose configuration or CI workflow. See `REPRODUCIBILITY_VERIFICATION.md` for what has and has not been verified on a clean machine.

---

# Development philosophy

Boundary follows a deliberately compact pipeline:

```text
DETECT
  |
  v
ASSESS
  |
  v
CONTEXT
  |
  v
POLICY
  |
  v
TRANSFORM
  |
  v
EXPLAIN
  |
  v
AUDIT
```

The prototype is not intended to solve every privacy problem.

It demonstrates one systems-level idea:

> **Make data-handling decisions at the boundary where information moves from one software context into another.**

---

# Future work

Possible future engineering directions include:

* dependency pinning
* containerized deployment
* CI-based reproducibility
* expanded test coverage
* benchmark datasets and evaluation metrics
* richer sensitivity ontologies
* stronger linkage-risk models
* configurable transformation strategies
* improved policy validation
* pluggable destination-trust sources
* SDK and middleware integrations
* stronger audit integrity
* performance profiling and caching

These are future directions and are not represented as existing features.

---

# Academic context

Boundary was developed as an **Open Source Tools for Data Science (OST)** course project.

The repository demonstrates the practical integration of:

* Git / GitHub
* Python
* FastAPI
* NLP / embeddings
* configuration-driven policy enforcement
* automated tests
* Flutter
* local model inference
* synthetic data
* audit logging

The implementation is deliberately scoped as a small, inspectable engineering prototype.

---

# Project identity

**Boundary**

**Context-aware sensitive-data protection at the system boundary.**

Developed by **Painsparc**.

Repository:

[https://github.com/painsparc/Boundary](https://github.com/painsparc/Boundary)

---

# Third-party components

The current implementation uses third-party software and models including:

* Microsoft Presidio
* spaCy
* Sentence Transformers
* FastAPI
* Pydantic
* PyYAML
* NumPy
* Requests
* Ollama
* Flutter

Each third-party component remains subject to its own license and terms.

---

# License

Boundary is released under the MIT License. See the `LICENSE` file at the repository root.

---

# Disclaimer

Boundary is an academic/research prototype provided for experimentation and demonstration.

It is not a guarantee of:

* complete sensitive-data detection
* privacy preservation
* re-identification prevention
* security
* regulatory compliance
* production suitability

Real deployments should be independently evaluated against their data classes, threat model, downstream systems, operational controls, and applicable requirements.

```
```
