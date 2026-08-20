import sys, types, unittest
if "flask" not in sys.modules:
    f = types.ModuleType("flask"); f.jsonify = lambda x: x; f.request = None; sys.modules["flask"] = f

from cierny_kamen_global_reference import desired_description


META = "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\nČÍSLO OBRAZU: 01/01\n<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->"


class GlobalReferenceTests(unittest.TestCase):
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
