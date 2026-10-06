"""Field-name normalisation shared by the engine and the policy validator."""
import re

import config

_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")
_ALIAS_TO_CANON = {alias: canon for canon, aliases in config.FIELD_ALIASES.items() for alias in aliases}


def normalize_key(name) -> str:
    """accountNumber / Account-Number / ACCOUNT_NUMBER -> account_number."""
    s = str(name).strip()
    s = _CAMEL_1.sub(r"\1_\2", s)
    s = _CAMEL_2.sub(r"\1_\2", s)
    return re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()


def canonical_field(name) -> str:
    """Normalise a key and resolve configured aliases (gov_id -> government_id)."""
    n = normalize_key(name)
    return _ALIAS_TO_CANON.get(n, n)
