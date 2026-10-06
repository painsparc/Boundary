"""Contextual (semantic) detection: embedding similarity plus a deterministic lexicon.

The lexicon always runs, so detection does not silently disappear when the
embedding model cannot be downloaded (offline / air-gapped installs).
"""
import logging
import os
import re

import config

logger = logging.getLogger("BoundaryEngine")

ANCHORS = {
    "medical_context": ["patient diagnosed", "hospital appointment", "cardiology", "medical treatment",
                        "insurance medical claim", "chest pain", "doctor"],
    "financial_context": ["bank account", "financial hardship", "loan information", "payment details",
                          "credit card debt"],
}
LEXICON = {
    "medical_context": ["patient", "diagnos", "hospital", "cardiolog", "medical", "treatment", "doctor",
                        "clinic", "prescription", "symptom", "surgery", "medication", "therapy", "disease",
                        "diabetes", "blood pressure", "chest pain", "insurance claim"],
    "financial_context": ["bank account", "financial hardship", "loan", "credit card", "debt", "mortgage",
                          "bankruptcy", "payment details", "overdue", "salary"],
}


class SemanticClassifier:
    def __init__(self, model_name="all-MiniLM-L6-v2", use_embeddings=True):
        self._model = None
        self.backend = "lexicon"
        self._patterns = {c: re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + ")", re.I)
                          for c, kws in LEXICON.items()}
        if use_embeddings and os.environ.get("BOUNDARY_DISABLE_EMBEDDINGS") != "1":
            try:
                from sentence_transformers import SentenceTransformer, util
                self._model, self._util = SentenceTransformer(model_name), util
                self._anchors = {c: self._model.encode(t, convert_to_tensor=True) for c, t in ANCHORS.items()}
                self.backend = "embedding+lexicon"
            except Exception as exc:  # offline, missing package, corrupt cache ...
                self._model = None
                logger.warning("[SYSTEM] Embedding model unavailable (%s: %s); using lexicon-only semantic detection.",
                               type(exc).__name__, str(exc)[:120])

    def classify(self, text) -> list:
        if not text or not isinstance(text, str):
            return []
        text = text[:config.MAX_ANALYZE_CHARS]
        found = {c for c, p in self._patterns.items() if p.search(text)}
        if self._model is not None:
            emb = self._model.encode(text, convert_to_tensor=True)
            for cat, anchors in self._anchors.items():
                if float(self._util.cos_sim(emb, anchors)[0].max().item()) >= config.SEMANTIC_THRESHOLD:
                    found.add(cat)
        return sorted(found)
