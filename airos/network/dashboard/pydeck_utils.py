"""pydeck serialization safety utilities.

pydeck 0.9.x serialises layer data via json.dumps() without allow_nan=False,
so Python float('nan') becomes the bare JavaScript token `NaN` in the output.
NaN is not valid JSON; browsers parse it as the IEEE-754 NaN float.  When
that NaN lands in an h3_id field the H3-js library throws:

    "Latitude or longitude arguments were outside of acceptable range (code: 3)"

even though every H3 ID is perfectly valid in Python.

Two-layer defence
-----------------
1. ``clean_h3_data()`` — call this on every layer's data *before* passing to
   ``pdk.Layer``.  It filters bad h3_id rows and replaces NaN/Inf in all
   values (recursively, including nested RGBA color lists).

2. Module-level monkey-patch of ``pydeck.bindings.json_tools.serialize`` —
   a belt-and-suspenders guarantee that even data that bypasses
   ``clean_h3_data`` (e.g. a raw DataFrame passed directly to pdk.Layer, or
   NaN introduced by ``default_serialize`` during the to_dict conversion) is
   scrubbed before the JSON string leaves Python.

Usage
-----
    from airos.network.dashboard.pydeck_utils import clean_h3_data

    layer = pdk.Layer("H3HexagonLayer", data=clean_h3_data(cells), ...)
"""
from __future__ import annotations

import json as _json
import math
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Core NaN sanitiser (recursive)
# ---------------------------------------------------------------------------

def _nan_to_none(val: Any) -> Any:
    """Replace non-finite floats (NaN, Inf) with None (→ JSON null), recursively.

    Handles:
    - Python float NaN / Inf
    - numpy.float64 / float32 / float16 (all support math.isfinite via __float__)
    - Nested lists (e.g. RGBA color arrays like [180, NaN, 24, 200])
    - Nested dicts
    """
    if isinstance(val, bool):
        return val  # bool is a subclass of int; protect it before the numeric check
    try:
        if not math.isfinite(val):      # works for float, np.float64, np.float32 …
            return None
    except TypeError:
        pass  # non-numeric types (str, None, list, dict, …) → fall through
    if isinstance(val, list):
        return [_nan_to_none(v) for v in val]
    if isinstance(val, dict):
        return {k: _nan_to_none(v) for k, v in val.items()}
    return val


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean_h3_data(data: list[dict] | pd.DataFrame) -> list[dict]:
    """Return a sanitised list of dicts safe to pass to pydeck.Layer.

    Steps
    -----
    1. Convert DataFrame → list of dicts if needed.
    2. Drop rows where ``h3_id`` is not a non-empty string (catches None,
       float NaN, int 0, empty string, and the sentinel string "nan" —
       all of which crash H3-js).
    3. Walk every value in every surviving row and replace any float NaN /
       Infinity with ``None`` so json.dumps() emits ``null`` instead of
       the bare ``NaN`` literal.
    """
    if isinstance(data, pd.DataFrame):
        rows: list[dict] = data.to_dict(orient="records")
    else:
        rows = list(data or [])

    result = []
    for row in rows:
        # Only filter on h3_id if the row actually has that field.
        # Non-H3 layers (ScatterplotLayer etc.) have no h3_id — keep them, just clean NaN.
        if "h3_id" in row:
            h3_id = row["h3_id"]
            # Reject non-strings, empty strings, and the sentinel string "nan"
            # that pandas sometimes emits when a float-NaN migrates into an
            # object column and gets cast to str.
            if not isinstance(h3_id, str) or not h3_id.strip() or h3_id.strip().lower() == "nan":
                continue
        # Replace NaN/Inf in every value (→ JSON null instead of bare NaN token)
        result.append({k: _nan_to_none(v) for k, v in row.items()})

    return result


# ---------------------------------------------------------------------------
# Belt-and-suspenders: patch pydeck's JSON serialiser
#
# Even when clean_h3_data() is called, a raw DataFrame passed directly to
# pdk.Layer (e.g. in cross_domain_panel) or NaN values returned by pydeck's
# own default_serialize() would still leak into the output.  Patching
# pydeck's serialize() function guarantees that every deck.to_json() call
# scrubs NaN → null, regardless of whether clean_h3_data() was used.
# ---------------------------------------------------------------------------

def _deep_clean(obj: Any) -> Any:
    """Recursively replace non-finite floats with None in any JSON-like structure."""
    if isinstance(obj, bool):
        return obj
    try:
        if not math.isfinite(obj):
            return None
    except TypeError:
        pass
    if isinstance(obj, list):
        return [_deep_clean(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _deep_clean(v) for k, v in obj.items()}
    return obj


def _patch_pydeck_serialize() -> None:
    """Monkey-patch pydeck.bindings.json_tools.serialize to be NaN-safe."""
    try:
        import pydeck.bindings.json_tools as _jt

        _orig_default = _jt.default_serialize

        def _safe_default(o, remap_function=_jt.lower_camel_case_keys):
            result = _orig_default(o, remap_function=remap_function)
            return _deep_clean(result)

        def _safe_serialize(serializable):
            cleaned = _deep_clean(serializable)
            return _json.dumps(
                cleaned,
                sort_keys=True,
                default=_safe_default,
                indent=2,
            )

        _jt.serialize = _safe_serialize
        # Also patch the module-level reference used by JSONMixin.to_json()
        import pydeck.bindings.deck as _deck_mod
        if hasattr(_deck_mod, "serialize"):
            _deck_mod.serialize = _safe_serialize

    except Exception:
        # If pydeck internals change, fall back silently — clean_h3_data()
        # still provides the first line of defence.
        pass


_patch_pydeck_serialize()
