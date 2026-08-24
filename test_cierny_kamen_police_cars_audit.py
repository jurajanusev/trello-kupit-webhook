import sys
import types
import unittest

flask = types.ModuleType("flask")
flask.jsonify = lambda value: value
flask.request = types.SimpleNamespace(headers={}, args={})
sys.modules.setdefault("flask", flask)

from cierny_kamen_police_cars_audit import police_car_classification


class PoliceCarClassificationTests(unittest.TestCase):
    def test_explicit_police_car_is_confirmed(self):
        self.assertEqual(police_car_classification("**Policajné auto** | KARTA: x"), "confirmed")

    def test_master_identity_can_confirm_item(self):
        self.assertEqual(police_car_classification("<n> **Zásahové vozidlo**", "Policajné auto pátracieho tímu"), "confirmed")

    def test_police_boat_is_excluded(self):
        self.assertIsNone(police_car_classification("**Policajný čln pátracieho tímu**"))

    def test_generic_river_car_is_ambiguous(self):
        self.assertEqual(police_car_classification("**Auto pri rieke**"), "ambiguous")

    def test_dialogue_mention_without_vehicle_identity_is_excluded(self):
        self.assertIsNone(police_car_classification("postava hovorí o polícii"))


if __name__ == "__main__":
    unittest.main()
