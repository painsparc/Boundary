"""Boundary core engine: detect -> assess -> policy -> transform -> re-assess -> explain -> audit."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from presidio_analyzer import AnalyzerEngine

import config
from fields import canonical_field
from policy import STRICTNESS, PolicyStore
from semantic import SemanticClassifier
from validators import verhoeff_valid


# ==========================================
# 1. LOGGING, ERRORS, SMALL HELPERS
# ==========================================
def setup_logger():
    logger = logging.getLogger("BoundaryEngine")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)
    return logger


logger = setup_logger()


class BoundaryRequestError(ValueError):
    """Base class for errors caused by the caller's request (HTTP 4xx)."""


class UnknownRouteError(BoundaryRequestError):
    """Unknown destination or purpose."""


class PolicyNotFoundError(BoundaryRequestError):
    """Known destination and purpose, but no policy block configured for the pair."""


class InputLimitError(BoundaryRequestError):
    """Payload too deep / too large / not an object."""


_REMOVED = object()
_GOV_RES = {n: re.compile(p) for n, p in config.GOV_ID_VALUE_PATTERNS.items()}


def linkage_from_count(count: int) -> float:
    return config.LINKAGE_TABLE.get(count, config.LINKAGE_MAX) if count < 3 else config.LINKAGE_MAX


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fmt_path(path: tuple) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


def looks_like_government_id(text: str) -> bool:
    t = text.strip()
    for name, rx in _GOV_RES.items():
        if rx.fullmatch(t):
            if name == "in_aadhaar" and not verhoeff_valid(re.sub(r"[ -]", "", t)):
                continue
            return True
    return False


def mask_value(value) -> str:
    s = str(value)
    if not s:
        return "***"
    if "@" in s[1:]:
        local, _, domain = s.rpartition("@")
        return (local[:1] or "*") + "***@" + domain
    digits = sum(c.isdigit() for c in s)
    if digits >= 8 and digits / max(len(re.sub(r"[\s-]", "", s)), 1) >= 0.6:
        seen, out = 0, []
        for ch in s:
            if ch.isdigit():
                seen += 1
                out.append(ch if seen > digits - 4 else "*")
            else:
                out.append(ch)
        return "".join(out)
    return s[0] + "***"


def generalize_value(value, canon: str):
    """Return a coarser value, or None when this field/value cannot be generalised safely."""
    if canon == "age" and not isinstance(value, bool):
        try:
            age = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None
        if 0 <= age <= 130:
            lo = age // 10 * 10
            return f"{lo}-{lo + 9}"
        return None
    if canon in ("city", "region"):
        return "Regional Area"
    if canon == "postal_code":
        s = str(value).strip()
        return s[:3] + "***" if len(s) >= 4 else None
    return None


def apply_action(value, action: Any, canon: str):
    """Return (new_value, effective_action, note). Unknown actions fail CLOSED."""
    act = action.strip().upper() if isinstance(action, str) else ""
    if act == "ALLOW":
        return value, "ALLOW", None
    if act == "MASK":
        return mask_value(value), "MASK", None
    if act == "GENERALIZE":
        g = generalize_value(value, canon)
        if g is None:
            return "[REDACTED]", "REDACT", "GENERALIZE not supported for this field/value; REDACT applied"
        return g, "GENERALIZE", None
    if act == "REDACT":
        return "[REDACTED]", "REDACT", None
    if act == "REMOVE":
        return _REMOVED, "REMOVE", None
    if act == "BLOCK":
        return "[BLOCKED]", "BLOCK", None
    return "[BLOCKED]", "BLOCK", f"unknown action {action!r}; BLOCK applied (fail-closed)"


@dataclass
class Leaf:
    path: tuple
    key: str
    value: Any
    canon: str = ""
    is_qi: bool = False
    intrinsic: float = 0.1          # detection-based risk, excluding the linkage heuristic
    risk: float = 0.1               # intrinsic, raised by linkage for quasi-identifiers
    categories: list = field(default_factory=list)
    methods: list = field(default_factory=list)
    action: str = "ALLOW"           # decided action
    effective: str = "ALLOW"        # action actually applied
    new_value: Any = None
    reason: str = ""
    policy_rule: bool = False       # an explicit policy rule decided this
    fallback: bool = False          # zero-trust fallback decided this
    escalated: bool = False


