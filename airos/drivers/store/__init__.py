"""H3 Knowledge Store — multi-level DuckDB store indexed by H3 cell.

Levels
------
0/1  h3_signals      — raw observations and derived features per cell
2    h3_assessments  — domain risk assessments per cell
3    h3_packets      — decision packets linked to cells
4    h3_insights     — agent-generated cross-domain insights
5    h3_outcomes     — field feedback / ground-truth outcomes

Quick start
-----------
>>> from airos.drivers.store import writer, reader
>>> writer.upsert_metadata(h3_id="8a1b00000007fff", city_id="bangalore", resolution=8)
>>> writer.write_signals([{"h3_id": "8a1b00000007fff", "signal": "AQI", "value": 142}],
...                      city_id="bangalore", domain="air")
>>> ctx = reader.get_h3_context("8a1b00000007fff", "bangalore")
"""

from airos.drivers.store import reader, writer
from airos.drivers.store.store import H3KnowledgeStore

__all__ = ["H3KnowledgeStore", "writer", "reader"]
