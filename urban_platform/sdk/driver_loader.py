"""
AirOS Driver Loader
====================
Discovers, validates, and activates domain drivers for a deployment.

Discovery order
---------------
1. Built-in (in-tree) drivers referenced by "builtin_class" in drivers_registry.yaml.
2. Third-party drivers installed as Python packages that declare the
   "airos.drivers" entry point group.

Trust model
-----------
Only drivers with ``trusted: true`` in drivers_registry.yaml are loaded.
Drivers discovered via entry points but absent from the registry are quarantined
(logged as WARNING, not loaded).

Usage
-----
    from urban_platform.sdk.driver_loader import load_drivers
    from pathlib import Path

    drivers = load_drivers(Path("data/config/drivers_registry.yaml"))
    rows = drivers["air"].fetch("bangalore", bbox)

The returned dict is ``{domain_name: driver_instance}``.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from urban_platform.sdk.driver_types import ConformanceResult, DriverConformanceError

if TYPE_CHECKING:
    from urban_platform.sdk.driver_protocol import H3DataSourceDriver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_drivers(
    registry_path: Path | str,
    *,
    strict: bool = False,
) -> dict[str, "H3DataSourceDriver"]:
    """Load and conformance-check all trusted drivers listed in the registry.

    Parameters
    ----------
    registry_path : Path | str
        Path to drivers_registry.yaml.
    strict : bool
        If True, raise DriverConformanceError on the first conformance failure.
        If False (default), log the failure and skip the driver — the deployment
        continues with the remaining drivers.

    Returns
    -------
    dict[str, H3DataSourceDriver]
        Mapping of domain name → active, conformance-passed driver instance.
        Domains that failed conformance or are not trusted are absent.
    """
    registry_path = Path(registry_path)
    if not registry_path.exists():
        logger.warning(
            "drivers_registry.yaml not found at %s — falling back to legacy dispatch",
            registry_path,
        )
        return {}

    registry = _load_registry(registry_path)
    drivers: dict[str, "H3DataSourceDriver"] = {}

    # Step 1: load in-tree (builtin_class) drivers from registry
    for domain, cfg in registry.items():
        if not cfg.get("trusted", False):
            logger.debug("Driver %r is not trusted — skipping", domain)
            continue

        builtin_class = cfg.get("builtin_class")
        if builtin_class:
            driver = _load_builtin(domain, builtin_class, strict=strict)
            if driver is not None:
                drivers[domain] = driver

    # Step 2: discover third-party drivers via entry points
    ep_drivers = _discover_entry_point_drivers(registry, strict=strict)
    for domain, driver in ep_drivers.items():
        if domain in drivers:
            logger.warning(
                "Entry-point driver %r conflicts with built-in driver for domain %r — "
                "built-in takes precedence. Set trusted: false for the built-in to override.",
                type(driver).__name__, domain,
            )
        else:
            drivers[domain] = driver

    loaded = sorted(drivers.keys())
    logger.info(
        "Driver loader: %d driver(s) active — %s",
        len(loaded), loaded,
    )
    return drivers


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_registry(path: Path) -> dict[str, dict]:
    """Parse drivers_registry.yaml and return the 'drivers' section."""
    try:
        with path.open() as f:
            raw = yaml.safe_load(f)
        return raw.get("drivers", {})
    except Exception as exc:
        logger.error("Failed to parse %s: %s", path, exc)
        return {}


def _load_builtin(
    domain: str,
    builtin_class_str: str,
    *,
    strict: bool,
) -> "H3DataSourceDriver | None":
    """Import and instantiate a built-in driver class from 'module:ClassName' string."""
    try:
        module_path, class_name = builtin_class_str.rsplit(":", 1)
    except ValueError:
        logger.error(
            "Driver %r: invalid builtin_class format %r — expected 'module.path:ClassName'",
            domain, builtin_class_str,
        )
        return None

    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        instance = cls()
    except Exception as exc:
        logger.error("Driver %r: failed to import %r: %s", domain, builtin_class_str, exc)
        return None

    return _run_conformance(domain, instance, strict=strict)


def _discover_entry_point_drivers(
    registry: dict[str, dict],
    *,
    strict: bool,
) -> dict[str, "H3DataSourceDriver"]:
    """Discover drivers registered via the 'airos.drivers' entry point group."""
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="airos.drivers")
    except Exception:
        return {}

    drivers: dict[str, "H3DataSourceDriver"] = {}

    for ep in eps:
        domain = ep.name
        cfg = registry.get(domain, {})

        if not cfg:
            logger.warning(
                "Entry-point driver %r (from package %r) is not in drivers_registry.yaml — "
                "quarantined. Add it with trusted: true to activate.",
                domain, ep.value,
            )
            continue

        if not cfg.get("trusted", False):
            logger.warning(
                "Entry-point driver %r is in the registry but trusted: false — skipping",
                domain,
            )
            continue

        try:
            cls = ep.load()
            instance = cls()
        except Exception as exc:
            logger.error(
                "Driver %r: failed to load entry point %r: %s", domain, ep.value, exc
            )
            continue

        driver = _run_conformance(domain, instance, strict=strict)
        if driver is not None:
            drivers[domain] = driver

    return drivers


def _run_conformance(
    domain: str,
    instance: "H3DataSourceDriver",
    *,
    strict: bool,
) -> "H3DataSourceDriver | None":
    """Run conformance_check() on a driver instance.

    Returns the instance if ok, None if not ok (unless strict=True, in which
    case raises DriverConformanceError).
    """
    try:
        result: ConformanceResult = instance.conformance_check()
    except Exception as exc:
        logger.error("Driver %r: conformance_check() raised: %s", domain, exc)
        if strict:
            raise DriverConformanceError(
                f"Driver {domain!r} conformance_check() raised: {exc}"
            ) from exc
        return None

    for w in result.warnings:
        logger.warning("Driver %r conformance warning: %s", domain, w)

    if not result.ok:
        for f in result.failures:
            logger.error("Driver %r conformance failure: %s", domain, f)
        msg = f"Driver {domain!r} failed conformance: {result.failures}"
        if strict:
            raise DriverConformanceError(msg)
        logger.error("%s — driver will not be loaded", msg)
        return None

    logger.debug("Driver %r passed conformance (%r)", domain, type(instance).__name__)
    return instance


# ---------------------------------------------------------------------------
# Singleton registry (for use by ingestor.py)
# ---------------------------------------------------------------------------

_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "config" / "drivers_registry.yaml"
_active_drivers: dict[str, "H3DataSourceDriver"] | None = None


def get_active_drivers(*, reload: bool = False) -> dict[str, "H3DataSourceDriver"]:
    """Return the singleton active driver pool, loading it on first call.

    Call with reload=True to re-read drivers_registry.yaml and re-run
    conformance without restarting AirOS (e.g. after adding a new driver).
    """
    global _active_drivers
    if _active_drivers is None or reload:
        _active_drivers = load_drivers(_REGISTRY_PATH)
    return _active_drivers
