"""Policy loading, validation, security invariants and atomic persistence."""
import hashlib
import os
import re
import tempfile
import threading
from pathlib import Path

import yaml

import config
from fields import canonical_field

# Ordered least -> most restrictive. When several rules match one value, the strictest wins.
VALID_ACTIONS = ("ALLOW", "MASK", "GENERALIZE", "REDACT", "BLOCK", "REMOVE")
STRICTNESS = {a: i for i, a in enumerate(VALID_ACTIONS)}
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_RULES_PER_BLOCK = 200


class PolicyError(ValueError):
    """Raised when a policy is malformed or breaks a security invariant."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__("; ".join(self.violations))


def validate_block(destination, purpose, rules):
    """Return (normalised_rules, violations) for one destination/purpose block."""
    where = f"{destination}/{purpose}"
    violations, out = [], {}
    if destination not in config.DESTINATION_TRUST:
        violations.append(f"{where}: unknown destination '{destination}' (supported: {sorted(config.DESTINATION_TRUST)})")
    if purpose not in config.PURPOSE_SCOPE:
        violations.append(f"{where}: unknown purpose '{purpose}' (supported: {sorted(config.PURPOSE_SCOPE)})")
    if not isinstance(rules, dict):
        return {}, violations + [f"{where}: rules must be a mapping of field/category -> ACTION"]
    if len(rules) > MAX_RULES_PER_BLOCK:
        violations.append(f"{where}: too many rules ({len(rules)} > {MAX_RULES_PER_BLOCK})")
    trust = config.DESTINATION_TRUST.get(destination)
    for raw_key, raw_action in rules.items():
        key = canonical_field(raw_key)
        if not _KEY_RE.match(key):
            violations.append(f"{where}: invalid rule key {raw_key!r}")
            continue
        action = raw_action.strip().upper() if isinstance(raw_action, str) else None
        if action not in STRICTNESS:
            violations.append(f"{where}: invalid action {raw_action!r} for '{key}' (allowed: {list(VALID_ACTIONS)})")
            continue
        if key in out and out[key] != action:
            violations.append(f"{where}: '{raw_key}' collides with another key resolving to '{key}' with a different action")
            continue
        if action == "ALLOW" and key in config.NO_ALLOW_CATEGORIES and trust is not None \
                and trust < config.SENSITIVE_ALLOW_MIN_TRUST:
            violations.append(
                f"{where}: '{key}' cannot be ALLOW for a destination with trust {trust:.2f} "
                f"(< {config.SENSITIVE_ALLOW_MIN_TRUST:.2f}); use MASK, REDACT, BLOCK or REMOVE")
            continue
        out[key] = action
    return out, violations


def normalize_policies(raw):
    """Validate and normalise a whole policy document. Raises PolicyError."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PolicyError(["policy file must be a mapping of destination -> purpose -> rules"])
    out, violations = {}, []
    for dest, purposes in raw.items():
        if not isinstance(purposes, dict):
            violations.append(f"{dest}: must map purposes to rule blocks")
            continue
        for purpose, rules in purposes.items():
            block, v = validate_block(dest, purpose, rules)
            violations += v
            out.setdefault(dest, {})[purpose] = block
    if violations:
        raise PolicyError(violations)
    return out


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


class PolicyStore:
    """Single source of truth for policies; every decision can cite `.hash`."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.policies, self.hash = {}, ""
        self.reload()

    def reload(self):
        with self._lock:
            data = self.path.read_bytes() if self.path.exists() else b""
            policies = normalize_policies(yaml.safe_load(data) if data else {})
            self.policies, self.hash = policies, file_hash(data)
            return self.hash

    def routes(self):
        with self._lock:
            return {d: sorted(p for p, r in ps.items() if r) for d, ps in self.policies.items()}

    def save_block(self, destination, purpose, rules, replace=False):
        """Validate, then atomically persist one block and reload. Never writes an invalid file."""
        with self._lock:
            block, violations = validate_block(destination, purpose, rules)
            if violations:
                raise PolicyError(violations)
            previous = self.hash
            merged = {d: {p: dict(r) for p, r in ps.items()} for d, ps in self.policies.items()}
            current = merged.setdefault(destination, {}).get(purpose, {})
            merged[destination][purpose] = block if replace else {**current, **block}
            normalize_policies(merged)  # re-validate the complete document
            payload = yaml.safe_dump(merged, default_flow_style=False, sort_keys=True).encode()
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".policies-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self.reload()
            return {"previous_hash": previous, "policy_hash": self.hash,
                    "rules_in_block": len(self.policies[destination][purpose]), "mode": "replace" if replace else "merge"}
