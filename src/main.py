import os
import sys
import json
import yaml
import time
import uuid
import logging
from pathlib import Path
from datetime import datetime
import numpy as np

# Suppress HuggingFace/Presidio warnings for a clean console
import warnings
warnings.filterwarnings("ignore")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from presidio_analyzer import AnalyzerEngine
from sentence_transformers import SentenceTransformer, util
import config

# ==========================================
# 1. LOGGING & UTILS
# ==========================================
def setup_logger():
    logger = logging.getLogger("BoundaryEngine")
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(message)s')
    ch.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(ch)
    return logger

logger = setup_logger()

# ==========================================
# 2. CORE ENGINE
# ==========================================
class CoreEngine:
    def __init__(self):
        logger.info("[SYSTEM] Initializing Boundary Engine (Zero-Trust Mode)...")
        
        with open(config.POLICY_FILE, 'r') as f:
            self.policies = yaml.safe_load(f)
            
        logger.info("[SYSTEM] Loading Presidio Analyzer...")
        self.analyzer = AnalyzerEngine()
        
        logger.info("[SYSTEM] Loading Semantic Engine (all-MiniLM-L6-v2)...")
        self.semantic_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        self.anchor_texts = {
            "medical_context": ["patient diagnosed", "hospital appointment", "cardiology", "medical treatment", "insurance medical claim", "chest pain", "doctor"],
            "financial_context": ["bank account", "financial hardship", "loan information", "payment details", "credit card debt"]
        }
        self.anchor_embeddings = {
            category: self.semantic_model.encode(texts, convert_to_tensor=True)
            for category, texts in self.anchor_texts.items()
        }
        self.semantic_threshold = 0.45
        logger.info("[SYSTEM] Engine Ready.\n")

    def analyze_linkage_risk(self, data: dict) -> tuple[float, list]:
        present_qi = [k for k in data.keys() if k in config.QUASI_IDENTIFIERS]
        count = len(present_qi)
        if count == 0: risk = 0.0
        elif count == 1: risk = 0.2
        elif count == 2: risk = 0.5
        else: risk = 0.85
        return risk, present_qi

    def analyze_semantics(self, text: str) -> list[str]:
        if not text or not isinstance(text, str): return []
        text_emb = self.semantic_model.encode(text, convert_to_tensor=True)
        detected_categories = []
        for category, anchors_emb in self.anchor_embeddings.items():
            cosine_scores = util.cos_sim(text_emb, anchors_emb)[0]
            if torch_max_float(cosine_scores) >= self.semantic_threshold:
                detected_categories.append(category)
        return detected_categories

    def transform_value(self, value, action: str, field: str) -> any:
        if action == "ALLOW": return value
        if action == "REDACT": return "[REDACTED]"
        if action == "BLOCK": return "[BLOCKED]"
        if action == "REMOVE": return None
        if action == "MASK":
            val_str = str(value)
            if "@" in val_str:
                return val_str[0] + "***@" + val_str.split("@")[-1]
            return val_str[0] + "***"
        if action == "GENERALIZE":
            if field == "age":
                try:
                    age = int(value)
                    return f"{age//10 * 10}-{age//10 * 10 + 9}"
                except: return "Age Generalized"
            if field == "city":
                return "Regional Area"
            return "Generalized"
        return value

    def process_record(self, data: dict, destination: str, purpose: str) -> dict:
        audit_id = str(uuid.uuid4())
        transformed_data = {}
        explanations = []
        audit_logs = []
        
        dest_trust = config.DESTINATION_TRUST.get(destination, 0.5)
        purp_scope = config.PURPOSE_SCOPE.get(purpose, 1.0)
        linkage_risk, qi_fields = self.analyze_linkage_risk(data)
        
        # Safely fetch policy rules (returns empty dict if combination doesn't exist)
        policy = self.policies.get(destination, {}).get(purpose, {})
        overall_sensitivity_accumulator = 0.0

        for field, value in data.items():
            if value is None:
                continue
                
            field_risk = 0.1
            detection_methods = []
            detected_categories = []
            
            # --- 1. DETECTION LAYER ---
            if isinstance(value, str):
                results = self.analyzer.analyze(text=value, entities=[], language='en')
                if results:
                    field_risk = max(field_risk, 0.8)
                    detected_categories.append(results[0].entity_type)
                    detection_methods.append("presidio_pattern")

            if field == "free_text_note" and isinstance(value, str):
                sem_cats = self.analyze_semantics(value)
                if sem_cats:
                    field_risk = max(field_risk, 0.9)
                    detected_categories.extend(sem_cats)
                    detection_methods.append("semantic_embedding")
                    
            if field in ["government_id", "bank_account"]:
                field_risk = 0.95
                detected_categories.append(field)
                detection_methods.append("static_mapping")
                
            if field in qi_fields:
                field_risk = max(field_risk, linkage_risk)
                detected_categories.append("quasi_identifier")
                detection_methods.append("heuristic_linkage")

            overall_sensitivity_accumulator = max(overall_sensitivity_accumulator, field_risk)

            # --- 2. ZERO-TRUST DECISION LAYER (THE FIX) ---
            policy_action = None
            reason = ""
            
            # A. Check if explicitly addressed in YAML policy categories
            for cat in detected_categories:
                norm_cat = cat.lower().replace("_address", "")
                if norm_cat in policy:
                    policy_action = policy[norm_cat]
                    reason = f"Explicit policy enforcement on category: {norm_cat}"
                    break
            
            # B. Fallback to direct field name in YAML
            if not policy_action and field in policy:
                policy_action = policy[field]
                reason = f"Explicit policy enforcement on field: {field}"

            # C. The Zero-Trust Logic
            if policy_action:
                action = policy_action
            elif field_risk >= 0.5:
                # High risk detected, but NO policy exists for this specific destination/purpose
                action = "BLOCK"
                reason = "ZERO-TRUST FALLBACK: Sensitive data detected with no explicit ALLOW policy."
            else:
                # Low risk data (like transaction_id) with no policy
                action = "ALLOW"
                reason = "Low risk data; no blocking policy detected."
                
            if action == "GENERALIZE" and field in qi_fields:
                reason = f"Generalization applied due to composite linkage risk of {linkage_risk} from fields: {qi_fields}"
                
            # --- 3. TRANSFORMATION LAYER ---
            new_value = self.transform_value(value, action, field)
            if action != "REMOVE":
                transformed_data[field] = new_value
                
            if action != "ALLOW" or field_risk > 0.5:
                expl = {
                    "field": field,
                    "categories": detected_categories,
                    "action": action,
                    "risk": round(field_risk, 2),
                    "reason": reason,
                    "detection_method": "+".join(detection_methods) if detection_methods else "none"
                }
                explanations.append(expl)
                
                audit_record = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "audit_id": audit_id,
                    "destination": destination,
                    "purpose": purpose,
                    **expl
                }
                audit_logs.append(audit_record)

        overall_risk = (overall_sensitivity_accumulator * (1 - dest_trust)) + (linkage_risk * purp_scope)
        overall_risk = min(round(overall_risk, 2), 1.0)

        with open(config.LOGS_DIR / "audit.jsonl", "a") as f:
            for log in audit_logs:
                f.write(json.dumps(log) + "\n")

        return {
            "metadata": {
                "audit_id": audit_id,
                "destination": destination,
                "purpose": purpose,
                "risk_assessment": {
                    "overall_risk": overall_risk,
                    "max_sensitivity": round(overall_sensitivity_accumulator, 2),
                    "linkage_risk": linkage_risk,
                    "destination_trust": dest_trust,
                    "purpose_scope": purp_scope
                }
            },
            "explanations": explanations,
            "data": transformed_data
        }

def torch_max_float(tensor) -> float:
    return tensor.max().item()

# (Demo functions omitted for brevity since you are running via API now)