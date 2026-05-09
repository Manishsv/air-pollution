from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional

from .schema import DEFAULT_RETENTION_DAYS, RAW_DATA_ROOT

logger = logging.getLogger(__name__)


def _date_from_stem(path: Path) -> Optional[date]:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def prune(
    domain: str,
    city_id: str,
    retention_days: Optional[int] = None,
    root: Path = RAW_DATA_ROOT,
    today: Optional[date] = None,
) -> int:
    """Delete Parquet files for domain/city_id older than retention_days. Returns file count deleted."""
    cutoff = (today or date.today()) - timedelta(
        days=retention_days if retention_days is not None else DEFAULT_RETENTION_DAYS.get(domain, 90)
    )
    domain_dir = root / domain / city_id
    if not domain_dir.exists():
        return 0

    deleted = 0
    for f in domain_dir.glob("*.parquet"):
        obs_date = _date_from_stem(f)
        if obs_date and obs_date < cutoff:
            try:
                f.unlink()
                logger.info("Pruned %s", f)
                deleted += 1
            except OSError as exc:
                logger.warning("Could not delete %s: %s", f, exc)
    return deleted


def prune_all(
    retention_overrides: Optional[Dict[str, int]] = None,
    root: Path = RAW_DATA_ROOT,
    today: Optional[date] = None,
) -> Dict[str, int]:
    """Prune all domains and cities found under root. Returns {domain/city_id: files_deleted}."""
    overrides = retention_overrides or {}
    results: Dict[str, int] = {}
    if not root.exists():
        return results
    for domain_dir in root.iterdir():
        if not domain_dir.is_dir():
            continue
        domain = domain_dir.name
        days = overrides.get(domain, DEFAULT_RETENTION_DAYS.get(domain, 90))
        for city_dir in domain_dir.iterdir():
            if not city_dir.is_dir():
                continue
            n = prune(domain, city_dir.name, days, root=root, today=today)
            results[f"{domain}/{city_dir.name}"] = n
    return results
