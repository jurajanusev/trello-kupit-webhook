import json
import sys
import types
import unittest

import extract_cierny_kamen_ep07_10 as extractor

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda value: value
    flask_stub.request = None
    sys.modules["flask"] = flask_stub

from cierny_kamen_ep07_10_import import (
    CHECKLIST_NAMES, SET_CHAINS, append_description_link,
    authoritative_payload, canonical_space_names,
    compatible_sample_checklists, ensure_attachments, folded,
    generated_checklist_prefix,
    merged_occurrence_links, prop_item_text,
    registry_aliases, registry_plan, runtime_state, set_chain_item,
    space_master_diff, space_registry_description,
)


class Ep0710ImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("cierny_kamen_ep07_10_scenes.json", encoding="utf-8") as stream:
            cls.payload = json.load(stream)

    def test_authoritative_counts_and_ids(self):
        self.assertEqual({"07": 51, "08": 47, "09": 51, "10": 51}, self.payload["episode_counts"])
        ids = [scene["scene_id"] for scene in self.payload["scenes"]]
        self.assertEqual(200, len(ids))
        self.assertEqual(200, len(set(ids)))

    def test_permanent_payload_extends_through_episode_10(self):
        from cierny_kamen_prop_identities import apply_identity_map
        from cierny_kamen_split_0440 import augment_payload
        with open("cierny_kamen_pdf_payload.json", encoding="utf-8") as stream:
            old_payload = json.load(stream)
        payload = authoritative_payload(augment_payload(apply_identity_map(old_payload)))
        ids = [scene["scene_id"] for scene in payload["scenes"]]
        self.assertEqual(514, len(ids))
        self.assertEqual(514, len(set(ids)))
        self.assertEqual(10, payload["stats"]["episodes"])
        self.assertEqual(47, payload["episode_counts"]["08"])
        self.assertEqual(181, sum(
            len(scene["props"]) for scene in payload["scenes"]
            if scene["episode"] >= 7
        ))

    def test_0807_is_flash_only(self):
        ids = {scene["scene_id"] for scene in self.payload["scenes"]}
        self.assertIn("08/07FLASH", ids)
        self.assertNotIn("08/07", ids)
        self.assertIn("08/09", ids)

    def test_special_headings_and_locations(self):
        scenes = {scene["scene_id"]: scene for scene in self.payload["scenes"]}
        self.assertEqual("ŠKOLA – CHODBA – KUMBÁL (LIMBO)", scenes["07/04"]["location"])
        self.assertEqual("ALEX, DOGY", scenes["07/04"]["characters_raw"])
        self.assertEqual("FEFE BEEF", scenes["08/07FLASH"]["location"])
        self.assertEqual("Kiko sa bozkáva s Noelom", __import__("cierny_kamen_split_0440").scene_0440()["prepis"])

    def test_every_scene_has_verbatim_payload(self):
        for scene in self.payload["scenes"]:
            self.assertTrue(scene["prepis"], scene["scene_id"])
            self.assertTrue(scene["action_raw"], scene["scene_id"])
            self.assertEqual(64, len(scene["action_sha256"]))

    def test_parallel_scenes_are_split_and_complete(self):
        scenes = {scene["scene_id"]: scene for scene in self.payload["scenes"]}
        for scene_id in ("08/20", "09/17", "10/03LP", "10/04LP", "10/11", "10/14", "10/20"):
            self.assertNotIn(scenes[scene_id]["action_raw"].strip().casefold(), {"paralelne", "parelelne"})
            self.assertGreater(len(scenes[scene_id]["action_raw"]), 40, scene_id)
        self.assertIn("Zoberte si z chladničky", scenes["08/20"]["action_raw"])
        self.assertIn("nechal som tam mobil", scenes["08/21"]["action_raw"])
        self.assertIn("Sára, všetci čakajú", scenes["09/17"]["action_raw"])
        self.assertIn("Jakub plynulým pohybom", scenes["09/18"]["action_raw"])
        self.assertIn("Tréning tanečnej skupiny", scenes["10/04LP"]["action_raw"])
        self.assertIn("Tréning basketbalistov", scenes["10/05LP"]["action_raw"])

    def test_registry_alias_normalization(self):
        card = {"name": "ŠKOLA – KLUBOVŇA", "desc": "KANONICKÝ NÁZOV: ŠKOLA – KLUBOVŇA\nALIASY: ŠKOLA - KLUBOVŇA"}
        self.assertEqual({folded("ŠKOLA – KLUBOVŇA")}, registry_aliases(card))

    def test_explicit_identity_map_is_evidence_backed(self):
        with open("cierny_kamen_ep07_10_identity_map.json", encoding="utf-8") as stream:
            identity = json.load(stream)
        scenes = {scene["scene_id"]: scene for scene in self.payload["scenes"]}
        self.assertGreaterEqual(identity["record_count"], 180)
        for record in identity["records"]:
            self.assertIn(record["evidence_phrase"].casefold(), scenes[record["scene_id"]]["action_raw"].casefold())
            self.assertTrue(record["stable_name"])
            if record["continuity_group"]:
                self.assertTrue(record["physical_presence"])

    def test_space_map_contains_reviewed_multi_space_headings(self):
        with open("cierny_kamen_ep07_10_space_map.json", encoding="utf-8") as stream:
            spaces = json.load(stream)
        self.assertEqual(3, len(spaces["VERONIKINA VILA – VSTUP/OBÝVAČKA/JEDÁLEŇ"]))
        self.assertEqual(["ALEXOV DOM – ALEXOVA IZBA"], spaces["ALEXOV DOM – ALIXOVA IZBA"])

    def test_prop_markdown_keeps_url_outside_italic(self):
        record = {
            "stable_name": "Betin osobný mobil", "action": "číta správu",
            "continuity_group": "betin-mobil", "previous": None,
            "next": "01/19", "current_state": "zapnutý displej",
            "categories": ["Osobná rekvizita", "Nadväzná rekvizita"],
        }
        value = prop_item_text(record, "https://trello.com/c/example")
        self.assertEqual(
            "<n> **Betin osobný mobil** — *číta správu | ← prvý výskyt | "
            "TU: zapnutý displej | → 01/19* | KARTA: https://trello.com/c/example",
            value,
        )
        self.assertFalse(value.endswith("*"))

    def test_checklist_order_is_permanent(self):
        self.assertEqual(
            ("REKVIZITY", "SET", "INFO Z PORADY", "INFO Z NATÁČANIA", "OTÁZKY NA PORADU"),
            CHECKLIST_NAMES,
        )

    def test_runtime_state_excludes_archived_history_from_card_limit(self):
        calls = []
        def trello_get(path, params):
            calls.append((path, dict(params)))
            if path.startswith("/boards/CzuD55PR") and path.count("/") == 2:
                return {"id": "board", "name": "Čierny Kameň"}
            if path == "/boards/board/lists":
                return [
                    {"id": "open-list", "name": "SCENÁRE", "closed": False},
                    {"id": "archived-list", "name": "SCENÁRE", "closed": True},
                ]
            if path == "/lists/open-list/cards":
                return [{"id": "card", "idList": "open-list"}]
            if path == "/search":
                return {"cards": [{"id": "alex-guitar", "closed": False}]}
            return []
        state = runtime_state({"trello_get": trello_get})
        self.assertEqual("board", state["board"]["id"])
        self.assertEqual({"card", "alex-guitar"}, {item["id"] for item in state["cards"]})
        card_call = next(item for item in calls if item[0] == "/lists/open-list/cards")
        self.assertEqual("open", card_call[1]["filter"])
        self.assertFalse(any(item[0] == "/lists/archived-list/cards" for item in calls))
        search_call = next(item for item in calls if item[0] == "/search")
        self.assertEqual("Alexova gitara od Lukáša", search_call[1]["query"])

    def test_existing_master_in_legacy_prop_list_is_reused(self):
        state = {
            "lists": [
                {"id": "legacy", "name": "NADVÄZNÉ REKVIZITY", "closed": False},
                {"id": "alex", "name": "ALEX – OS. REKVIZITY", "closed": False},
                {"id": "global", "name": "REGISTER REKVIZÍT", "closed": False},
            ],
            "cards": [{
                "id": "guitar", "name": "Alexova gitara", "desc": "",
                "idList": "legacy", "shortUrl": "https://trello.com/c/guitar",
                "closed": False,
            }],
        }
        identity = {"records": [{
            "stable_name": "Alexova gitara", "scene_id": "07/01LP",
            "physical_presence": True, "owner": "ALEX",
            "categories": ["Osobná rekvizita", "Nadväzná rekvizita"],
        }]}
        row = registry_plan(state, identity)[0]
        self.assertEqual("reuse", row["status"])
        self.assertEqual("ALEX – OS. REKVIZITY", row["target_list"])
        self.assertEqual("guitar", row["matches"][0]["id"])

    def test_backlink_merge_preserves_old_occurrences(self):
        old = "### VÝSKYTY\n- [06/47 – Starý výskyt](https://trello.com/c/old)"
        merged = merged_occurrence_links(old, [
            "- [06/47 – Starý výskyt](https://trello.com/c/old)",
            "- [08/41 – Nový výskyt](https://trello.com/c/new)",
        ])
        self.assertEqual(2, len(merged))
        self.assertIn("https://trello.com/c/old", merged[0])
        self.assertIn("https://trello.com/c/new", merged[1])

    def test_only_shape_identical_samples_can_receive_generated_item_fix(self):
        desired = [(name, ["new"] if name == "REKVIZITY" else []) for name in CHECKLIST_NAMES]
        actual = [(name, ["old"] if name == "REKVIZITY" else []) for name in CHECKLIST_NAMES]
        self.assertTrue(compatible_sample_checklists("09/35", actual, desired))
        self.assertFalse(compatible_sample_checklists("09/36", actual, desired))
        self.assertFalse(compatible_sample_checklists("09/35", actual[:-1], desired))

    def test_only_exact_generated_prefix_can_resume(self):
        desired = [(name, ["one", "two"] if name == "REKVIZITY" else []) for name in CHECKLIST_NAMES]
        self.assertTrue(generated_checklist_prefix([("REKVIZITY", ["one"])], desired))
        self.assertTrue(generated_checklist_prefix(desired[:3], desired))
        self.assertFalse(generated_checklist_prefix([("SET", [])], desired))
        self.assertFalse(generated_checklist_prefix([("REKVIZITY", ["manual"])], desired))

    def test_attachment_batch_reads_once_and_avoids_duplicates(self):
        posts = []
        api = {
            "trello_get": lambda path, params: [{"url": "https://trello.com/c/existing"}],
            "trello_post_body": lambda path, data: posts.append((path, data)),
        }
        added = ensure_attachments(api, {"id": "master"}, [
            ("https://trello.com/c/existing", "Existing"),
            ("https://trello.com/c/new", "New"),
            ("https://trello.com/c/new", "New duplicate"),
        ])
        self.assertEqual(1, added)
        self.assertEqual(1, len(posts))

    def test_only_confirmed_set_state_chains_are_mapped(self):
        self.assertEqual(2, len(SET_CHAINS))
        self.assertEqual(11, sum(len(item["occurrences"]) for item in SET_CHAINS))
        all_ids = {scene_id for chain in SET_CHAINS for scene_id, _ in chain["occurrences"]}
        self.assertNotIn("08/23", all_ids)
        self.assertNotIn("10/40", all_ids)
        value = set_chain_item(SET_CHAINS[0], 0, "https://trello.com/c/set")
        self.assertTrue(value.startswith("<n> **"))
        self.assertTrue(value.endswith("| KARTA: https://trello.com/c/set"))

    def test_set_master_link_is_appended_before_space_continuity(self):
        desc = "### ODKAZY\n- [Priestor](https://trello.com/c/space)\n\n### KONTINUITA PRIESTORU\n- Predchádzajúci: —"
        result = append_description_link(desc, "Oslava", "https://trello.com/c/set")
        self.assertIn("- [Oslava](https://trello.com/c/set)\n\n### KONTINUITA PRIESTORU", result)
        self.assertEqual(result, append_description_link(result, "Oslava", "https://trello.com/c/set"))

    def test_reused_space_master_preserves_display_punctuation(self):
        master_name = "DOM BETY – OBÝVAČKA"
        actual = space_registry_description(master_name).replace(
            "- Odkazy sa doplnia po vytvorení obrazových kariet.",
            "- Bez obrazového výskytu.",
        )
        state = {"cards": [{
            "id": "space", "name": master_name, "desc": actual,
        }]}
        row = {
            "name": "DOM BETY - OBÝVAČKA",
            "matches": [{"id": "space"}],
        }
        result = space_master_diff(state, row, [], {}, {})
        self.assertFalse(result["changed"])

    def test_space_alias_dash_variants_create_one_master_identity(self):
        payload = {"scenes": [
            {"scene_id": "01/01", "location": "A"},
            {"scene_id": "01/02", "location": "B"},
        ]}
        space_map = {
            "A": ["ŠKOLA - KLUBOVŇA"],
            "B": ["ŠKOLA – KLUBOVŇA"],
        }
        self.assertEqual(
            ["ŠKOLA - KLUBOVŇA"],
            canonical_space_names(payload, space_map),
        )


if __name__ == "__main__":
    unittest.main()
