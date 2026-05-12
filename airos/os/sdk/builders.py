"""
airos.os.sdk.builders — builder / agent discovery (DISCOVER mode).

Builders are the AI agents that process data and produce assessments, insights,
and city-wide patterns.  This module provides metadata-only access: it describes
what each builder does and what data contracts it consumes/produces.  It does
NOT load or execute builder code.

Typical usage
-------------
::

    from airos.os.sdk import list_builders, get_builder_spec

    for b in list_builders():
        print(b["builder_id"], "→", b["description"])

    spec = get_builder_spec("h3_expert")
    print(spec["output_contracts"])

Builder registry
----------------
Builders are registered in ``_BUILDER_REGISTRY`` below.  Each entry maps a
``builder_id`` to a spec dict with the following keys:

- ``builder_id``      — stable identifier used in run logs and audit events
- ``description``     — one-line human-readable summary
- ``input_contracts`` — data contract keys the builder reads
- ``output_contracts``— data contract keys the builder writes
- ``trigger``         — ``"sweep"`` (scheduled) or ``"on_demand"``
- ``domain``          — primary domain(s) this builder operates on, or ``None``
                        for cross-domain builders
- ``requires_llm``    — whether the builder calls an LLM
- ``latency_class``   — ``"fast"`` (<5 s), ``"medium"`` (5–60 s), ``"slow"`` (>60 s)
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Registry — authoritative list of builders in the AirOS pipeline.
# To add a new builder: append an entry here and run the test suite.
# ---------------------------------------------------------------------------

_BUILDER_REGISTRY: list[dict[str, Any]] = [
    {
        "builder_id": "h3_expert",
        "description": (
            "Analyses signals for a single H3 cell and produces a structured "
            "risk assessment plus a natural-language insight with evidence citations."
        ),
        "input_contracts": ["h3_signals", "h3_metadata", "h3_assessments"],
        "output_contracts": ["h3_assessments", "h3_insights"],
        "trigger": "sweep",
        "domain": None,  # cross-domain: runs per-cell across all domains
        "requires_llm": True,
        "latency_class": "medium",
    },
    {
        "builder_id": "city_pattern",
        "description": (
            "Synthesises cell-level insights into a city-wide pattern narrative. "
            "Runs after the H3 Expert sweep and covers all domains with high/severe risk."
        ),
        "input_contracts": ["h3_insights", "h3_assessments"],
        "output_contracts": ["city_patterns"],
        "trigger": "sweep",
        "domain": None,  # city-wide, cross-domain
        "requires_llm": True,
        "latency_class": "medium",
    },
    {
        "builder_id": "gee_air_quality",
        "description": (
            "Google Earth Engine connector. Fetches satellite-derived air quality "
            "signals (NO₂, PM2.5 proxies, AOD) and writes them to h3_signals."
        ),
        "input_contracts": [],
        "output_contracts": ["h3_signals"],
        "trigger": "sweep",
        "domain": "air_quality",
        "requires_llm": False,
        "latency_class": "slow",
    },
    {
        "builder_id": "gee_urban_heat",
        "description": (
            "Google Earth Engine connector. Fetches land surface temperature (LST) "
            "and NDVI and writes urban heat signals to h3_signals."
        ),
        "input_contracts": [],
        "output_contracts": ["h3_signals"],
        "trigger": "sweep",
        "domain": "urban_heat",
        "requires_llm": False,
        "latency_class": "slow",
    },
    {
        "builder_id": "pc_green_cover",
        "description": (
            "Microsoft Planetary Computer connector. Measures vegetation cover change "
            "(NDVI, EVI, ΔNDVI) from Sentinel-2 L2A and writes green cover signals "
            "to h3_signals. No GEE dependency — uses public STAC catalog."
        ),
        "input_contracts": [],
        "output_contracts": ["h3_signals"],
        "trigger": "sweep",
        "domain": "green_cover",
        "requires_llm": False,
        "latency_class": "slow",
    },
    {
        "builder_id": "gee_water",
        "description": (
            "Google Earth Engine connector. Assesses optical water clarity (NDWI "
            "proxy) and writes water quality signals to h3_signals."
        ),
        "input_contracts": [],
        "output_contracts": ["h3_signals"],
        "trigger": "sweep",
        "domain": "water_quality",
        "requires_llm": False,
        "latency_class": "slow",
    },
    {
        "builder_id": "gee_construction",
        "description": (
            "Google Earth Engine connector. Detects active construction via SAR "
            "backscatter change and writes construction signals to h3_signals."
        ),
        "input_contracts": [],
        "output_contracts": ["h3_signals"],
        "trigger": "sweep",
        "domain": "construction",
        "requires_llm": False,
        "latency_class": "slow",
    },
    {
        "builder_id": "gee_flood",
        "description": (
            "Google Earth Engine connector. Identifies flood-prone and currently "
            "inundated cells using SAR and writes flood signals to h3_signals."
        ),
        "input_contracts": [],
        "output_contracts": ["h3_signals"],
        "trigger": "sweep",
        "domain": "flood_risk",
        "requires_llm": False,
        "latency_class": "slow",
    },
    {
        "builder_id": "openaq_ingestor",
        "description": (
            "OpenAQ adapter. Pulls ground-station PM2.5, PM10, NO₂, O₃ readings "
            "and writes them to h3_signals with data_quality='real_station'."
        ),
        "input_contracts": [],
        "output_contracts": ["h3_signals"],
        "trigger": "sweep",
        "domain": "air_quality",
        "requires_llm": False,
        "latency_class": "fast",
    },
]

# Index for O(1) lookup
_REGISTRY_INDEX: dict[str, dict[str, Any]] = {b["builder_id"]: b for b in _BUILDER_REGISTRY}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_builders(
    *,
    domain: str | None = None,
    requires_llm: bool | None = None,
    trigger: str | None = None,
) -> list[dict[str, Any]]:
    """Return metadata for all registered builders, with optional filters.

    Parameters
    ----------
    domain:
        Filter to builders whose primary domain matches.  Cross-domain builders
        (``domain=None`` in registry) are always included unless filtered.
    requires_llm:
        If ``True``, return only LLM-backed builders.
        If ``False``, return only rule-based / connector builders.
    trigger:
        Filter by trigger mode: ``"sweep"`` or ``"on_demand"``.

    Returns
    -------
    list[dict]
        Each dict has: builder_id, description, input_contracts,
        output_contracts, trigger, domain, requires_llm, latency_class.

    Example
    -------
    ::

        from airos.os.sdk import list_builders

        # All builders
        for b in list_builders():
            print(b["builder_id"])

        # Only LLM builders
        for b in list_builders(requires_llm=True):
            print(b["builder_id"], b["latency_class"])
    """
    out = list(_BUILDER_REGISTRY)

    if domain is not None:
        out = [b for b in out if b.get("domain") is None or b.get("domain") == domain]
    if requires_llm is not None:
        out = [b for b in out if b.get("requires_llm") == requires_llm]
    if trigger is not None:
        out = [b for b in out if b.get("trigger") == trigger]

    return out


def get_builder_spec(builder_id: str) -> dict[str, Any] | None:
    """Return the spec dict for a single builder, or ``None`` if not found.

    Parameters
    ----------
    builder_id:
        The stable builder identifier (e.g. ``"h3_expert"``).

    Example
    -------
    ::

        from airos.os.sdk import get_builder_spec

        spec = get_builder_spec("city_pattern")
        print(spec["input_contracts"])   # ["h3_insights", "h3_assessments"]
        print(spec["requires_llm"])      # True
    """
    return dict(_REGISTRY_INDEX[builder_id]) if builder_id in _REGISTRY_INDEX else None
