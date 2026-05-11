from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from airos.os.common.config import load_config
from airos.os.specifications.audit import run_conformance_audit
from airos.os.specifications.engine import list_conformance_result_violations


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
        choices=["all", "audit", "model", "visualize", "sensor-siting", "conformance",
                 "ingest-h3", "geocode-h3", "scheduler"],
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
    ap.add_argument("--overwrite", action="store_true",
                    help="geocode-h3: re-geocode cells that already have an area name")
    ap.add_argument("--city", default=None,
                    help="geocode-h3: restrict to a single city id (e.g. bangalore)")
    ap.add_argument("--cities", nargs="+", default=None, metavar="CITY",
                    help="ingest-h3: city ids to ingest (default: all configured cities)")
    ap.add_argument("--domains", nargs="+", default=None, metavar="DOMAIN",
                    help="ingest-h3: domain names to ingest (default: all domains)")
    ap.add_argument("--force", action="store_true",
                    help="ingest-h3: bypass the watermark interval and re-ingest")
    args = ap.parse_args()

    if args.step == "scheduler":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
        from airos.os.scheduler import run_forever
        run_forever()
        return

    if args.step == "ingest-h3":
        import logging as _logging
        _logging.basicConfig(level=_logging.INFO,
                             format="%(asctime)s %(levelname)s %(name)s — %(message)s",
                             datefmt="%H:%M:%S")
        from airos.drivers.store.ingestor import run as _h3_run, ALL_CITIES, ALL_DOMAINS
        cities  = getattr(args, "cities",  None) or ALL_CITIES
        domains = getattr(args, "domains", None) or ALL_DOMAINS
        force   = getattr(args, "force",   False)
        results = _h3_run(cities=cities, domains=domains, force=force)
        total = sum(n for dm in results.values() for n in dm.values() if n > 0)
        print(f"\nH3 ingest complete — {total} rows written across "
              f"{len(results)} cities × {len(domains)} domains")
        return

    if args.step == "geocode-h3":
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
                            datefmt="%H:%M:%S")
        from airos.drivers.store.geocoder import geocode_all_cells, geocode_summary
        overwrite = getattr(args, "overwrite", False)
        city_arg  = getattr(args, "city", None)
        # Print coverage before
        pre = geocode_summary(city_id=city_arg)
        if not pre.empty:
            print("\nCurrent coverage (before geocoding):")
            print(pre.to_string(index=False))
        results = geocode_all_cells(city_id=city_arg, overwrite=overwrite)
        if results:
            print("\nGeocoding results:")
            for city, counts in sorted(results.items()):
                print(f"  {city}: {counts['done']} named, {counts['failed']} failed")
        # Print coverage after
        post = geocode_summary(city_id=city_arg)
        if not post.empty:
            print("\nCoverage after geocoding:")
            print(post.to_string(index=False))
        return

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
        "Config loaded for city=%s mode=%s h3r=%s",
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
    )


if __name__ == "__main__":
    main()

