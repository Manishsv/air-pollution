from __future__ import annotations

from typing import Any

import pandas as pd

from urban_platform.common.cache import with_source_metadata


def fetch_firms(config: Any) -> pd.DataFrame:
    """
    Stub connector for NASA FIRMS active fire detections.

    This connector is introduced for platform layering and will be wired later.
    """
    df = pd.DataFrame()
    return with_source_metadata(df, source="firms", retrieval_type="stub", details={"note": "Not wired yet"})

