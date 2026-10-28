import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / 'utils.py'
spec = importlib.util.spec_from_file_location('fm_utils_test', source)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)


class TestBusinessFormulas(unittest.TestCase):
    def test_replenish_15(self):
        self.assertEqual(utils.replenish_quantity(40, 25, 30), 15)

    def test_replenish_limited_by_stock(self):
        self.assertEqual(utils.replenish_quantity(40, 25, 8), 8)

    def test_shelf_full(self):
        self.assertEqual(utils.replenish_quantity(40, 40, 30), 0)

    def test_normalize_headers(self):
        self.assertEqual(utils.normalize_column('Mã barcode'), 'mabarcode')
        self.assertEqual(utils.normalize_column('Số lượng'), 'soluong')


if __name__ == '__main__':
    unittest.main()
