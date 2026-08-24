import sys
import types
import unittest

flask = types.ModuleType("flask")
flask.jsonify = lambda value: value
flask.request = types.SimpleNamespace(headers={}, args={})
sys.modules.setdefault("flask", flask)

from cierny_kamen_vehicles import identity_text, vehicle_kind


class VehicleTests(unittest.TestCase):
    def test_distinguishes_vehicle_kinds(self):
        self.assertEqual(vehicle_kind("Policajné auto pri rieke"), "police_car")
        self.assertEqual(vehicle_kind("Taxík privážajúci Sofiu"), "taxi")
        self.assertEqual(vehicle_kind("Drevená pramica Jakuba a Sáry"), "watercraft")
        self.assertEqual(vehicle_kind("Pohrebné auto"), "hearse")

    def test_automatic_snack_machine_is_not_vehicle(self):
        self.assertIsNone(vehicle_kind("Automat na snacky"))

    def test_vehicle_related_components_are_not_vehicles(self):
        self.assertIsNone(vehicle_kind("maják na Kelerové auto"))
        self.assertIsNone(vehicle_kind("plachta tmavej farby ktorou je auto prekryté"))
        self.assertIsNone(vehicle_kind("drôt s ktorým Bety otvorí Olasovej auto"))
        self.assertIsNone(vehicle_kind("rozpísaná Sárina pohrebná reč"))

    def test_identity_ignores_context(self):
        self.assertEqual(identity_text("<n> **Policajné auto** — *jazdí pri rieke*"), "Policajné auto")


if __name__ == "__main__":
    unittest.main()
