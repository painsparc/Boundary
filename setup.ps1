# Boundary reproducible setup script
$ErrorActionPreference = "Stop"

Write-Host "=== Boundary setup ===" -ForegroundColor Cyan

$python = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "Python launcher 'py' was not found. Install Python 3.11 first."
}

& py -3.11 --version
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11 is required for the reproducibility target."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv..." -ForegroundColor Yellow
    & py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Python virtual environment."
    }
}

$venvPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"

Write-Host "Upgrading pip..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}

Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency installation failed."
}

Write-Host "Installing spaCy English model..." -ForegroundColor Yellow
& $venvPython -m spacy download en_core_web_lg
if ($LASTEXITCODE -ne 0) {
    throw "spaCy English model installation failed."
}

Write-Host "Running dependency smoke check..." -ForegroundColor Yellow
& $venvPython -c "import fastapi, uvicorn, pydantic, yaml, requests, numpy, presidio_analyzer, sentence_transformers, spacy, ollama; print('Dependencies OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Dependency smoke check failed."
}

Write-Host "Running spaCy validation..." -ForegroundColor Yellow
& $venvPython -m spacy validate
if ($LASTEXITCODE -ne 0) {
    throw "spaCy validation failed."
}

Write-Host "Running tests..." -ForegroundColor Yellow
& $venvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed. Boundary setup is not complete."
}

Write-Host ""
Write-Host "Setup complete. All verification checks passed." -ForegroundColor Green
Write-Host ""
Write-Host "Start API with:" -ForegroundColor Cyan
Write-Host ".\.venv\Scripts\python.exe -m uvicorn src.api:app --host 127.0.0.1 --port 8000"