import unittest

import pandas as pd

from src.provenance import PROVENANCE_COLS, ensure_provenance_columns


class TestProvenance(unittest.TestCase):
    def test_ensure_provenance_columns_adds(self):
        df = pd.DataFrame({"a": [1, 2]})
        out = ensure_provenance_columns(df)
        for c in PROVENANCE_COLS:
            self.assertIn(c, out.columns)


if __name__ == "__main__":
    unittest.main()

