"""AirOS batch scheduler — ingest + agent loop.

Runs as a long-lived process (``python main.py --step scheduler``).

How it works
------------
A single background thread wakes every SWEEP_INTERVAL seconds and:

  1. Ingest sweep — calls ingestor.run() for every (city, domain).
     The ingestor's watermark logic (_check_interval / _TooRecentError)
     silently skips any domain that was run too recently, so each domain
     is effectively pulled at its own configured frequency:

         air / fire        — every 15 min
         heat              — every 30 min
         flood/water/waste — every 1 h
         construction/
         green/noise       — every 6 h

  2. Agent sweep — runs the H3 Expert Agent for the top-N risk cells per
     city that don't already have a recent insight (agent's own 6-hour
     dedup guard).

The scheduler writes a JSON status file (data/scheduler_status.json) after
every sweep so the dashboard can display health without querying the process.

Configuration (via .env)
------------------------
SCHEDULER_CITIES   comma-separated city IDs  (default: all)
SCHEDULER_DOMAINS  comma-separated domains   (default: all)
SCHEDULER_AGENT    true/false — whether to run the agent after each sweep
                   (default: true)
SCHEDULER_TOP_N    how many top-risk cells to pass to the agent per city
                   (default: 10)
SWEEP_INTERVAL_SEC seconds between sweeps (default: 900 = 15 min)
"""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE        = Path(__file__).resolve().parent   # airos/os/
PROJECT_ROOT = _HERE.parents[1]                  # airos/os/ → 2 levels up → repo root
STATUS_FILE  = PROJECT_ROOT / "data" / "scheduler_status.json"

DEFAULT_SWEEP_INTERVAL = 900   # 15 minutes — matches the shortest domain interval
DEFAULT_AGENT_TOP_N    = 10


# ---------------------------------------------------------------------------
# Status file helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_status(state: dict) -> None:
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(state, indent=2))
    except Exception as exc:
        logger.debug("Could not write scheduler status: %s", exc)


def read_status() -> dict:
    """Read the last written scheduler status (for the dashboard)."""
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text())
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Sweep helpers
# ---------------------------------------------------------------------------

def _run_ingest(cities: list[str], domains: list[str]) -> dict:
    """Run one ingest sweep. Returns {city: {domain: rows}} summary."""
    from airos.drivers.store.ingestor import run as ingestor_run
    try:
        return ingestor_run(cities=cities, domains=domains, force=False)
    except Exception as exc:
        logger.error("Ingest sweep error: %s", exc)
        return {}


def _run_geocode_catchup(batch_size: int = 60) -> dict:
    """Process a small batch of cells with missing area_name via Nominatim.

    Lets newly onboarded cities get reverse-geocoded automatically over a
    few hours of normal scheduler operation — no manual step.
    Nominatim is rate-limited at 1.1s/call, so we cap the batch so it
    never exceeds ~70s of wall time per sweep. Returns {"done", "cached",
    "failed"} aggregated across whatever cities had pending cells.
    """
    from airos.drivers.store.geocoder import geocode_all_cells
    try:
        out = geocode_all_cells(limit=batch_size)
    except Exception as exc:
        logger.warning("[geocode] catch-up failed: %s", exc)
        return {}
    if not out:
        return {}
    total = {"done": 0, "cached": 0, "failed": 0}
    for city, stats in out.items():
        for k in total:
            total[k] += int(stats.get(k, 0))
    if total["done"] or total["cached"]:
        logger.info(
            "[geocode] catch-up: %d cell(s) named, %d cached, %d failed "
            "across %d city(s)", total["done"], total["cached"],
            total["failed"], len(out),
        )
    return total


