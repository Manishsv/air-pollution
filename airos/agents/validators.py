"""Post-generation validator for H3 expert agent outputs.

Strips city-broadcast tokens from compound labels and `domains_involved`,
demotes tier if compound legitimacy collapses, and stamps an audit trail
on the insight payload. Runs after structured-output JSON parsing, before
`write_insight()` persists the row.

Why deterministic (not another LLM call):
The agent's system prompt (v0.7) bans "air-heat compound" labels but the
model complies inconsistently — ~75% on Pune Haveli Subdistrict sweeps,
with cells that have multiple legitimate cell-resolved domains regressing.
A regex/set-level guard catches the remaining 25% with zero token cost.

Methodology §4.4 (similarity-bias mitigation).
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

VALIDATOR_VERSION = "post-gen-v0.1"

# Domain tokens that are *always* city-broadcast at AirOS today
_CITY_BROADCAST_DOMAINS = frozenset({"weather"})

# Tokens that may appear as compound-label modifiers and should be stripped
# from "air-heat-noise compound stress" → "air-noise compound stress".
# We strip BOTH the heat token (when only city-broadcast heat signals fired)
# AND every weather-side hyphen modifier.
_CITY_BROADCAST_LABEL_TOKENS = frozenset({
    "weather", "wind", "humidity", "pressure", "temperature", "precip",
    "rain",  # narrative shorthand
})

# Heat signals — if the only elevated heat signals are these (city-broadcast),
# strip 'heat' from compound labels. If a cell-resolved heat signal (LST) is
# elevated, 'heat' is a legitimate compound leg.
_HEAT_CITY_BROADCAST_SIGNALS = frozenset({"HEAT_INDEX_C", "UHI"})
_HEAT_CELL_RESOLVED_SIGNALS  = frozenset({"LST", "LST_C"})

# Tier demotion threshold — high requires ≥2 elevated cell-resolved domains
_HIGH_REQUIRES_DOMAINS = 2


def _heat_is_city_broadcast(dossier_signals: dict | None) -> bool:
    """Return True if the only elevated heat signals are city-broadcast ones.

    Falls back to True (treat heat as city-broadcast) when we cannot inspect
    the dossier — the safer default given we know HEAT_INDEX_C dominates.
    """
    if not dossier_signals:
        return True
    heat_sigs = (dossier_signals.get("heat") or {})
    has_cell_resolved = any(
        s in heat_sigs and (heat_sigs[s] or {}).get("value") is not None
        for s in _HEAT_CELL_RESOLVED_SIGNALS
    )
    return not has_cell_resolved


def _rewrite_compound_label(finding: str, strip_tokens: set[str]) -> tuple[str, str | None]:
    """Strip `strip_tokens` from the hyphenated compound label preceding the
    first colon in `finding`. Returns (new_finding, rewrite_note | None).

    Examples (with strip_tokens={"heat", "wind"}):
      "Persistent air-heat compound stress: PM2.5 spike (58…)"
        → "Persistent PM2.5 spike (58…)"     (label collapses → single token)
      "Transient air-heat-noise compound stress: PM2.5 spike (…)"
        → "Transient air-noise compound stress: PM2.5 spike (…)"
      "Episodic PM2.5 spike (…) part of city-wide event"   (no compound label)
        → unchanged
    """
    if not finding or ":" not in finding:
        return finding, None
    head, _, tail = finding.partition(":")
    # Look for "<prefix> <a>-<b>[-<c>…] compound <suffix>"
    m = re.match(r"^(.*?)\b((?:[a-z]+)(?:-[a-z]+)+)\s+compound\s+(\w+)\s*$",
                 head.strip(), re.IGNORECASE)
    if not m:
        return finding, None
    prefix, label, suffix = m.group(1).strip(), m.group(2), m.group(3)
    toks = label.lower().split("-")
    keep = [t for t in toks if t not in strip_tokens]
    if keep == toks:
        return finding, None   # nothing to strip
    if len(keep) >= 2:
        new_label = "-".join(keep) + f" compound {suffix}"
    elif len(keep) == 1:
        # Collapse — only one domain remains, drop the "compound" word entirely
        # and let the body of the finding carry the meaning.
        new_label = ""   # signal: strip the entire label section
    else:
        new_label = ""
    if new_label:
        new_head = f"{prefix} {new_label}".strip()
        new_finding = f"{new_head}:{tail}"
    else:
        # Collapsed label — keep only the body (after the colon) prefixed
        # with the original sentence start.
        new_finding = f"{prefix}{tail}".strip()
        new_finding = re.sub(r"\s+", " ", new_finding)
    return new_finding, f"{label} compound {suffix} → {new_label or '(collapsed to body)'}"


def validate_post_generation(
    payload: dict[str, Any],
    *,
    dossier_signals: dict | None = None,
) -> dict[str, Any]:
    """Apply post-generation guards to a structured insight payload.

    Returns a *new* dict — the input is not mutated. Adds:
      - `post_validator_flags`: list of human-readable rewrite notes
      - `post_validator_version`: the validator version
    Demotes `priority_tier` from "high" to "medium" if compound legitimacy
    collapses (fewer than _HIGH_REQUIRES_DOMAINS cell-resolved domains).
    """
    out = dict(payload)
    flags: list[str] = []

    # ── Step 1+2: classify and strip city-broadcast domains ──────────────
    domains = list(out.get("domains_involved") or [])
    if domains:
        strip = set(_CITY_BROADCAST_DOMAINS)
        if _heat_is_city_broadcast(dossier_signals):
            strip.add("heat")
        cleaned = [d for d in domains if d.lower() not in strip]
        dropped = [d for d in domains if d.lower() in strip]
        if dropped:
            out["domains_involved"] = cleaned
            for d in dropped:
                flags.append(f"stripped_city_broadcast_domain:{d.lower()}")

    # ── Step 3: rewrite compound label in finding ────────────────────────
    finding = out.get("finding") or ""
    strip_label_tokens = set(_CITY_BROADCAST_LABEL_TOKENS)
    if _heat_is_city_broadcast(dossier_signals):
        strip_label_tokens.add("heat")
    new_finding, rewrite_note = _rewrite_compound_label(finding, strip_label_tokens)
    if rewrite_note:
        out["finding"] = new_finding
        flags.append(f"rewrote_compound_label:{rewrite_note}")

    # ── Step 4: tier demotion when compound legitimacy collapses ─────────
    tier = (out.get("priority_tier") or "").lower()
    if tier == "high":
        cell_resolved_n = len(out.get("domains_involved") or [])
        if cell_resolved_n < _HIGH_REQUIRES_DOMAINS:
            out["priority_tier"] = "medium"
            flags.append(
                f"demoted_tier:high→medium (only {cell_resolved_n} cell-resolved "
                f"domain after strip; need ≥{_HIGH_REQUIRES_DOMAINS})"
            )

    # ── Step 5: stamp audit trail ────────────────────────────────────────
    if flags:
        out["post_validator_flags"] = flags
        out["post_validator_version"] = VALIDATOR_VERSION
        logger.info(
            "Post-validator applied %d change(s): %s",
            len(flags), "; ".join(flags),
        )
    return out
