import unittest
import sys
import types


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_set_registry_audit import (
    N_PREFIX,
    base_card_url,
    expected_set_scenes,
    marker_key,
)


class SetRegistryAuditTests(unittest.TestCase):
    def test_lowercase_n_prefix_only(self):
        self.assertTrue(N_PREFIX.match("<n> set — state"))
        self.assertFalse(N_PREFIX.match("<N> set — state"))
        self.assertFalse(N_PREFIX.match("ordinary set"))

    def test_card_url_is_normalized_from_item(self):
        self.assertEqual(
            base_card_url("KARTA: https://trello.com/c/Ab12Cd34/card-name"),
            "https://trello.com/c/Ab12Cd34",
        )
        self.assertIsNone(base_card_url("KARTA: pending"))

    def test_registry_marker(self):
        self.assertEqual(marker_key({
            "desc": "<!-- CIERNY-KAMEN-REGISTRY:SET:broken-glass -->"
        }), "broken-glass")

    def test_expected_chains_use_only_continuity_items(self):
        payload = {"scenes": [{
            "scene_id": "01/01",
            "set_items": [
                {"continuity": True, "registry_key": "chain"},
                {"continuity": False, "registry_key": "ordinary"},
            ],
        }]}
        self.assertEqual(expected_set_scenes(payload), {"chain": ["01/01"]})


if __name__ == "__main__":
    unittest.main()

