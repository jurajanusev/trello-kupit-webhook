import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_props_0101_0115 import SCENE_IDS, exact_named


class Props01010115Tests(unittest.TestCase):
    def test_scope_has_exactly_fifteen_scenes(self):
        self.assertEqual(len(SCENE_IDS), 15)
        self.assertIn("01/11FLASH", SCENE_IDS)

    def test_exact_name_is_case_and_accent_insensitive(self):
        items = [{"name": "REGISTER REKVIZÍT"}, {"name": "Other"}]
        self.assertEqual(
            exact_named(items, "register rekvizit"), [items[0]]
        )


if __name__ == "__main__":
    unittest.main()
