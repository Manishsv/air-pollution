from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .schema import OBSERVATION_COLUMNS, RAW_DATA_ROOT

logger = logging.getLogger(__name__)


def _date_from_stem(path: Path) -> Optional[date]:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


class ObservationStoreReader:
    def __init__(self, root: Path = RAW_DATA_ROOT) -> None:
        self._root = root

    def read_recent(
        self,
        domain: str,
        city_id: str,
        max_age_hours: int = 1,
        lookback_days: int = 1,
    ) -> pd.DataFrame:
        """
        Return cached observations if the most recent file is fresh enough.
        Returns empty DataFrame if cache is absent or stale — caller falls back to API.
        """
        domain_dir = self._root / domain / city_id
        if not domain_dir.exists():
            return pd.DataFrame(columns=OBSERVATION_COLUMNS)

        files = sorted(domain_dir.glob("*.parquet"), reverse=True)
        if not files:
            return pd.DataFrame(columns=OBSERVATION_COLUMNS)

        latest_mtime = datetime.fromtimestamp(files[0].stat().st_mtime, tz=timezone.utc)
        age = datetime.now(timezone.utc) - latest_mtime
        if age > timedelta(hours=max_age_hours):
            logger.debug("Cache stale for %s/%s (age %.1fh)", domain, city_id,
                         age.total_seconds() / 3600)
            return pd.DataFrame(columns=OBSERVATION_COLUMNS)

        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date()
        to_read = [f for f in files if (_date_from_stem(f) or date.min) >= cutoff]
        if not to_read:
            return pd.DataFrame(columns=OBSERVATION_COLUMNS)

        try:
            return pd.concat([pd.read_parquet(f) for f in to_read], ignore_index=True)
        except Exception as exc:
            logger.warning("read_recent failed: %s", exc)
            return pd.DataFrame(columns=OBSERVATION_COLUMNS)

    def query_range(
        self,
        domain: str,
        city_id: str,
        ts_start: datetime,
        ts_end: datetime,
    ) -> pd.DataFrame:
        """DuckDB-powered temporal range scan across all partitions for a domain+city."""
        import duckdb

        domain_dir = self._root / domain / city_id
        files = list(domain_dir.glob("*.parquet")) if domain_dir.exists() else []
        if not files:
            return pd.DataFrame(columns=OBSERVATION_COLUMNS)

        glob = str(domain_dir / "*.parquet")
        ts_start_s = ts_start.astimezone(timezone.utc).isoformat()
        ts_end_s = ts_end.astimezone(timezone.utc).isoformat()

        try:
            conn = duckdb.connect()
            df = conn.execute(
                """
                SELECT *
                FROM read_parquet(?)
                WHERE domain   = ?
                  AND city_id  = ?
                  AND timestamp >= ?
                  AND timestamp <  ?
                ORDER BY timestamp, station_id, variable
                """,
                [glob, domain, city_id, ts_start_s, ts_end_s],
            ).df()
            conn.close()
            return df
        except Exception as exc:
            logger.warning("query_range failed: %s", exc)
            return pd.DataFrame(columns=OBSERVATION_COLUMNS)

    def list_available(self, domain: str, city_id: str) -> list[str]:
        """Sorted list of date strings that have Parquet files for domain+city."""
        d = self._root / domain / city_id
        if not d.exists():
            return []
        return sorted(f.stem for f in d.glob("*.parquet") if _date_from_stem(f))
