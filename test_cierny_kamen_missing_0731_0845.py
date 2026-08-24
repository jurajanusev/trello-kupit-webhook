import sys
import types
import unittest

flask = types.ModuleType("flask")
flask.jsonify = lambda value: value
flask.request = types.SimpleNamespace(headers={}, args={})
sys.modules.setdefault("flask", flask)

import cierny_kamen_missing_0731_0845 as target


class MissingScenesTest(unittest.TestCase):
    def test_target_sources_are_exact_and_unique(self):
        _, scenes = target._target_payload()
        self.assertEqual([row["scene_id"] for row in scenes], list(target.TARGET_IDS))
        self.assertEqual(len({row["scene_id"] for row in scenes}), 4)
        self.assertEqual(scenes[0]["prepis"], "Veronika sa zabáva na diskotéke")
        self.assertEqual(scenes[1]["prepis"], "Veronika trestá mamu")
        self.assertEqual(scenes[2]["prepis"], "Laura Veronike zablokovala kartu")
        self.assertEqual(scenes[3]["prepis"], "Sofia prichádza k Révayovcom")

    def test_curated_props_are_identity_first(self):
        records = target._records_for_targets()
        names = {row["stable_name"] for row in records}
        self.assertIn("Kikov osobný mobil", names)
        self.assertIn("Čas 21:50 na Kikovom mobile", names)
        self.assertIn("Veronikina platobná karta", names)
        self.assertIn("Taxík privážajúci Sofiu k Révayovcom", names)
        self.assertIn("Sofiin kufrík k Révayovcom", names)
        self.assertFalse(any(name in {"Mobil", "Auto", "Karta", "Kufor"} for name in names))

    def test_auto_and_personal_targets(self):
        rows = target._records_for_targets()
        taxi = next(row for row in rows if "Taxík" in row["stable_name"])
        mobile = next(row for row in rows if row["stable_name"] == "Kikov osobný mobil")
        screen = next(row for row in rows if row["stable_name"].startswith("Čas 21:50"))
        self.assertEqual(target._target_list_name(taxi), "AUTÁ")
        self.assertEqual(target._target_list_name(mobile), "KIKO – OS. REKVIZITY")
        self.assertEqual(target._target_list_name(screen), "REGISTER REKVIZÍT")


if __name__ == "__main__":
    unittest.main()