# ==========================================
# 2. CORE ENGINE
# ==========================================
class CoreEngine:
    def __init__(self, policy_path=None, audit_path=None, audit_enabled=True, use_embeddings=True):
        logger.info("[SYSTEM] Initializing Boundary Engine (Zero-Trust Mode)...")
        self.policy_store = PolicyStore(policy_path or config.POLICY_FILE)
        self.audit_path = Path(audit_path or config.AUDIT_FILE)
        self.audit_enabled = audit_enabled
        self._audit_lock = threading.Lock()

        logger.info("[SYSTEM] Loading Presidio Analyzer...")
        self.analyzer = AnalyzerEngine()
        logger.info("[SYSTEM] Loading semantic detection...")
        self.semantic = SemanticClassifier(use_embeddings=use_embeddings)
        logger.info(f"[SYSTEM] Engine Ready (policy {self.policy_store.hash}, semantic={self.semantic.backend}).\n")

    # ---- policy access -------------------------------------------------
    @property
    def policies(self):
        return self.policy_store.policies

    @property
    def semantic_backend(self):
        return self.semantic.backend

    def reload_policies(self):
        return self.policy_store.reload()

    # ---- detection helpers --------------------------------------------
    def analyze_linkage_risk(self, data: dict):
        """Linkage heuristic over distinct, non-empty quasi-identifiers (case/alias-insensitive, nested-aware)."""
        present = set()
        for leaf in self._collect(data):
            c = canonical_field(leaf.key)
            if c in config.QUASI_IDENTIFIERS and str(leaf.value).strip() != "":
                present.add(c)
        return linkage_from_count(len(present)), sorted(present)

    def analyze_semantics(self, text: str) -> list:
        return self.semantic.classify(text)

    def transform_value(self, value, action: str, field_name: str = ""):
        new, _, _ = apply_action(value, action, canonical_field(field_name))
        return None if new is _REMOVED else new

    def _collect(self, data) -> list:
        if not isinstance(data, dict):
            raise InputLimitError("'data' must be a JSON object")
        leaves: list = []

        def walk(node, path, key):
            if len(path) > config.MAX_DEPTH:
                raise InputLimitError(f"data nested deeper than {config.MAX_DEPTH} levels")
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, path + (k,), str(k))
            elif isinstance(node, (list, tuple)):
                for i, v in enumerate(node):
                    walk(v, path + (i,), key)
            elif node is not None:   # null values are dropped from the payload
                if len(leaves) >= config.MAX_LEAVES:
                    raise InputLimitError(f"data has more than {config.MAX_LEAVES} values")
                leaves.append(Leaf(path=path, key=key, value=node))

        walk(data, (), "")
        return leaves

    def _detect(self, leaf: Leaf):
        leaf.canon = canonical_field(leaf.key)
        risk, cats, methods = 0.1, [], []

        def add(cat, r, method):
            nonlocal risk
            if cat not in cats:
                cats.append(cat)
            if method not in methods:
                methods.append(method)
            risk = max(risk, r)

        if leaf.canon in config.HIGH_RISK_FIELDS:
            add(leaf.canon, config.HIGH_RISK_FIELDS[leaf.canon], "static_mapping")
        elif leaf.canon in config.SENSITIVE_FIELD_RISK:
            add(leaf.canon, config.SENSITIVE_FIELD_RISK[leaf.canon], "field_alias")

        v = leaf.value
        text = v if isinstance(v, str) else (str(v) if _is_number(v) and len(str(v)) >= 7 else None)
        if text is not None and text.strip():
            if looks_like_government_id(text):
                add("government_id", 0.95, "value_pattern")
            results = self.analyzer.analyze(text=text[:config.MAX_ANALYZE_CHARS], language="en",
                                            score_threshold=config.PRESIDIO_MIN_SCORE)
            for r in sorted(results, key=lambda r: -r.score):
                if r.entity_type in config.IGNORED_ENTITIES:
                    continue
                cat = config.ENTITY_CATEGORY.get(r.entity_type, r.entity_type.lower())
                add(cat, config.ENTITY_RISK.get(r.entity_type, config.DEFAULT_ENTITY_RISK), "presidio_pattern")
            if isinstance(v, str) and len(text.split()) >= 3:
                for cat in self.semantic.classify(text):
                    add(cat, 0.9, "semantic_embedding" if "embedding" in self.semantic.backend else "semantic_lexicon")
        leaf.intrinsic = risk
        leaf.categories, leaf.methods = cats, methods

    # ---- the pipeline -------------------------------------------------
    def process_record(self, data: dict, destination: str, purpose: str, *,
                       require_policy: bool = True, audit_id: str | None = None) -> dict:
        if destination not in config.DESTINATION_TRUST:
            raise UnknownRouteError(f"Unknown destination '{destination}'. Supported: {sorted(config.DESTINATION_TRUST)}")
        if purpose not in config.PURPOSE_SCOPE:
            raise UnknownRouteError(f"Unknown purpose '{purpose}'. Supported: {sorted(config.PURPOSE_SCOPE)}")

        store = self.policy_store
        policy = store.policies.get(destination, {}).get(purpose) or {}
        policy_hash = store.hash
        policy_found = bool(policy)
        if not policy_found and require_policy:
            configured = store.routes().get(destination, [])
            raise PolicyNotFoundError(
                f"No policy configured for destination '{destination}' / purpose '{purpose}'. "
                f"Purposes configured for this destination: {configured or 'none'}.")

        audit_id = audit_id or str(uuid.uuid4())
        dest_trust, purp_scope = config.DESTINATION_TRUST[destination], config.PURPOSE_SCOPE[purpose]
        leaves = self._collect(data)
        for leaf in leaves:
            self._detect(leaf)

        # --- linkage on the INPUT -------------------------------------
        qi_present = {l.canon for l in leaves if l.canon in config.QUASI_IDENTIFIERS and str(l.value).strip() != ""}
        linkage_risk = linkage_from_count(len(qi_present))
        qi_list = sorted(qi_present)
        for l in leaves:
            l.is_qi = l.canon in qi_present
            l.risk = l.intrinsic
            if l.is_qi:
                l.categories.append("quasi_identifier")
                l.methods.append("heuristic_linkage")
                l.risk = max(l.intrinsic, linkage_risk)

        # --- policy decision (strictest matching rule wins) ------------
        fallback_count = 0
        for l in leaves:
            keys = [l.canon] + [c for c in l.categories if c != "quasi_identifier" and c != l.canon]
            matches = [(k, policy[k]) for k in keys if k in policy]
            if matches:
                l.action = max((a for _, a in matches), key=lambda a: STRICTNESS[a])
                l.policy_rule = True
                l.reason = ("Explicit policy rule " + ", ".join(f"{k}={a}" for k, a in matches)
                            + ("" if len(matches) == 1 else f" (strictest applied: {l.action})"))
            elif l.risk >= config.ZERO_TRUST_RISK_THRESHOLD:
                l.action, l.fallback = "BLOCK", True
                fallback_count += 1
                reason = "ZERO-TRUST FALLBACK: sensitive data detected with no explicit policy rule"
                l.reason = reason if policy_found else reason + " (no policy block exists for this destination/purpose)"
            else:
                l.action, l.reason = "ALLOW", "Low risk data; no rule needed"
            if l.action == "GENERALIZE" and l.is_qi:
                l.reason = f"Generalization applied due to composite linkage risk of {linkage_risk} from fields: {qi_list}"
            self._apply(l)

        input_risk = min(round(max([l.risk for l in leaves], default=0.0) * (1 - dest_trust)
                               + linkage_risk * purp_scope, 2), 1.0)

        # --- re-assess the FINAL payload and escalate if still too risky ---
        def residual():
            exposed = [l for l in leaves if l.effective in ("ALLOW", "MASK")]
            res_link = linkage_from_count(len({l.canon for l in exposed if l.is_qi}))
            sens = max([l.intrinsic for l in exposed], default=0.0)
            return min(sens * (1 - dest_trust) + res_link * purp_scope, 1.0), res_link

        limit, escalations = config.MAX_RESIDUAL_RISK, 0
        for phase in ("qi_generalize", "sensitive_block", "qi_block"):
            while residual()[0] > limit:
                exposed = [l for l in leaves if l.effective in ("ALLOW", "MASK")]
                if phase == "qi_generalize":
                    cands, new_action = [l for l in exposed if l.is_qi], "GENERALIZE"
                elif phase == "sensitive_block":
                    cands = sorted((l for l in exposed if not l.is_qi and l.intrinsic >= config.ZERO_TRUST_RISK_THRESHOLD),
                                   key=lambda l: -l.intrinsic)
                    new_action = "BLOCK"
                else:
                    cands, new_action = [l for l in exposed if l.is_qi], "BLOCK"
                if not cands:
                    break
                l = cands[0]
                l.reason += f" | ESCALATED to {new_action}: residual risk {round(residual()[0], 2)} exceeded limit {limit}"
                l.action, l.escalated = new_action, True
                self._apply(l)
                escalations += 1
        overall_risk, residual_link = residual()
        overall_risk = round(overall_risk, 2)

        # --- rebuild payload -------------------------------------------
        decided = {l.path: l for l in leaves}

        def rebuild(node, path):
            if isinstance(node, dict):
                out = {}
                for k, v in node.items():
                    p = path + (k,)
                    if isinstance(v, (dict, list, tuple)):
                        out[k] = rebuild(v, p)
                    elif p in decided and decided[p].new_value is not _REMOVED:
                        out[k] = decided[p].new_value
                return out
            out = []
            for i, v in enumerate(node):
                p = path + (i,)
                if isinstance(v, (dict, list, tuple)):
                    out.append(rebuild(v, p))
                elif p in decided and decided[p].new_value is not _REMOVED:
                    out.append(decided[p].new_value)
            return out

        transformed = rebuild(data, ())

        # --- explanations + audit -----------------------------------------
        explanations, audit_rows = [], []
        for l in leaves:
            if l.effective != "ALLOW" or l.risk > 0.5:
                expl = {
                    "field": _fmt_path(l.path), "categories": l.categories, "action": l.effective,
                    "risk": round(l.risk, 2), "reason": l.reason,
                    "detection_method": "+".join(l.methods) if l.methods else "none",
                    "policy_rule": l.policy_rule, "fallback_used": l.fallback, "escalated": l.escalated,
                }
                explanations.append(expl)
                audit_rows.append({"type": "field", "timestamp": self._now(), "audit_id": audit_id,
                                   "destination": destination, "purpose": purpose, "policy_hash": policy_hash, **expl})

        result = {
            "metadata": {
                "audit_id": audit_id, "destination": destination, "purpose": purpose,
                "policy": {"hash": policy_hash, "found": policy_found, "fallback_fields": fallback_count},
                "risk_assessment": {
                    "overall_risk": overall_risk,           # risk of the FINAL payload
                    "input_risk": input_risk,               # risk of the raw input
                    "max_sensitivity": round(max([l.risk for l in leaves], default=0.0), 2),
                    "linkage_risk": linkage_risk,           # raw input
                    "residual_linkage_risk": residual_link,  # final payload
                    "residual_risk_limit": limit,
                    "within_limit": overall_risk <= limit,
                    "escalations": escalations,
                    "destination_trust": dest_trust, "purpose_scope": purp_scope,
                },
            },
            "explanations": explanations,
            "data": transformed,
        }
        audit_rows.insert(0, {"type": "request", "timestamp": self._now(), "audit_id": audit_id,
                              "destination": destination, "purpose": purpose, "policy_hash": policy_hash,
                              "policy_found": policy_found, "fields_evaluated": len(leaves),
                              "fields_changed": sum(1 for l in leaves if l.effective != "ALLOW"),
                              "overall_risk": overall_risk, "input_risk": input_risk, "escalations": escalations})
        self.audit(audit_rows)
        return result

    def _apply(self, leaf: Leaf):
        leaf.new_value, leaf.effective, note = apply_action(leaf.value, leaf.action, leaf.canon)
        if note:
            leaf.reason += f" | {note}"

    # ---- audit ---------------------------------------------------------
    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def audit(self, rows):
        if not self.audit_enabled or not rows:
            return
        with self._audit_lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")

    def audit_event(self, event: dict):
        self.audit([{"type": "event", "timestamp": self._now(), **event}])
