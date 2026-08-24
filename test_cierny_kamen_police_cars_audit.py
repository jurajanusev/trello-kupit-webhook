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

    def test_police_car_only_in_mobile_context_is_excluded(self):
        item = "**Alicin reportérsky mobil** — *na mieste je policajné auto*"
        self.assertIsNone(police_car_classification(item, "Alicin reportérsky mobil"))

    def test_owner_specific_river_car_is_not_police_candidate(self):
        self.assertIsNone(police_car_classification("**Auto Jakuba a Sáry** — *zastavia pri rieke*", "Auto Jakuba a Sáry"))


if __name__ == "__main__":
    unittest.main()