def _run_agent(cities: list[str], top_n: int) -> dict:
    """Run the H3 Expert Agent for each city. Returns {city: insights_count}."""
    from airos.agents.h3_expert import run_top_risk_cells
    from airos.agents.llm_config import load_config
    try:
        cfg = load_config()
    except Exception:
        cfg = None

    results: dict[str, int] = {}
    for city_id in cities:
        try:
            insights = run_top_risk_cells(city_id, top_n=top_n, config=cfg)
            n = len([r for r in insights if r.get("insight_id")])
            results[city_id] = n
            if n:
                logger.info("[agent] %s — %d new insight(s)", city_id, n)
            else:
                logger.debug("[agent] %s — no new cells eligible", city_id)
        except Exception as exc:
            logger.warning("[agent] %s error: %s", city_id, exc)
            results[city_id] = 0
    return results


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """Runs ingest + agent sweeps on a fixed interval in a daemon thread."""

    def __init__(
        self,
        *,
        cities:          list[str] | None = None,
        domains:         list[str] | None = None,
        sweep_interval:  int  = DEFAULT_SWEEP_INTERVAL,
        run_agent:       bool = True,
        agent_top_n:     int  = DEFAULT_AGENT_TOP_N,
    ) -> None:
        from airos.drivers.store.ingestor import ALL_CITIES, ALL_DOMAINS

        self.cities         = cities  or ALL_CITIES
        self.domains        = domains or ALL_DOMAINS
        self.sweep_interval = sweep_interval
        self.run_agent      = run_agent
        self.agent_top_n    = agent_top_n

        self._stop_event    = threading.Event()
        self._thread: threading.Thread | None = None
        self._sweep_count   = 0

    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("Scheduler already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="airos-scheduler", daemon=True
        )
        self._thread.start()
        logger.info(
            "Scheduler started — %d cities, %d domains, sweep every %ds",
            len(self.cities), len(self.domains), self.sweep_interval,
        )

    def stop(self) -> None:
        logger.info("Scheduler stopping…")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Main scheduler loop — runs until stop() is called."""
        _write_status({
            "state":        "starting",
            "started_at":   _now_iso(),
            "sweep_count":  0,
            "cities":       self.cities,
            "domains":      self.domains,
            "sweep_interval_sec": self.sweep_interval,
        })

        # Run immediately on start, then every sweep_interval
        while not self._stop_event.is_set():
            self._sweep()
            # Sleep in small increments so stop() is responsive
            deadline = time.monotonic() + self.sweep_interval
            while time.monotonic() < deadline and not self._stop_event.is_set():
                time.sleep(5)

        _write_status({**read_status(), "state": "stopped", "stopped_at": _now_iso()})
        logger.info("Scheduler stopped.")

    def _sweep(self) -> None:
        self._sweep_count += 1
        sweep_start = _now_iso()
        logger.info("=== Sweep #%d started ===", self._sweep_count)

        _write_status({
            **read_status(),
            "state":          "sweeping",
            "sweep_count":    self._sweep_count,
            "sweep_started":  sweep_start,
        })

        # 1 — Ingest
        ingest_results = _run_ingest(self.cities, self.domains)
        total_rows = sum(
            n for dm in ingest_results.values()
            for n in dm.values() if isinstance(n, int) and n > 0
        )
        logger.info("Sweep #%d ingest: %d rows written", self._sweep_count, total_rows)

        # 1a' — Airshed-scale ingest. For every enabled non-city AOI
        # (kind ∈ airshed/watershed/corridor/...), runs the AOI's
        # declared domain subset at the AOI's H3 resolution across
        # its full bbox. Currently supports air + fire; weather/heat/
        # water still tracked as TBD (need bbox-grid connector mode).
        try:
            from airos.drivers.store.airshed_ingestor import run_airshed_ingest_sweep
            ai_results = run_airshed_ingest_sweep()
            ai_rows = sum(n for dm in ai_results.values() for n in dm.values()
                          if isinstance(n, int) and n > 0)
            if ai_rows:
                logger.info(
                    "Sweep #%d airshed ingest: %d rows across %d AOI(s)",
                    self._sweep_count, ai_rows, len(ai_results),
                )
        except Exception as exc:
            logger.warning("[airshed-ingest] step failed: %s", exc)

        # 1b — Reverse-geocode pending cells (newly onboarded cities get
        # named automatically over a few hours of normal sweep operation).
        # Capped at 60 cells/sweep (~66s at Nominatim's 1.1s rate limit).
        _run_geocode_catchup(batch_size=60)

        # 1c — Airshed-scale composition (Phase 3 items 2+3). Reads cells
        # already ingested by the per-city sweeps above and computes
        # UPWIND_PM25_LOAD_REGIONAL (~200 km, bearing-based) for every cell
        # inside any enabled airshed/watershed/corridor AOI. Cheap (<1s
        # for ~5k cells) and no-op when no non-city AOIs are enabled.
        try:
            from airos.os.airshed_compositor import run_airshed_composition
            run_airshed_composition()
        except Exception as exc:
            logger.warning("[airshed] composition step failed: %s", exc)

        # 2 — Agent (if enabled)
        agent_results: dict = {}
        if self.run_agent:
            agent_results = _run_agent(self.cities, self.agent_top_n)
            total_insights = sum(agent_results.values())
            if total_insights:
                logger.info("Sweep #%d agent: %d new insight(s)", self._sweep_count, total_insights)

        # 2c — Airshed agent (Phase 4+). For every enabled non-city AOI,
        # runs the airshed-expert agent on its top-N res-`AOI` parent
        # cells (default 10, override via AIRSHED_INSIGHTS_TOP_N env var
        # or disable entirely via AIRSHED_INSIGHTS_DISABLED=1). One LLM
        # call per parent; produces regional-scale insights routed to
        # airshed bodies (CPCB Central / NCAP).
        if self.run_agent:
            try:
                from airos.agents.airshed_expert import run_airshed_insights
                airshed_results = run_airshed_insights()
                total_airshed = sum(airshed_results.values())
                if total_airshed:
                    logger.info(
                        "Sweep #%d airshed agent: %d insight(s) across %d AOI(s)",
                        self._sweep_count, total_airshed, len(airshed_results),
                    )
            except Exception as exc:
                logger.warning("[airshed-agent] step failed: %s", exc)

        # 2b — Process on-demand analysis requests (max 3 per sweep)
        analysis_completed = 0
        try:
            from airos.drivers.store.reader import get_pending_requests
            from airos.drivers.store.writer import update_request_status
            from airos.agents.h3_expert import H3ExpertAgent
            from airos.agents.llm_config import load_config as _load_cfg

            pending_df = get_pending_requests(limit=3)
            if not pending_df.empty:
                try:
                    _cfg = _load_cfg()
                except Exception:
                    _cfg = None
                for _, req in pending_df.iterrows():
                    rid      = req["request_id"]
                    h3_id    = req["h3_id"]
                    req_city = req["city_id"]
                    update_request_status(rid, "running")
                    try:
                        result = H3ExpertAgent(h3_id=h3_id, city_id=req_city, config=_cfg).run()
                        update_request_status(rid, "completed", insight_id=result.get("insight_id"))
                        analysis_completed += 1
                        logger.info("[analysis] %s/%s — completed, insight: %s",
                                    req_city, h3_id, result.get("insight_id", "none"))
                    except Exception as exc:
                        update_request_status(rid, "failed", error_msg=str(exc))
                        logger.warning("[analysis] %s/%s — failed: %s", req_city, h3_id, exc)
        except Exception as exc:
            logger.warning("Analysis request sweep error: %s", exc)

        # 2c — City pattern synthesis (runs after agent sweep)
        # SPEC: City Pattern Agent MUST be skipped if fewer than 3 new insights
        # were produced in the current sweep (AGENT_INTERFACE §City Pattern Agent §Skip condition).
        _MIN_INSIGHTS_FOR_PATTERN = 3
        _total_new_insights = sum(agent_results.values())
        city_pattern_results: dict[str, int] = {}
        if self.run_agent and _total_new_insights >= _MIN_INSIGHTS_FOR_PATTERN:
            try:
                from airos.agents.city_pattern_agent import CityPatternAgent
                from airos.agents.llm_config import load_config as _load_cfg2
                try:
                    _pcfg = _load_cfg2()
                except Exception:
                    _pcfg = None
                for city_id in self.cities:
                    try:
                        pattern_agent = CityPatternAgent(
                            city_id,
                            lookback_hours=2,  # insights from this sweep + recent
                            config=_pcfg,
                        )
                        result = pattern_agent.run()
                        n_themes = len(result.get("themes", []))
                        city_pattern_results[city_id] = n_themes
                        if n_themes:
                            logger.info(
                                "[city-pattern] %s — %d theme(s) identified",
                                city_id, n_themes,
                            )
                    except Exception as exc:
                        logger.warning("[city-pattern] %s — error: %s", city_id, exc)
                        city_pattern_results[city_id] = 0
            except ImportError:
                pass  # city_pattern_agent module not available — skip

        # 2d — Promote high-priority insights → decision packets
        try:
            from airos.os.insight_packets import InsightPacketGenerator
            new_packets = InsightPacketGenerator().generate(city_ids=self.cities)
            if new_packets:
                logger.info("Sweep #%d packets: %d new decision packet(s) promoted from insights",
                            self._sweep_count, new_packets)
        except Exception as exc:
            logger.warning("Insight packet promotion error: %s", exc)

        # 3 — Sensor siting batch (monthly cadence, self-gating via siting_log watermark)
        siting_results: dict = {}
        try:
            from airos.drivers.store.ingestor import run_siting_batch
            siting_results = run_siting_batch(cities=self.cities)
            written = sum(
                n for dm in siting_results.values()
                for n in dm.values() if isinstance(n, int) and n > 0
            )
            if written:
                logger.info("Sweep #%d siting: %d candidates (re)computed", self._sweep_count, written)
        except Exception as exc:
            logger.warning("Siting batch error: %s", exc)

        # 3b — Data quality coverage gaps (runs every sweep; cheap — pure SQL aggregation)
        # Computes DATA_CONFIDENCE-based gap clusters and populates h3_siting_candidates.
        # For sensor_list domains only — query_driven sources always have confidence = 1.0.
        # Runs immediately on first sweep so the Sensor Coverage dashboard is never empty.
        dq_candidates: dict[str, int] = {}
        try:
            from airos.drivers.store.data_quality import populate_siting_candidates
            for city_id in self.cities:
                try:
                    n = populate_siting_candidates(city_id)
                    dq_candidates[city_id] = n
                    if n:
                        logger.info(
                            "[dq] %s — %d coverage gap candidate(s) updated",
                            city_id, n,
                        )
                except Exception as city_exc:
                    logger.warning("[dq] %s — siting update failed: %s", city_id, city_exc)
        except ImportError:
            pass  # data_quality module not yet available — skip silently

        # 4 — Write status
        siting_candidates = sum(
            n for dm in siting_results.values()
            for n in dm.values() if isinstance(n, int) and n > 0
        ) + sum(dq_candidates.values())
        _write_status({
            "state":          "idle",
            "sweep_count":    self._sweep_count,
            "last_sweep_at":  sweep_start,
            "last_sweep_rows": total_rows,
            "last_sweep_insights": sum(agent_results.values()),
            "last_analysis_completed": analysis_completed,
            "last_city_pattern_themes": sum(city_pattern_results.values()),
            "last_siting_candidates": siting_candidates,
            "next_sweep_at":  _next_sweep_iso(self.sweep_interval),
            "cities":         self.cities,
            "domains":        self.domains,
            "sweep_interval_sec": self.sweep_interval,
            "agent_enabled":  self.run_agent,
            "ingest_summary": {
                city: {d: n for d, n in dm.items()}
                for city, dm in ingest_results.items()
            },
        })
        logger.info("=== Sweep #%d done ===", self._sweep_count)


def _next_sweep_iso(interval_sec: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(seconds=interval_sec)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# ---------------------------------------------------------------------------
# Entry point (called from main.py --step scheduler)
# ---------------------------------------------------------------------------

def run_forever() -> None:
    """Start the scheduler and block until SIGINT/SIGTERM."""
    # Read config from env
    raw_cities  = os.environ.get("SCHEDULER_CITIES",  "").strip()
    raw_domains = os.environ.get("SCHEDULER_DOMAINS", "").strip()
    run_agent   = os.environ.get("SCHEDULER_AGENT",   "true").lower() != "false"
    top_n       = int(os.environ.get("SCHEDULER_TOP_N",    str(DEFAULT_AGENT_TOP_N)))
    interval    = int(os.environ.get("SWEEP_INTERVAL_SEC", str(DEFAULT_SWEEP_INTERVAL)))

    from airos.drivers.store.ingestor import ALL_CITIES, ALL_DOMAINS
    cities  = [c.strip() for c in raw_cities.split(",")  if c.strip()] or ALL_CITIES
    domains = [d.strip() for d in raw_domains.split(",") if d.strip()] or ALL_DOMAINS

    scheduler = Scheduler(
        cities=cities,
        domains=domains,
        sweep_interval=interval,
        run_agent=run_agent,
        agent_top_n=top_n,
    )
    scheduler.start()

    # Handle Ctrl+C and SIGTERM gracefully
    def _shutdown(sig, frame):
        logger.info("Signal %s received — shutting down scheduler…", sig)
        scheduler.stop()

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "AirOS scheduler running. Cities: %s | Domains: %s | "
        "Sweep: every %ds | Agent: %s | Top-N: %d",
        ", ".join(cities), ", ".join(domains), interval,
        "enabled" if run_agent else "disabled", top_n,
    )
    logger.info("Press Ctrl+C to stop.")

    # Keep main thread alive
    while scheduler.is_running():
        time.sleep(1)
