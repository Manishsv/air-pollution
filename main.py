from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from src.pipeline import run_pipeline


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    setup_logging()
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)

    cfg = load_config(Path(__file__).parent / "config.yaml")
    logging.getLogger(__name__).info(
        "Running air-quality MVP for city=%s mode=%s h3r=%s lookback_days=%s horizon=%sh",
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        cfg.lookback_days,
        cfg.forecast_horizon_hours,
    )
    outputs = run_pipeline(cfg)
    logging.getLogger(__name__).info("Done. Outputs:")
    for k, v in outputs.items():
        logging.getLogger(__name__).info("  %s: %s", k, v)


if __name__ == "__main__":
    main()

