# Boundary Reproducibility Verification Record

Repository:
https://github.com/painsparc/Boundary

Target:
Python 3.11.x

## Static source audit

- [x] README reviewed
- [x] `src/main.py` reviewed
- [x] `src/api.py` reviewed
- [x] `src/config.py` reviewed
- [x] `src/policies.yaml` reviewed
- [x] `src/client.py` reviewed
- [x] `tests/test_boundary.py` reviewed
- [x] Flutter `pubspec.yaml` reviewed
- [x] existing `setup.ps1` reviewed

## Issues identified

- [x] No pinned Python requirements file
- [x] No Python lockfile
- [x] Existing setup.ps1 is only a workspace scaffold
- [x] spaCy model requirement is separate from pip packages
- [x] Sentence Transformer model download is implicit
- [x] Ollama is required only for `/generate-policy`
- [x] No clean reference environment/CI workflow in repository

## Runtime verification

Verified (Ubuntu 24 sandbox, Python 3.12.3, venv; 2026-10-05):

- [x] `pytest -q` passes (about 70 tests) with presidio-analyzer, spaCy `en_core_web_lg`, FastAPI, PyYAML, numpy, httpx
- [x] `uvicorn src.api:app` starts from the repository root; `/health`, `/routes`, `/protect` respond
- [x] `src/client.py` runs against the live server
- [x] Unsafe `/save-policy` returns 422 and leaves `policies.yaml` unchanged; foreign-origin CORS preflight gets no allow-origin header
- [x] Pinned versions resolve under `pip install --dry-run -r requirements.txt` (Python 3.12)

Not verified (blocked or unavailable in the sandbox):

- [ ] Full real `pip install -r requirements.txt` including torch / sentence-transformers
- [ ] MiniLM model download (Hugging Face unreachable); the suite ran in lexicon-only mode (`/health` reports `semantic_backend`)
- [ ] Python 3.11 specifically
- [ ] `setup.ps1` on Windows
- [ ] Flutter build and widget test (no Flutter SDK; Dart edits were only bracket-checked)
- [ ] Ollama `/generate-policy` against a real model (covered by a mocked-client test only)

## Final acceptance

Run `setup.ps1` on a clean Windows machine, or follow `SETUP.md` on a clean Windows/macOS/Linux machine.

Record:
- OS
- Python version
- pip version
- install result
- test result
- API health result
- `/protect` result
- model download result
- optional Ollama result
