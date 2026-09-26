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

The current tool environment could not reach GitHub/PyPI, so these cannot honestly be marked passed here:

- [ ] Fresh `pip install -r requirements.txt`
- [ ] Fresh model download
- [ ] `pytest -q`
- [ ] `/health`
- [ ] `/protect`
- [ ] `src/client.py`
- [ ] Flutter runtime
- [ ] Ollama `/generate-policy`

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
