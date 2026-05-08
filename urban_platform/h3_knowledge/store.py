"""H3KnowledgeStore — DuckDB store using transient connections.

Concurrency model
-----------------
DuckDB does not support concurrent connections (even read-only blocks while a
write connection is held).  The solution: every query opens its own connection,
runs the statement, and closes the connection immediately.  The file lock is held
for the duration of one SQL call (~1-5 ms), not for the lifetime of the process.

This means:
  - Dashboard and ingestor can interleave safely (probabilistically — rare
    lock collisions surface as warnings and return empty results, not crashes).
  - No singleton, no global state to manage.
  - Ingestor does NOT need to hold an exclusive session.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

try:
    import duckdb
    _DUCKDB_OK = True
except ImportError:
    _DUCKDB_OK = False

from urban_platform.h3_knowledge.schema import DB_PATH, ALL_DDL

logger = logging.getLogger(__name__)

# One lock to serialise access within a single process (e.g. multi-threaded Streamlit).
# Cross-process contention is handled by catching IOException.
_lock = threading.Lock()

_schema_initialised = False


def _ensure_schema(db_path: Path) -> None:
    """Create tables if they don't exist.  Runs once per process."""
    global _schema_initialised
    if _schema_initialised:
        return
    try:
        with duckdb.connect(str(db_path)) as conn:
            for ddl in ALL_DDL:
                for stmt in ddl.strip().split("\n\n"):
                    stmt = stmt.strip()
                    if stmt:
                        try:
                            conn.execute(stmt)
                        except Exception as exc:
                            logger.debug("Schema DDL (non-fatal): %s", exc)
        _schema_initialised = True
        logger.info("H3KnowledgeStore schema ready at %s", db_path)
    except Exception as exc:
        logger.warning("Schema init failed (DB may be locked): %s", exc)


class H3KnowledgeStore:
    """Transient-connection wrapper around a DuckDB file.

    Every public method opens a connection, runs SQL, and closes the connection.
    This keeps lock hold-time to ~1-5 ms per call, enabling safe interleaving
    between the dashboard (reads) and the ingestor (writes).
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        if not _DUCKDB_OK:
            raise ImportError("duckdb is not installed. Run: pip install duckdb")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        _ensure_schema(db_path)

    # ------------------------------------------------------------------
    # Factory / singleton
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, db_path: Path = DB_PATH) -> "H3KnowledgeStore":
        """Return a store handle.  Cheap — no connection is opened here."""
        return cls(db_path)

    # kept for API compatibility — same as get() with transient connections
    @classmethod
    def get_writer(cls, db_path: Path = DB_PATH) -> "H3KnowledgeStore":
        return cls(db_path)

    @classmethod
    def reset(cls) -> None:
        """No-op with transient connections (no singleton to clear)."""
        global _schema_initialised
        _schema_initialised = False

    # ------------------------------------------------------------------
    # Core execute helpers
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: list | None = None) -> None:
        """Execute a write statement (INSERT / UPDATE / DELETE / DDL)."""
        with _lock:
            try:
                with duckdb.connect(str(self._db_path)) as conn:
                    if params:
                        conn.execute(sql, params)
                    else:
                        conn.execute(sql)
            except Exception as exc:
                if "lock" in str(exc).lower() or "IO Error" in str(exc):
                    logger.warning("H3Store write skipped (lock contention): %s", exc)
                else:
                    logger.warning("H3Store execute error: %s | sql: %.120s", exc, sql)

    def fetchdf(self, sql: str, params: list | None = None):
        """Execute a SELECT and return a pandas DataFrame."""
        import pandas as pd
        with _lock:
            try:
                with duckdb.connect(str(self._db_path), read_only=True) as conn:
                    if params:
                        return conn.execute(sql, params).df()
                    return conn.execute(sql).df()
            except Exception as exc:
                if "lock" in str(exc).lower() or "IO Error" in str(exc):
                    logger.debug("H3Store read skipped (lock contention): %s", exc)
                else:
                    logger.warning("H3Store fetchdf error: %s | sql: %.120s", exc, sql)
                return pd.DataFrame()

    def fetchone(self, sql: str, params: list | None = None):
        """Execute a SELECT and return the first row tuple, or None."""
        with _lock:
            try:
                with duckdb.connect(str(self._db_path), read_only=True) as conn:
                    cur = conn.execute(sql, params or [])
                    return cur.fetchone()
            except Exception as exc:
                if "lock" in str(exc).lower() or "IO Error" in str(exc):
                    logger.debug("H3Store fetchone skipped (lock contention): %s", exc)
                else:
                    logger.warning("H3Store fetchone error: %s", exc)
                return None

    # ------------------------------------------------------------------
    # Health check
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
        return self.fetchone("SELECT 1") is not None
