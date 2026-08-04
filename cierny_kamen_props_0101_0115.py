from __future__ import annotations

import copy
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
PROP_ADDITIONS = {
    "01/08LP": (
        "↳ Potápačská výstroj policajného pátracieho tímu — traja "
        "policajní potápači sa vynárajú a ponárajú pri hľadaní "
        "Jakubovho tela.",
    ),
    "01/09": (
        "↳ Maják policajného auta pri rieke — bliká na policajnom aute "
        "v pozadí počas pátrania po Jakubovi.",
    ),
    "01/12LP": (
        "↳ Sárin fotoalbum s Jakubovými fotografiami — Sára si ho "
        "v izbe prezerá, plače a pozerá Jakubove fotografie.",
    ),
    "01/15": (
        "↳ Kikovo auto — Kiko a Bety na ňom prichádzajú pred Betin dom; "
        "po zastavení obaja vystúpia.",
    ),
}
QUESTION_ADDITIONS = {
    "01/07": (
        "01/07 — Akú konkrétnu výbavu nesie Matejova skupina na kurz "
        "prežitia? Scenár ju explicitne neuvádza.",
    ),
    "01/09": (
        "01/09 — Má mať Keler pri rozhovore s Klaudiou a Oskarom "
        "fyzicky v ruke vyšetrovateľský notes? Scenár jeho použitie "
        "neuvádza.",
    ),
    "01/11FLASH": (
        "01/11FLASH — Potvrdiť, či je Sárina šatka ten istý konkrétny "
        "kus fyzicky prítomný už v 01/02LP–01/06LP; scenár ju v týchto "
        "obrazoch neukazuje a uvádza ju až v 01/11FLASH.",
    ),
    "01/13": (
        "01/13 — Sú pri príchode Laury a Veroniky z limuzíny fyzicky "
        "viditeľné kufre? Scenár ich neuvádza.",
    ),
    "01/14": (
        "01/14 — Prenášajú sa kufre z 01/13 do obývačky? Scenár ich "
        "neuvádza.",
    ),
}


def exact_named(items, name):
    def folded(value):
        normalized = unicodedata.normalize("NFKD", normalize_name(value))
        return "".join(char for char in normalized
                       if not unicodedata.combining(char))

    target = folded(name)
    return [item for item in items if folded(item.get("name")) == target]


def checklist_plan(scene_id, checklists):
    operations = []
    targets = (
        ("REKVIZITY", PROP_ADDITIONS.get(scene_id, ())),
        ("OTÁZKY NA PORADU", QUESTION_ADDITIONS.get(scene_id, ())),
    )
    for checklist_name, desired_names in targets:
        matches = exact_named(checklists, checklist_name)
        if len(matches) != 1:
            if desired_names:
                raise ValueError(
                    f"{scene_id}: expected one {checklist_name} checklist; "
                    f"found {len(matches)}"
                )
            continue
        existing = [item.get("name") for item in matches[0].get("checkItems", [])]
        for name in desired_names:
            if name not in existing:
                operations.append({
                    "scene_id": scene_id,
                    "checklist": checklist_name,
                    "checklist_id": matches[0]["id"],
                    "name": name,
                })
    return operations


def verify_add_only(before, after, operations):
    expected = copy.deepcopy(before)
    expected["checklists"] = []
    actual = copy.deepcopy(after)
    actual["checklists"] = []
    if actual != expected:
        return "protected card data changed outside checklists"

    before_by_id = {item["id"]: item for item in before["checklists"]}
    after_by_id = {item["id"]: item for item in after["checklists"]}
    if set(before_by_id) != set(after_by_id):
        return "checklist set changed"
    allowed = {item["name"] for item in operations}
    for checklist_id, old in before_by_id.items():
        new = after_by_id[checklist_id]
        old_without_items = {key: value for key, value in old.items()
                             if key != "checkItems"}
        new_without_items = {key: value for key, value in new.items()
                             if key != "checkItems"}
        if old_without_items != new_without_items:
            return "checklist metadata changed"
        old_items = {item["id"]: item for item in old.get("checkItems", [])}
        new_items = {item["id"]: item for item in new.get("checkItems", [])}
        for item_id, old_item in old_items.items():
            if new_items.get(item_id) != old_item:
                return "existing checklist item changed"
        additions = [item for item_id, item in new_items.items()
                     if item_id not in old_items]
        if any(item.get("name") not in allowed for item in additions):
            return "unexpected checklist item added"
    for operation in operations:
        checklist = after_by_id[operation["checklist_id"]]
        if sum(item.get("name") == operation["name"]
               for item in checklist.get("checkItems", [])) != 1:
            return "planned checklist item missing or duplicated"
    return None


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-props-0101-0115", methods=["POST"])
    def cierny_kamen_props_0101_0115():
        if request.headers.get("X-Props-0101-0115-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "dry-run", "apply", "final-audit"}:
            return jsonify({"error": "unsupported mode"}), 400
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "15"))
        except ValueError:
            return jsonify({"error": "invalid start/limit"}), 400
        if start < 0 or limit < 1 or limit > 15:
            return jsonify({"error": "limit must be 1..15"}), 400

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
        plans = []
        for scene_id, card in scene_cards.items():
            checklists = support["checklists"].get(card["id"], [])
            prop_checklists = exact_named(checklists, "REKVIZITY")
            operations = checklist_plan(scene_id, checklists)
            plans.extend(operations)
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
                "planned_operations": operations,
            })

        registry_cards = [
            card for card in state["cards"]
            if card.get("idList") == prop_lists[0]["id"]
        ]
        protected = [
            protected_card_value(scene_cards[scene_id], support)
            for scene_id in SCENE_IDS
        ]
        base = {
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
            "pending_operations": len(plans),
            "pending_props": sum(item["checklist"] == "REKVIZITY"
                                 for item in plans),
            "pending_questions": sum(
                item["checklist"] == "OTÁZKY NA PORADU" for item in plans
            ),
        }
        if mode in {"audit", "dry-run", "final-audit"}:
            valid = mode != "final-audit" or not plans
            return jsonify({
                "status": mode, "writes": 0, "valid": valid, **base,
            }), 200 if valid else 409

        selected_ids = SCENE_IDS[start:start + limit]
        selected = [item for item in plans if item["scene_id"] in selected_ids]
        before = {
            scene_id: protected_card_value(scene_cards[scene_id], support)
            for scene_id in selected_ids
        }
        writes = 0
        for operation in selected:
            api["trello_post_body"](
                f"/checklists/{operation['checklist_id']}/checkItems",
                {"name": operation["name"], "pos": "bottom"},
            )
            writes += 1

        errors = []
        if selected:
            after_state = api["cierny_kamen_import_state"](payload)
            after_support = board_support_data(api, state["board"]["id"])
            after_cards = {card["id"]: card for card in after_state["cards"]}
            for scene_id in selected_ids:
                scene_operations = [item for item in selected
                                    if item["scene_id"] == scene_id]
                if not scene_operations:
                    continue
                card = scene_cards[scene_id]
                after = protected_card_value(
                    after_cards[card["id"]], after_support
                )
                error = verify_add_only(before[scene_id], after, scene_operations)
                if error:
                    errors.append({"scene_id": scene_id, "error": error})
        return jsonify({
            "status": mode, "writes": writes, "start": start,
            "limit": limit, "selected_scene_ids": list(selected_ids),
            "operations": selected, "errors": errors,
            "pending_before": len(plans),
        }), 200 if not errors else 409
