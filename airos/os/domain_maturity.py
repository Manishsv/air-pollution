"""Domain maturity registry — methodology §12.

Codifies the per-domain maturity tier from the methodology doc so dashboard
panels and downstream code can read a single source of truth instead of
having the tier hard-coded in multiple places.

Tier semantics (matches methodology §12):

    prod_observational     — Real measurement, low latency, well-served coverage
    prod_structural        — Slow-changing OSM/structural data with known limits
    prod_proxy             — Derived measurement approximating quantity of interest
    prod_event_driven      — Real measurements but inherently sparse — zero rows is meaningful
    pilot_proxy            — Functional but operationally limited; needs upgrade before high-stakes claims
    deployment_dependent   — Production-ready IF an external dependency is satisfied
    synthetic_demo         — Literature-derived or estimated; should not be load-bearing for action

Each entry also carries:
    `label`            : human-readable short name shown in the badge
    `color`            : CSS color for the badge background
    `caveat`           : one-line caveat surfaced to the user (and prompts) when the tier is below production-ready
"""
from __future__ import annotations


TIER_META: dict[str, dict[str, str]] = {
    "prod_observational": {
        "label":  "Production · Observational",
        "color":  "#16a34a",   # green
        "caveat": "",
    },
    "prod_structural": {
        "label":  "Production · Structural",
        "color":  "#0891b2",   # cyan
        "caveat": "",
    },
    "prod_proxy": {
        "label":  "Production · Proxy",
        "color":  "#7c3aed",   # purple
        "caveat": "Derived signal that approximates the quantity of interest — read alongside its caveats.",
    },
    "prod_event_driven": {
        "label":  "Production · Event-driven",
        "color":  "#0891b2",   # cyan
        "caveat": "Sparse by design — zero rows means no event detected, not no event occurred.",
    },
    "pilot_proxy": {
        "label":  "Pilot · Proxy",
        "color":  "#d97706",   # amber
        "caveat": "Pilot-stage proxy — not load-bearing for high-stakes decisions until production data feeds are wired up.",
    },
    "deployment_dependent": {
        "label":  "Deployment-dependent",
        "color":  "#d97706",
        "caveat": "Requires an external upstream feed (e.g. CV pipeline, API key) before signals appear.",
    },
    "synthetic_demo": {
        "label":  "Synthetic / Demo",
        "color":  "#dc2626",   # red
        "caveat": "Synthetic estimate — not measurement. Demo / sandbox only.",
    },
}


# Per-domain assignment. Matches methodology §12 Domain Maturity Matrix.
DOMAIN_MATURITY: dict[str, str] = {
    "air":          "prod_observational",
    "weather":      "prod_proxy",            # model output, not station obs
    "roads":        "prod_structural",
    "buildings":    "prod_structural",
    "drains":       "prod_structural",
    "pois":         "prod_structural",
    "terrain":      "prod_structural",
    "fire":         "prod_event_driven",
    "heat":         "prod_proxy",            # surface UHI, not human heat exposure
    "nightlights":  "prod_proxy",            # falls back to synthetic if no token; flag in caveat
    "green":        "prod_proxy",
    "water":        "prod_proxy",
    "construction": "prod_proxy",
    "waste":        "prod_proxy",            # FIRMS attribution is a hypothesis
    "noise":        "pilot_proxy",           # synthetic mode by default
    "flood":        "pilot_proxy",           # synthetic incidents/assets in v1
    "crowd":        "deployment_dependent",  # needs upstream CV pipeline
}


def get_domain_maturity(domain: str) -> dict[str, str]:
    """Return {tier, label, color, caveat} for a domain.

    Unknown domains return a neutral 'unknown' entry so callers don't need
    to defend against KeyError.
    """
    tier = DOMAIN_MATURITY.get(domain, "unknown")
    meta = TIER_META.get(tier) or {
        "label":  "Unknown maturity",
        "color":  "#6b7280",
        "caveat": "",
    }
    return {"tier": tier, **meta}
