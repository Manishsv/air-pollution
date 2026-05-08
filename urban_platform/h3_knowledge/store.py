"""H3KnowledgeStore — DuckDB connection manager and schema initialiser."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

try:
    import duckdb
    _DUCKDB_OK = True
except ImportError:
    _DUCKDB_OK = False

from urban_platform.h3_knowledge.schema import DB_PATH, ALL_DDL

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_instance: Optional["H3KnowledgeStore"] = None


class H3KnowledgeStore:
    """Thread-safe DuckDB-backed multi-level H3 knowledge store.

    Usage
    -----
    store = H3KnowledgeStore.get()          # singleton
    store.execute("SELECT count(*) FROM h3_signals")
    # or use the writer/reader helpers
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        if not _DUCKDB_OK:
            raise ImportError(
                "duckdb is not installed. Run: pip install duckdb"
            )
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection = duckdb.connect(str(db_path))
        self._init_schema()
        logger.info("H3KnowledgeStore initialised at %s", db_path)

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, db_path: Path = DB_PATH) -> "H3KnowledgeStore":
        """Return the process-level singleton, creating it if needed."""
        global _instance
        if _instance is None:
            with _lock:
                if _instance is None:
                    _instance = cls(db_path)
        return _instance

    @classmethod
    def reset(cls) -> None:
        """Close and discard the singleton (useful in tests)."""
        global _instance
        with _lock:
            if _instance is not None:
                try:
                    _instance._conn.close()
                except Exception:
                    pass
                _instance = None

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        for ddl in ALL_DDL:
            # DuckDB executes multi-statement strings when separated by ";"
            # but CREATE INDEX can't be in the same execute as CREATE TABLE
            # on some builds — split on blank lines to be safe.
            for stmt in ddl.strip().split("\n\n"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        self._conn.execute(stmt)
                    except Exception as exc:
                        logger.warning("Schema DDL warning (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Low-level execute (used by writer/reader)
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: list | None = None):
        """Execute SQL, returning a DuckDB relation."""
        with _lock:
            if params:
                return self._conn.execute(sql, params)
            return self._conn.execute(sql)

    def fetchdf(self, sql: str, params: list | None = None):
        """Execute SQL and return a pandas DataFrame."""
        import pandas as pd
        with _lock:
            try:
                if params:
                    return self._conn.execute(sql, params).df()
                return self._conn.execute(sql).df()
            except Exception as exc:
                logger.error("H3KnowledgeStore query error: %s | sql: %s", exc, sql[:200])
                return pd.DataFrame()

    def fetchone(self, sql: str, params: list | None = None):
        """Execute SQL and return the first row tuple, or None."""
        with _lock:
            try:
                cur = self._conn.execute(sql, params or [])
                return cur.fetchone()
            except Exception as exc:
                logger.error("H3KnowledgeStore fetchone error: %s", exc)
                return None

    # ------------------------------------------------------------------
    # Convenience: table row counts (health check)
    # ------------------------------------------------------------------

    def table_counts(self) -> dict[str, int]:
        tables = ["h3_metadata", "h3_signals", "h3_assessments",
                  "h3_packets", "h3_insights", "h3_outcomes"]
        counts: dict[str, int] = {}
        for t in tables:
            row = self.fetchone(f"SELECT count(*) FROM {t}")
            counts[t] = int(row[0]) if row else 0
        return counts

    def is_available(self) -> bool:
        try:
            self.fetchone("SELECT 1")
            return True
        except Exception:
            return False
