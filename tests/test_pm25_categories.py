import unittest

from src.recommendations import pm25_category_india


class TestPM25Categories(unittest.TestCase):
    def test_category_mapping(self):
        cats = {
            "good": (0, 30),
            "satisfactory": (31, 60),
            "moderate": (61, 90),
            "poor": (91, 120),
            "very_poor": (121, 250),
            "severe": (251, 999),
        }
        self.assertEqual(pm25_category_india(10, cats), "good")
        self.assertEqual(pm25_category_india(35, cats), "satisfactory")
        self.assertEqual(pm25_category_india(75, cats), "moderate")
        self.assertEqual(pm25_category_india(110, cats), "poor")
        self.assertEqual(pm25_category_india(200, cats), "very_poor")
        self.assertEqual(pm25_category_india(400, cats), "severe")


if __name__ == "__main__":
    unittest.main()

