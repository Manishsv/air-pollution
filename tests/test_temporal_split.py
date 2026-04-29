import unittest
from datetime import datetime, timezone, timedelta

import pandas as pd

from src.model import _time_split


class TestTemporalSplit(unittest.TestCase):
    def test_strict_temporal_split(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base + timedelta(hours=i) for i in range(10)]
        df = pd.DataFrame({"timestamp": ts, "x": range(10)})
        train, test = _time_split(df, test_fraction=0.2)
        self.assertTrue(train["timestamp"].max() < test["timestamp"].min())
        # last 20% of 10 timestamps = last 2 in test
        self.assertEqual(len(test["timestamp"].unique()), 2)


if __name__ == "__main__":
    unittest.main()

