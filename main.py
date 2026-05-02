from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from urban_platform.applications.air_pollution.pipeline import run_air_pollution_pipeline
from urban_platform.specifications.audit import run_conformance_audit
from urban_platform.specifications.engine import list_conformance_result_violations


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    setup_logging()
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)

    ap = argparse.ArgumentParser(description="Probabilistic urban air-quality observability MVP")
    ap.add_argument("--sample", action="store_true", help="Run in sample mode (limits OSM features)")
    ap.add_argument("--force-refresh", choices=["none", "aq", "all"], default="none", help="Bypass caches for scope")
    ap.add_argument(
        "--step",
        choices=["all", "audit", "model", "visualize", "sensor-siting", "conformance"],
        default="all",
        help="Stop after a step (sensor-siting reads existing outputs)",
    )
    ap.add_argument(
        "--sensor-siting-mode",
        choices=["coverage", "hotspot_discovery", "equity"],
        default=None,
        help="Override config sensor_siting.mode (coverage prioritizes distant/interpolated; equity uses urban proxies)",
    )
    ap.add_argument("--no-recommendations", action="store_true", help="Disable operational recommendations")
    args = ap.parse_args()

    if args.step == "conformance":
        log = logging.getLogger(__name__)
        report = run_conformance_audit(Path(__file__).parent)
        log.info("Wrote conformance report to %s", Path(__file__).parent / "data" / "outputs" / "conformance_report.json")
        results = report.get("results") or []
        log.info("Validated %s checks", len(results))
        violations = list_conformance_result_violations(results)
        if violations:
            log.error(
                "Conformance failed: %s required check(s) invalid (non-skipped status!=valid or error_count>0)",
                len(violations),
            )
            for line in violations[:40]:
                log.error("  %s", line)
            if len(violations) > 40:
                log.error("  ... and %s more", len(violations) - 40)
            raise SystemExit(1)
        return

    cfg = load_config(Path(__file__).parent / "config.yaml")
    logging.getLogger(__name__).info(
        "Running air-quality MVP for city=%s mode=%s h3r=%s lookback_days=%s horizon=%sh",
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        cfg.lookback_days,
        cfg.forecast_horizon_hours,
    )
    outputs = run_air_pollution_pipeline(
        cfg,
        step=args.step,
        refresh_scope=args.force_refresh,
        no_recommendations=bool(args.no_recommendations),
        sample_mode_override=True if args.sample else None,
        sensor_siting_mode=args.sensor_siting_mode,
    )
    logging.getLogger(__name__).info("Done. Outputs:")
    for k, v in outputs.items():
        logging.getLogger(__name__).info("  %s: %s", k, v)


if __name__ == "__main__":
    main()

