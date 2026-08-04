import sys
import types
import unittest


if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_all_props_registry import CATEGORY_LABELS, exact_named


class AllPropsRegistryTests(unittest.TestCase):
    def test_required_labels_are_explicit(self):
        self.assertEqual(len(CATEGORY_LABELS), 6)
        self.assertIn("Nadväzný priestor", CATEGORY_LABELS)

    def test_exact_names_ignore_case_and_accents(self):
        values = [{"name": "REGISTER REKVIZÍT"}, {"name": "Other"}]
        self.assertEqual(exact_named(values, "register rekvizit"), [values[0]])


if __name__ == "__main__":
    unittest.main()
