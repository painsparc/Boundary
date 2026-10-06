# Boundary — Reproducible Setup & Verification

## Scope

This document covers the Python backend and its tests/API. The Flutter presentation layer and the optional local-Ollama policy-generation path are documented separately below.

The repository currently expects:
- Python 3.10+ in its README.
- A spaCy English model (`en_core_web_lg`).
- A Sentence Transformers model (`all-MiniLM-L6-v2`), downloaded on first engine startup.
- Ollama + `llama3.2` only for `/generate-policy`.

For reproducibility, use **Python 3.11.x**. The pinned dependency set is in `requirements.txt`.

## 1. Fresh setup — Windows PowerShell

```powershell
git clone https://github.com/painsparc/Boundary.git
cd Boundary

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m spacy download en_core_web_lg
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 2. Fresh setup — macOS/Linux

```bash
git clone https://github.com/painsparc/Boundary.git
cd Boundary

python3.11 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m spacy download en_core_web_lg
```

## 3. First model download

Boundary creates a `SentenceTransformer("all-MiniLM-L6-v2")` during `CoreEngine` initialization. The first run therefore downloads the model from Hugging Face and caches it locally. Later runs use the local cache.

A network connection is required for the first model download unless the model is pre-cached.

## 4. Verify imports before starting the service

```bash
python -c "import fastapi, uvicorn, pydantic, yaml, requests, numpy, presidio_analyzer, sentence_transformers, spacy, ollama; print('Python dependencies: OK')"
python -m spacy validate
python -c "import spacy; print('spaCy:', spacy.__version__); print('en_core_web_lg:', spacy.load('en_core_web_lg').meta['version'])"
```

## 5. Run the automated tests

From the repository root:

```bash
pytest -q
```

Expected result for the current repository tests: all three tests pass:
1. composite linkage risk,
2. semantic medical-context detection,
3. differential fraud-vs-LLM output.

The first test run may take longer because the semantic model must be downloaded and loaded.

## 6. Start the API

From the repository root:

```bash
python -m uvicorn src.api:app --host 127.0.0.1 --port 8000
```

The API should be available at:

- `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{
  "status": "ok",
  "offline_first": true
}
```

## 7. Test the core `/protect` workflow

PowerShell:

```powershell
$body = @{
  data = @{
    name = "Test User"
    age = 43
    city = "Pune"
    occupation = "Doctor"
    bank_account = "12345"
  }
  destination = "third_party_llm"
  purpose = "customer_support"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/protect" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

The response should contain:
- `metadata`
- `risk_assessment`
- `explanations`
- transformed `data`

For the repository's current policy, `bank_account` is blocked for `third_party_llm/customer_support`.

## 8. Run the bundled Python client

With the API running:

```bash
python src/client.py
```

It calls `/protect` against `127.0.0.1:8000`.

## 9. Optional: local AI policy generation

The core `/protect` workflow does **not** require Ollama.

To use `/generate-policy`:

1. Install Ollama.
2. Start the Ollama service.
3. Pull the model:

```bash
ollama pull llama3.2
```

4. Confirm the model is available:

```bash
ollama list
```

5. Start Boundary normally.

The API uses the Ollama Python client and requests model `llama3.2`.

## 10. Flutter presentation layer

The Flutter app lives in:

```text
presentation layer/boundary_frontend/
```

Requirements:
- Flutter/Dart installation compatible with the project's Dart SDK constraint (`>=3.0.0 <4.0.0`).
- Backend running at `http://127.0.0.1:8000`.

Run:

```bash
cd "presentation layer/boundary_frontend"
flutter pub get
flutter run
```

The UI has:
- Intercept mode: submit data, choose destination/purpose, inspect transformation and explanations.
- Setup mode: generate an Ollama policy proposal, review/edit it, save it, and reload the engine.

## 11. Important reproducibility notes

### Python version

Although the original README says Python 3.10+, this reproducibility target uses Python 3.11.x because the project combines Presidio, spaCy, Sentence Transformers and PyTorch. This reduces cross-version packaging risk.

### Models are not ordinary pip dependencies

Two model assets are runtime requirements:

- `en_core_web_lg` for Presidio/spaCy.
- `all-MiniLM-L6-v2` for semantic detection.

They therefore must be downloaded/cached separately.

### Ollama is optional

Do not require Ollama just to run the Boundary protection engine. It is only required for `/generate-policy`.

### Synthetic data only

The repository uses synthetic demonstration data. Do not substitute real personal/financial data during setup verification.

## 12. Acceptance checklist

A clean setup is considered verified only when all of these are true:

- [ ] Python 3.11 environment created.
- [ ] `pip install -r requirements.txt` succeeds.
- [ ] `en_core_web_lg` is installed.
- [ ] `all-MiniLM-L6-v2` downloads/loads.
- [ ] `pytest -q` passes.
- [ ] `/health` returns `status=ok`.
- [ ] `/protect` returns transformed data and explanations.
- [ ] `src/client.py` succeeds.
- [ ] `logs/audit.jsonl` receives an audit record.
- [ ] Optional Ollama path works if policy generation is required.
- [ ] Flutter app connects if the presentation layer is part of the acceptance test.

## 13. Known repository issues addressed by this reproducibility pass

1. No pinned Python dependency manifest → added `requirements.txt`.
2. Setup script did not install dependencies → replace it with the reproducible setup procedure in this document.
3. Model dependencies were implicit → explicitly documented `en_core_web_lg` and `all-MiniLM-L6-v2`.
4. Ollama dependency was mixed into the overall mental setup → explicitly separated as optional for `/generate-policy`.
5. Clean API startup is specified with an explicit host/port command.
6. Verification now includes tests, health endpoint, protection endpoint, client, and audit logging.

## 14. Current verification limitation

This deliverable was prepared from the live GitHub source tree and dependency metadata, but the execution environment used for this pass could not establish outbound access to GitHub/PyPI. Therefore, a successful `pip install` and test run on a genuinely clean internet-connected machine still needs to be recorded as the final empirical verification step.

Do not label the repository "fully fresh-machine verified" until that final run succeeds.

## Runtime configuration (environment variables)

| Variable | Purpose |
| --- | --- |
| `BOUNDARY_ADMIN_KEY` | If set, `/save-policy` and `/generate-policy` require this value in the `X-API-Key` header. If unset, they accept loopback clients only. |
| `BOUNDARY_CORS_ORIGINS` | Comma-separated extra allowed origins. `localhost` / `127.0.0.1` origins are always allowed. |
| `BOUNDARY_AUDIT_LOG` | Audit log path (default `logs/audit.jsonl`, git-ignored). |
| `BOUNDARY_POLICY_FILE` | Policy file path (default `src/policies.yaml`). |
| `BOUNDARY_DISABLE_EMBEDDINGS=1` | Skip the MiniLM model and use the keyword lexicon only (also the automatic fallback when the model cannot be downloaded). |

The Flutter app reads `--dart-define=BOUNDARY_API_URL=...` and `--dart-define=BOUNDARY_ADMIN_KEY=...`.

After editing `src/policies.yaml`, run `python src/generate_examples.py` to refresh `data/output/`.

