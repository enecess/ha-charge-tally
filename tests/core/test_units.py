import unittest
from decimal import Decimal

from custom_components.charge_tally.core.units import energy_kwh, power_w, price_per_kwh


class UnitsTests(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(energy_kwh("1234", "Wh"), Decimal("1.234"))
        self.assertEqual(energy_kwh("2", "MWh"), Decimal("2000"))
        self.assertEqual(power_w("1.2", "kW"), Decimal("1200"))
        self.assertEqual(power_w("2", "MW"), Decimal("2000000"))
        self.assertEqual(price_per_kwh("-0.001", "CNY/Wh", "CNY"), Decimal("-1"))
        self.assertEqual(price_per_kwh("100", "USD/MWh", "USD"), Decimal(".1"))
        self.assertEqual(price_per_kwh(0, "CNY/kWh", "CNY"), 0)

    def test_rejects_invalid_and_nonfinite(self):
        for value in [None, True, "", "unknown", "NaN", "Infinity", "-Infinity", "-1"]:
            for fn, unit in [(energy_kwh, "kWh"), (power_w, "W")]:
                with self.subTest(fn=fn, value=value), self.assertRaises(ValueError):
                    fn(value, unit)
        for args in [
            ("NaN", "CNY/kWh", "CNY"),
            (1, "USD/kWh", "CNY"),
            (1, "CNY/W", "CNY"),
        ]:
            with self.assertRaises(ValueError):
                price_per_kwh(*args)
        with self.assertRaises(ValueError):
            energy_kwh(1, "J")
