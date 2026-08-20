import sys, types, unittest
if "flask" not in sys.modules:
    f = types.ModuleType("flask"); f.jsonify = lambda x: x; f.request = None; sys.modules["flask"] = f

from cierny_kamen_global_reference import ENDPOINT_DISABLED, _scene_groups, desired_description


META = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\nČÍSLO OBRAZU: 01/01\n<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"


class GlobalReferenceTests(unittest.TestCase):
    def test_one_time_endpoint_is_disabled(self):
        self.assertTrue(ENDPOINT_DISABLED)

    def test_original_screener_cards_are_excluded(self):
        state = {
            "lists_by_id": {"prod": {"name": "SCENÁRE"}, "old": {"name": "original screener"}},
            "cards": [{"id": "p", "idList": "prod", "name": "01/01 x"},
                      {"id": "o", "idList": "old", "name": "01/01 y"}],
        }
        api = {"cierny_kamen_scene_name_info": lambda name: {"scene_id": "01/01", "test": False}}
        self.assertEqual(["p"], [row["id"] for row in _scene_groups(api, state)["01/01"]])

    def test_legacy_layout_becomes_compact_and_preserves_manual_action_metadata(self):
        desc = """## Titul

### REKVIZITY V KONTEXTE
- **Mobil** — používa ho

### NADVAZNOSŤ
- Bez potvrdenej nadväznosti.

### ODKAZY
- Mobil: https://trello.com/c/Abc123

### KONTINUITA PRIESTORU
- Predchádzajúci: —
- Nasledujúci: —

### KONTINUITA POSTÁV
- BETY: ← — | → —

### RUČNÉ DOPLNENIA
moja poznámka

### AKCIA A DIALÓGY
*Presný text.*

""" + META
        desired, conflict, preserved = desired_description(desc, [{"name": "Mobil | KARTA: https://trello.com/c/Abc123"}])
        self.assertIsNone(conflict)
        self.assertIn("## NAVIGÁCIA", desired)
        self.assertNotIn("REKVIZITY V KONTEXTE", desired)
        self.assertIn("moja poznámka", desired)
        self.assertIn("*Presný text.*", desired)
        self.assertTrue(desired.endswith(META))
        self.assertEqual([], preserved)
        again, conflict, _ = desired_description(desired, [])
        self.assertIsNone(conflict)
        self.assertEqual(desired, again)


if __name__ == "__main__": unittest.main()
