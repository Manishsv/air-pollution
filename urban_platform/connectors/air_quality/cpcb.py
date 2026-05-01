from __future__ import annotations

from typing import Any

import pandas as pd

from urban_platform.common.cache import with_source_metadata


def fetch_cpcb(config: Any) -> pd.DataFrame:
    """
    Stub for CPCB ingestion.

    Contract:
      - fetch raw data only
      - return a pandas DataFrame
      - attach source metadata
    """
    df = pd.DataFrame()
    return with_source_metadata(df, source="cpcb", retrieval_type="stub", details={"note": "Not implemented yet"})

