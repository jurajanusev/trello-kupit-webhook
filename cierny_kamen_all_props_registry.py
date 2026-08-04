from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

from flask import jsonify, request

from cierny_kamen_reference_all import board_support_data


KEY = "cierny-kamen-all-props-registry-5aug-1f7c3b92"
PROP_LIST_NAME = "REGISTER REKVIZÍT"
SET_LIST_NAME = "NADVÄZNÉ SETY"
CATEGORY_LABELS = (
    "Auto", "Osobná rekvizita", "Dokument", "Screen",
    "Nadväzná rekvizita", "Nadväzný priestor",
)
CARD_URL = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+")


def folded(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def exact_named(items, name):
    target = folded(name)
    return [item for item in items if folded(item.get("name")) == target]


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-all-props-registry", methods=["POST"])
    def cierny_kamen_all_props_registry():
        if request.headers.get("X-All-Props-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode != "audit":
            return jsonify({"error": "unsupported mode"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        collisions = {
            scene_id: [card.get("shortUrl") for card in cards]
            for scene_id, cards in groups.items() if len(cards) != 1
        }
        scene_cards = {
            scene_id: cards[0] for scene_id, cards in groups.items()
            if len(cards) == 1
        }
        support = board_support_data(api, state["board"]["id"])
        prop_lists = exact_named(state["lists"], PROP_LIST_NAME)
        set_lists = exact_named(state["lists"], SET_LIST_NAME)
        blockers = []
        if len(prop_lists) != 1:
            blockers.append(
                f"expected one {PROP_LIST_NAME}; found {len(prop_lists)}"
            )
        if len(set_lists) != 1:
            blockers.append(
                f"expected one {SET_LIST_NAME}; found {len(set_lists)}"
            )
        if collisions:
            blockers.append("scene collisions")

        prop_cards = [
            card for card in state["cards"]
            if prop_lists and card.get("idList") == prop_lists[0]["id"]
        ]
        prop_by_url = {
            card.get("shortUrl"): card for card in prop_cards
            if card.get("shortUrl")
        }
        set_cards = [
            card for card in state["cards"]
            if set_lists and card.get("idList") == set_lists[0]["id"]
        ]
        scene_by_id = {scene["scene_id"]: scene for scene in payload["scenes"]}
        items = []
        checklist_errors = []
        for scene_id in [scene["scene_id"] for scene in payload["scenes"]]:
            card = scene_cards.get(scene_id)
            if not card:
                continue
            checklists = support["checklists"].get(card["id"], [])
            prop_checklists = exact_named(checklists, "REKVIZITY")
            if len(prop_checklists) != 1:
                checklist_errors.append({
                    "scene_id": scene_id, "count": len(prop_checklists),
                })
                continue
            for item in sorted(
                prop_checklists[0].get("checkItems", []),
                key=lambda value: value.get("pos", 0),
            ):
                urls = CARD_URL.findall(item.get("name") or "")
                linked = [prop_by_url[url] for url in urls if url in prop_by_url]
                items.append({
                    "scene_id": scene_id,
                    "scene_name": card.get("name"),
                    "scene_title": scene_by_id.get(scene_id, {}).get("prepis"),
                    "scene_url": card.get("shortUrl"),
                    "checklist_id": prop_checklists[0]["id"],
                    "item_id": item["id"], "pos": item.get("pos"),
                    "state": item.get("state"), "name": item.get("name"),
                    "urls": urls,
                    "valid_registry_urls": [card.get("shortUrl")
                                            for card in linked],
                    "invalid_urls": [url for url in urls
                                     if url not in prop_by_url],
                    "linked_cards": [{
                        "id": linked_card["id"],
                        "name": linked_card.get("name"),
                        "url": linked_card.get("shortUrl"),
                        "closed": linked_card.get("closed"),
                    } for linked_card in linked],
                })

        active_titles = Counter(
            folded(card.get("name")) for card in prop_cards
            if not card.get("closed")
        )
        duplicate_titles = {
            title: count for title, count in active_titles.items() if count > 1
        }
        label_matches = {
            name: exact_named(state["labels"], name) for name in CATEGORY_LABELS
        }
        return jsonify({
            "status": "audit", "writes": 0,
            "board": {"id": state["board"]["id"],
                      "name": state["board"].get("name"),
                      "url": state["board"].get("url")},
            "valid": not blockers, "blockers": blockers,
            "scene_cards": len(scene_cards), "collisions": collisions,
            "checklist_errors": checklist_errors,
            "prop_items": items,
            "counts": {
                "prop_items": len(items),
                "items_without_url": sum(not item["urls"] for item in items),
                "items_with_one_url": sum(len(item["urls"]) == 1 for item in items),
                "items_with_multiple_urls": sum(len(item["urls"]) > 1
                                                for item in items),
                "items_with_invalid_url": sum(bool(item["invalid_urls"])
                                              for item in items),
                "items_linked_to_archived_card": sum(
                    any(card["closed"] for card in item["linked_cards"])
                    for item in items
                ),
                "registry_cards": len(prop_cards),
                "registry_open": sum(not card.get("closed") for card in prop_cards),
                "registry_archived": sum(bool(card.get("closed"))
                                         for card in prop_cards),
                "active_duplicate_titles": len(duplicate_titles),
                "continuity_set_cards": len(set_cards),
                "continuity_set_open": sum(not card.get("closed")
                                           for card in set_cards),
            },
            "registry_cards": [{
                "id": card["id"], "name": card.get("name"),
                "url": card.get("shortUrl"), "closed": card.get("closed"),
                "desc": card.get("desc"),
                "idLabels": card.get("idLabels", []),
            } for card in prop_cards],
            "continuity_set_cards": [{
                "id": card["id"], "name": card.get("name"),
                "url": card.get("shortUrl"), "closed": card.get("closed"),
                "idLabels": card.get("idLabels", []),
            } for card in set_cards],
            "labels": {
                name: [{"id": item["id"], "name": item.get("name")}
                       for item in matches]
                for name, matches in label_matches.items()
            },
            "active_duplicate_titles": duplicate_titles,
        }), 200 if not blockers else 409

