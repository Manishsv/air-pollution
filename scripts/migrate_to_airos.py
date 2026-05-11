#!/usr/bin/env python3
"""Migrate urban_platform/ → airos/ five-layer architecture.

Usage:
    python scripts/migrate_to_airos.py [--dry-run] [--apply]

Layers
------
airos/os/       ← storage, sdk, common, standards, specifications(py),
                   rules, decision_support, quality, city_config, scheduler,
                   decision_events, core, deployments, adapters
airos/apps/     ← urban_platform/applications/
airos/agents/   ← urban_platform/agents/
airos/drivers/  ← connectors, h3_knowledge, processing, feature_store,
                   observation_store, fabric, registries, place, models, vision
airos/network/  ← review_dashboard/, urban_platform/api/, tools/
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Mapping: source path (relative to ROOT) → destination (relative to ROOT)
# Each entry is (src_dir_or_file, dst_dir_or_file)
# ---------------------------------------------------------------------------

MOVES: list[tuple[str, str]] = [
    # ── airos/os/ ─────────────────────────────────────────────────────────
    ("urban_platform/storage",        "airos/os/storage"),
    ("urban_platform/sdk",            "airos/os/sdk"),
    ("urban_platform/common",         "airos/os/common"),
    ("urban_platform/standards",      "airos/os/standards"),
    ("urban_platform/specifications", "airos/os/specifications"),
    ("urban_platform/rules",          "airos/os/rules"),
    ("urban_platform/decision_support","airos/os/decision_support"),
    ("urban_platform/quality",        "airos/os/quality"),
    ("urban_platform/core",           "airos/os/core"),
    ("urban_platform/deployments",    "airos/os/deployments"),
    ("urban_platform/adapters",       "airos/os/adapters"),
    ("urban_platform/city_config.py", "airos/os/city_config.py"),
    ("urban_platform/scheduler.py",   "airos/os/scheduler.py"),
    ("urban_platform/decision_events.py", "airos/os/decision_events.py"),

    # ── airos/apps/ ───────────────────────────────────────────────────────
    ("urban_platform/applications",   "airos/apps"),

    # ── airos/agents/ ─────────────────────────────────────────────────────
    ("urban_platform/agents",         "airos/agents"),

    # ── airos/drivers/ ────────────────────────────────────────────────────
    ("urban_platform/connectors",     "airos/drivers/connectors"),
    ("urban_platform/h3_knowledge",   "airos/drivers/store"),
    ("urban_platform/processing",     "airos/drivers/processing"),
    ("urban_platform/feature_store",  "airos/drivers/feature_store"),
    ("urban_platform/observation_store", "airos/drivers/observation_store"),
    ("urban_platform/fabric",         "airos/drivers/fabric"),
    ("urban_platform/registries",     "airos/drivers/registries"),
    ("urban_platform/place",          "airos/drivers/place"),
    ("urban_platform/models",         "airos/drivers/models"),
    ("urban_platform/vision",         "airos/drivers/vision"),
    ("urban_platform/studio",         "airos/os/studio"),

    # ── airos/network/ ────────────────────────────────────────────────────
    ("review_dashboard",              "airos/network/dashboard"),
    ("urban_platform/api",            "airos/network/api"),
    ("tools",                         "airos/network/cli"),
]

# ---------------------------------------------------------------------------
# Import rewrite rules — applied to every .py file after the move
# Order matters: longer/more-specific patterns first.
# ---------------------------------------------------------------------------

IMPORT_REWRITES: list[tuple[str, str]] = [
    # urban_platform sub-packages → airos equivalents
    ("urban_platform.storage",              "airos.os.storage"),
    ("urban_platform.sdk",                  "airos.os.sdk"),
    ("urban_platform.common",               "airos.os.common"),
    ("urban_platform.standards",            "airos.os.standards"),
    ("urban_platform.specifications",       "airos.os.specifications"),
    ("urban_platform.rules",                "airos.os.rules"),
    ("urban_platform.decision_support",     "airos.os.decision_support"),
    ("urban_platform.quality",              "airos.os.quality"),
    ("urban_platform.core",                 "airos.os.core"),
    ("urban_platform.deployments",          "airos.os.deployments"),
    ("urban_platform.adapters",             "airos.os.adapters"),
    ("urban_platform.city_config",          "airos.os.city_config"),
    ("urban_platform.scheduler",            "airos.os.scheduler"),
    ("urban_platform.decision_events",      "airos.os.decision_events"),
    ("urban_platform.applications",         "airos.apps"),
    ("urban_platform.agents",               "airos.agents"),
    ("urban_platform.connectors",           "airos.drivers.connectors"),
    ("urban_platform.h3_knowledge",         "airos.drivers.store"),
    ("urban_platform.processing",           "airos.drivers.processing"),
    ("urban_platform.feature_store",        "airos.drivers.feature_store"),
    ("urban_platform.observation_store",    "airos.drivers.observation_store"),
    ("urban_platform.fabric",               "airos.drivers.fabric"),
    ("urban_platform.registries",           "airos.drivers.registries"),
    ("urban_platform.place",                "airos.drivers.place"),
    ("urban_platform.models",               "airos.drivers.models"),
    ("urban_platform.vision",               "airos.drivers.vision"),
    ("urban_platform.studio",              "airos.os.studio"),
    # Catch-all for any remaining urban_platform references
    ("urban_platform",                      "airos.os"),
    # review_dashboard → airos.network.dashboard
    ("review_dashboard",                    "airos.network.dashboard"),
]


def _git_mv(src: Path, dst: Path, dry_run: bool) -> None:
    """Use git mv to preserve history; fall back to shutil if not tracked."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"  [git mv] {src.relative_to(ROOT)} → {dst.relative_to(ROOT)}")
        return
    result = subprocess.run(
        ["git", "mv", str(src), str(dst)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Not tracked by git — plain copy+remove
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            shutil.rmtree(src)
        else:
            shutil.copy2(src, dst)
            src.unlink()


def _rewrite_imports(path: Path, dry_run: bool) -> int:
    """Rewrite import strings in a Python file.  Returns number of replacements."""
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in IMPORT_REWRITES:
        # Match: `import old`, `from old import`, `from old.sub`, `import old.sub`
        # Use word-boundary style: old is followed by dot, space, or end-of-token
        pattern = re.compile(
            r'(?<![.\w])' + re.escape(old) + r'(?=[.\s,;\\)\]]|$)',
            re.MULTILINE,
        )
        text = pattern.sub(new, text)
    if text == original:
        return 0
    n = len(re.findall("|".join(re.escape(o) for o, _ in IMPORT_REWRITES), original))
    if dry_run:
        print(f"  [rewrite] {path.relative_to(ROOT)} ({n} occurrences)")
    else:
        path.write_text(text, encoding="utf-8")
    return n


def _write_shim(path: Path, airos_pkg: str, dry_run: bool) -> None:
    """Write a backward-compat shim __init__.py in the old location."""
    content = f'''"""Backward-compatibility shim — {path.parent.name} has moved to {airos_pkg}.

Import from {airos_pkg} in new code.
"""
from {airos_pkg} import *  # noqa: F401,F403
from {airos_pkg} import __all__ as __all__  # noqa: F401
'''
    if dry_run:
        print(f"  [shim] {path.relative_to(ROOT)}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Interface stubs — written to each layer's __init__.py
# ---------------------------------------------------------------------------

LAYER_INTERFACES = {
    "airos/__init__.py": '''\
"""AirOS — Urban Intelligence Platform.

Five-layer architecture:
  airos.os        — runtime contracts, storage, config, scheduling
  airos.apps      — domain application logic (air, flood, heat, …)
  airos.agents    — AI analysis agents (H3 Expert, City Pattern, …)
  airos.drivers   — data integration (connectors, store, processing, …)
  airos.network   — external surfaces (dashboard, API, CLI)
"""
from pathlib import Path as _Path

__version__ = "0.1.0"

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
''',
    "airos/os/__init__.py": '''\
"""AirOS OS layer — runtime contracts, storage, config, scheduling.

Key exports (Protocol / ABC level):
    IStore              — read/write interface for any storage backend
    IContractValidator  — validates data against domain specs
    IDeploymentConfig   — deployment-level settings (city, environment)
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class IStore(Protocol):
    """Minimal storage interface every backend must satisfy."""
    def read(self, key: str) -> object: ...
    def write(self, key: str, value: object) -> None: ...


@runtime_checkable
class IContractValidator(Protocol):
    def validate(self, data: dict, schema_id: str) -> list[str]: ...


@runtime_checkable
class IDeploymentConfig(Protocol):
    city_id: str
    environment: str  # "dev" | "staging" | "prod"
''',
    "airos/drivers/__init__.py": '''\
"""AirOS Drivers layer — data integration contracts.

Key exports:
    DriverProtocol      — every connector must implement fetch()
    ISignalWriter       — writes raw signals to the H3 store
    IAssessmentReader   — reads assessments from the H3 store
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class DriverProtocol(Protocol):
    """Every domain data connector implements this interface."""
    def fetch(self, bbox: dict, **kwargs) -> object: ...


@runtime_checkable
class ISignalWriter(Protocol):
    def write_signals(self, rows: list[dict], *, city_id: str, domain: str) -> int: ...


@runtime_checkable
class IAssessmentReader(Protocol):
    def read_assessments(self, city_id: str, domain: str, limit: int) -> list[dict]: ...
''',
    "airos/apps/__init__.py": '''\
"""AirOS Apps layer — domain application logic.

Key exports:
    AppProtocol         — every domain app implements run_pipeline()
    DecisionPacket      — typed dict for decision outputs
"""
from __future__ import annotations
from typing import Any, Protocol, TypedDict, runtime_checkable


class DecisionPacket(TypedDict, total=False):
    packet_id: str
    spatial_unit_id: str
    city_id: str
    domain: str
    risk_level: str
    confidence_score: float
    field_verification_required: bool
    evidence: dict
    recommendations: list[dict]


@runtime_checkable
class AppProtocol(Protocol):
    """Every domain app exposes a pipeline entry point."""
    def run_pipeline(self, bbox: dict, city_id: str, **kwargs) -> dict: ...
''',
    "airos/agents/__init__.py": '''\
"""AirOS Agents layer — AI analysis agents.

Key exports:
    AgentProtocol       — every agent implements analyse()
    Insight             — typed dict for agent insight outputs
"""
from __future__ import annotations
from typing import Any, Protocol, TypedDict, runtime_checkable


class Insight(TypedDict, total=False):
    h3_id: str
    city_id: str
    domain: str
    risk_level: str
    summary: str
    recommended_actions: list[str]
    confidence: float
    analysis_timestamp: str


@runtime_checkable
class AgentProtocol(Protocol):
    """Every analysis agent exposes an analyse method."""
    def analyse(self, cell: dict, context: dict) -> Insight: ...
''',
    "airos/network/__init__.py": '''\
"""AirOS Network layer — external surfaces (dashboard, API, CLI).

Key exports:
    INetworkSurface     — every surface must implement serve()
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class INetworkSurface(Protocol):
    """Every external surface implements a serve() entry point."""
    def serve(self, **kwargs) -> None: ...
''',
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without making changes")
    parser.add_argument("--apply", action="store_true",
                        help="Actually execute the migration (required to make changes)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Pass --dry-run to preview or --apply to execute.")
        sys.exit(1)

    dry_run = args.dry_run
    print(f"{'DRY RUN — ' if dry_run else ''}Migrating to airos/\n")

    # ── Step 1: Move files/directories ──────────────────────────────────────
    print("=== Step 1: Moving files ===")
    for src_rel, dst_rel in MOVES:
        src = ROOT / src_rel
        dst = ROOT / dst_rel
        if not src.exists():
            print(f"  [SKIP] {src_rel} does not exist")
            continue
        if dst.exists() and not dry_run:
            print(f"  [SKIP] {dst_rel} already exists — skipping move")
            continue
        _git_mv(src, dst, dry_run)

    # ── Step 2: Write layer interface __init__.py files ─────────────────────
    print("\n=== Step 2: Writing layer interfaces ===")
    for rel_path, content in LAYER_INTERFACES.items():
        path = ROOT / rel_path
        if dry_run:
            print(f"  [write] {rel_path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    # ── Step 3: Rewrite imports in all moved .py files ───────────────────────
    print("\n=== Step 3: Rewriting imports in airos/ ===")
    total_rewrites = 0
    for py_file in sorted((ROOT / "airos").rglob("*.py")):
        n = _rewrite_imports(py_file, dry_run)
        total_rewrites += n
    print(f"  Total import occurrences rewritten: {total_rewrites}")

    # ── Step 4: Rewrite imports in files that were NOT moved ─────────────────
    print("\n=== Step 4: Rewriting remaining files at root ===")
    # main.py, pyproject.toml references, etc.
    for py_file in sorted(ROOT.glob("*.py")):
        _rewrite_imports(py_file, dry_run)

    # ── Step 5: Write backward-compat shims ──────────────────────────────────
    print("\n=== Step 5: Writing backward-compat shims ===")
    shims = [
        (ROOT / "urban_platform" / "__init__.py", "airos.os"),
    ]
    for shim_path, airos_pkg in shims:
        if dry_run:
            print(f"  [shim] {shim_path.relative_to(ROOT)}")
        else:
            _write_shim(shim_path, airos_pkg, dry_run)

    print("\nDone." if not dry_run else "\nDry run complete — no files changed.")


if __name__ == "__main__":
    main()
