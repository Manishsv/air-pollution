"""
Reusable, layered urban data platform.

AirOS code is organized as vertical slices under `urban_platform/` and governed
by `specifications/` (contracts + conformance).
"""
from pathlib import Path as _Path

# Auto-load the project .env so keys (GEE, LLM, API) are available in any
# script context — not just main.py / dashboard app.
#
# Override rule: shell vars that are non-empty take precedence; shell vars
# that are set-but-empty (e.g. ANTHROPIC_API_KEY="" injected by Claude Desktop)
# are overridden by the .env value so the project config wins.
try:
    import os as _os
    from dotenv import dotenv_values as _dotenv_values
    _env_file = _Path(__file__).resolve().parent.parent / ".env"
    for _k, _v in _dotenv_values(_env_file).items():
        if _v and not _os.environ.get(_k):   # only set if env var is absent or blank
            _os.environ[_k] = _v
    del _k, _v, _env_file, _os, _dotenv_values
except (ImportError, Exception):
    pass  # python-dotenv not installed or .env missing; rely on shell env
