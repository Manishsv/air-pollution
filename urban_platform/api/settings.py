from __future__ import annotations

import os
from pathlib import Path

# Repo root: urban_platform/api/settings.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def api_store_dir() -> Path:
    """
    Root directory for FileAirOsStore used by the pilot API.

    Env: AIROS_STORE_DIR (absolute or relative to repo root). Default: data/store/api
    """
    raw = os.environ.get("AIROS_STORE_DIR", "").strip()
    if not raw:
        return (_REPO_ROOT / "data" / "store" / "api").resolve()
    p = Path(raw)
    if not p.is_absolute():
        return (_REPO_ROOT / p).resolve()
    return p.resolve()
