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

The current prototype calculates overall risk as:

```text
overall_risk =
    max_field_sensitivity × (1 - destination_trust)
    +
    linkage_risk × purpose_scope
```

The result is capped at `1.0`.

Field decisions then resolve explicit policy rules before falling back to the prototype's default behaviour.

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

When no explicit policy action exists for a sufficiently high-risk field, the current engine applies a zero-trust fallback and blocks the value.

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
  "offline_first": true
}
```

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

Response fields include:

```text
metadata
  -> destination
  -> purpose
  -> risk_assessment

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

It uses a locally running Ollama model to propose structured field-level actions.

## `POST /save-policy`

The endpoint writes reviewed rules into:

```text
src/policies.yaml
```

and reloads the engine.

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
|   +-- audit.jsonl
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
|   +-- main.py
|   +-- policies.yaml
|   +-- test_boundary.py
|
+-- tests/
|   +-- test_boundary.py
|
+-- dump_project.py
+-- setup.ps1
```

### Core files

| File                                                 | Purpose                                                   |
| ---------------------------------------------------- | --------------------------------------------------------- |
| `src/main.py`                                        | Core `CoreEngine` implementation                          |
| `src/config.py`                                      | Paths, trust baselines, purpose scopes, quasi-identifiers |
| `src/policies.yaml`                                  | Destination/purpose policy matrix                         |
| `src/api.py`                                         | FastAPI service                                           |
| `src/client.py`                                      | Python API demonstration client                           |
| `tests/test_boundary.py`                             | Core automated tests                                      |
| `data/input/fintech_support_ticket.json`             | Synthetic input fixture                                   |
| `data/output/`                                       | Example transformed outputs                               |
| `logs/audit.jsonl`                                   | Decision audit records                                    |
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

The current test suite covers three core behaviours:

### Composite linkage

Checks that multiple configured quasi-identifiers produce the expected prototype linkage-risk level.

### Semantic detection

Checks that:

```text
Patient requires treatment for high blood pressure.
```

is classified as:

```text
medical_context
```

### Differential outputs

Checks that the same data receives different treatment for:

```text
internal_fraud_system
third_party_llm
```

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

---

# Security considerations

Boundary is a data-processing component and should be treated accordingly.

For the current prototype:

* do not commit real personal data
* treat input/output files as potentially sensitive
* review audit logs before publishing them
* do not expose the API directly to an untrusted network
* add authentication and authorization before any internet-facing deployment
* tighten CORS for non-demo deployments
* use proper secret management for production systems
* protect or replace local audit storage for production use

The current FastAPI application allows all CORS origins because the bundled Flutter interface is designed for local/demo communication.

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

Sensitive-data detection is dependent on Presidio, static mappings, and the semantic embedding heuristic. False positives and false negatives are possible.

### Linkage-risk limitations

The current linkage score is based only on the count of configured quasi-identifiers present in the record.

It does not:

* query a population reference dataset
* calculate actual uniqueness
* implement formal k-anonymity
* guarantee resistance to re-identification

### Semantic limitations

The semantic classifier uses a compact embedding model and manually selected anchor phrases. It is not trained specifically for every domain.

### Policy limitations

The YAML grammar and transformation functions are intentionally small.

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

The repository currently does **not** contain:

* pinned Python dependency versions
* a Python lockfile
* Dockerfile
* Docker Compose configuration
* CI workflow defining a clean reference environment

Therefore the current project should be considered **source-reproducible with manual environment setup**, not fully environment-pinned or container-reproducible.

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

At the time this README was prepared, the repository did **not** contain a root `LICENSE` file.

Public visibility of a GitHub repository does not by itself grant permission to copy, modify, or redistribute its original code.

If this repository is intended to be released under an open-source license, add the chosen license at the repository root.

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
