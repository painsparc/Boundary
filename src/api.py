from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import yaml
from pathlib import Path
import ollama

# Add src to path to import main
sys.path.append(str(Path(__file__).resolve().parent))
from main import CoreEngine
import config

app = FastAPI(title="Boundary Engine API")

# Enable CORS for Flutter Web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = None

# --- Data Models ---
class ProtectRequest(BaseModel):
    data: dict
    destination: str
    purpose: str

class PolicyGenerationRequest(BaseModel):
    app_context: str
    destination: str
    purpose: str
    sample_fields: list[str]

class FieldRule(BaseModel):
    field: str
    action: str  # ALLOW, REDACT, BLOCK, MASK, GENERALIZE, REMOVE
    reason: str

class PolicyProposal(BaseModel):
    rules: list[FieldRule]

class SavePolicyRequest(BaseModel):
    destination: str
    purpose: str
    rules: dict

# --- Startup ---
@app.on_event("startup")
def startup_event():
    global engine
    engine = CoreEngine()

@app.get("/health")
def health():
    return {"status": "ok", "offline_first": True}

# --- 1. AI Configuration Phase (HIL Draft) ---
@app.post("/generate-policy")
def generate_policy(req: PolicyGenerationRequest):
    prompt = f"""
    You are an expert data privacy architect.
    App Context: {req.app_context}
    Destination: {req.destination}
    Purpose: {req.purpose}
    Data Fields: {', '.join(req.sample_fields)}

    For each data field, decide the most mathematically sound privacy action from this strict list: ALLOW, REDACT, BLOCK, MASK, GENERALIZE, REMOVE.
    Prioritize data utility for the stated purpose, but strictly minimize sensitive data.
    """
    try:
        print(f"\n[{req.destination} | {req.purpose}] AI Policy Generation Started...\n")
        
        # Ask Ollama and enable streaming
        stream = ollama.chat(
            model='llama3.2', # Change this if you pulled a different model
            messages=[{'role': 'user', 'content': prompt}],
            format=PolicyProposal.model_json_schema(),
            options={'temperature': 0.0},
            stream=True # This tells Ollama to stream chunks
        )
        
        # Accumulate the response while printing it live to the terminal
        full_response = ""
        for chunk in stream:
            content = chunk['message']['content']
            print(content, end='', flush=True) # Print live to terminal
            full_response += content
            
        print("\n\n[SYSTEM] Policy Generation Complete. Sending to UI.\n")

        # Validate and return the structured JSON
        # Note: Using .model_dump() instead of .dict() for newer Pydantic versions
        return PolicyProposal.model_validate_json(full_response).model_dump()
    except Exception as e:
        print(f"\n[ERROR] Generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 2. HIL Confirmation Phase (Lock it in) ---
@app.post("/save-policy")
def save_policy(req: SavePolicyRequest):
    try:
        # Load existing YAML
        policies = {}
        if config.POLICY_FILE.exists():
            with open(config.POLICY_FILE, 'r') as f:
                policies = yaml.safe_load(f) or {}

        # Update specific destination and purpose
        if req.destination not in policies:
            policies[req.destination] = {}
        policies[req.destination][req.purpose] = req.rules

        # Save back to YAML
        with open(config.POLICY_FILE, 'w') as f:
            yaml.dump(policies, f, default_flow_style=False)

        # Hot-reload the engine with the new rules
        global engine
        engine = CoreEngine()
        return {"status": "success", "message": "Policy locked and engine reloaded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 3. Runtime Phase (Lightning Fast Intercept) ---
@app.post("/protect")
def protect(req: ProtectRequest):
    try:
        return engine.process_record(req.data, req.destination, req.purpose)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))