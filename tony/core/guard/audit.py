import hashlib
import json
from typing import Any


def canonical_json(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, ensure_ascii=False)


def args_hash(args: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(args).encode()).hexdigest()
