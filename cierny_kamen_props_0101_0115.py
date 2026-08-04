from __future__ import annotations

import unicodedata

from flask import jsonify, request

from cierny_kamen_reference_0116 import normalize_name, stable_hash
from cierny_kamen_reference_all import board_support_data, protected_card_value


KEY = "cierny-kamen-props-0101-0115-4aug-7d64c8a1"
SCENE_IDS = (
    "01/01", "01/02LP", "01/03LP", "01/04LP", "01/05",
    "01/06LP", "01/07", "01/08LP", "01/09", "01/10",
    "01/11FLASH", "01/12LP", "01/13", "01/14", "01/15",
)


def exact_named(items, name):
    def folded(value):
        normalized = unicodedata.normalize("NFKD", normalize_name(value))
        return "".join(char for char in normalized
                       if not unicodedata.combining(char))

    target = folded(name)
    return [item for item in items if folded(item.get("name")) == target]


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-props-0101-0115", methods=["POST"])
    def cierny_kamen_props_0101_0115():
        if request.headers.get("X-Props-0101-0115-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode != "audit":
            return jsonify({"error": "unsupported mode"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        collisions = {
            scene_id: [card.get("shortUrl") for card in groups.get(scene_id, [])]
            for scene_id in SCENE_IDS if len(groups.get(scene_id, [])) != 1
        }
        if collisions:
            return jsonify({
                "status": "blocked", "writes": 0, "collisions": collisions,
            }), 409

        scene_cards = {scene_id: groups[scene_id][0] for scene_id in SCENE_IDS}
        support = board_support_data(api, state["board"]["id"])
        prop_lists = exact_named(
            state["lists"], payload["prop_registry_list_name"]
        )
        if len(prop_lists) != 1:
            return jsonify({
                "status": "blocked", "writes": 0,
                "error": "expected one exact prop registry list",
                "prop_lists": [item.get("name") for item in prop_lists],
            }), 409

        scenes = []
        for scene_id, card in scene_cards.items():
            checklists = support["checklists"].get(card["id"], [])
            prop_checklists = exact_named(checklists, "REKVIZITY")
            scenes.append({
                "scene_id": scene_id,
                "name": card.get("name"),
                "url": card.get("shortUrl"),
                "prop_checklist_count": len(prop_checklists),
                "prop_items": [
                    {"id": item.get("id"), "name": item.get("name"),
                     "state": item.get("state"), "pos": item.get("pos")}
                    for checklist in prop_checklists
                    for item in checklist.get("checkItems", [])
                ],
                "all_checklists": [item.get("name") for item in checklists],
            })

        registry_cards = [
            card for card in state["cards"]
            if card.get("idList") == prop_lists[0]["id"]
        ]
        protected = [
            protected_card_value(scene_cards[scene_id], support)
            for scene_id in SCENE_IDS
        ]
        return jsonify({
            "status": "audit", "writes": 0,
            "board": {"name": state["board"].get("name"),
                      "url": state["board"].get("url")},
            "scene_count": len(scenes), "scene_ids": list(SCENE_IDS),
            "collisions": collisions, "scenes": scenes,
            "registry_list": {"id": prop_lists[0]["id"],
                              "name": prop_lists[0].get("name")},
            "registry_cards": [
                {"id": card["id"], "name": card.get("name"),
                 "url": card.get("shortUrl"), "closed": card.get("closed"),
                 "desc": card.get("desc")}
                for card in registry_cards
            ],
            "protected_snapshot": {
                "sha256": stable_hash(protected),
                "cards": len(protected),
                "checklists": sum(len(item["checklists"]) for item in protected),
                "check_items": sum(
                    len(checklist.get("checkItems", []))
                    for item in protected for checklist in item["checklists"]
                ),
                "attachments": sum(len(item["attachments"]) for item in protected),
                "comments": sum(len(item["comments"]) for item in protected),
            },
        }), 200
