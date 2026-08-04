from __future__ import annotations

import re
import unicodedata
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

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
MAP_PATH = Path(__file__).with_name("cierny_kamen_all_props_registry_map.json")


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
        if mode not in {"audit", "dry-run"}:
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
        result = {
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
        }
        if mode == "audit" or blockers:
            return jsonify(result), 200 if not blockers else 409

        identity_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        map_rows = {row["item_id"]: row for row in identity_map["records"]}
        current_rows = {row["item_id"]: row for row in items}
        map_errors = []
        for item_id in sorted(set(map_rows) - set(current_rows)):
            map_errors.append({"item_id": item_id, "error": "item removed"})
        for item_id in sorted(set(current_rows) - set(map_rows)):
            map_errors.append({"item_id": item_id, "error": "new item"})
        for item_id in sorted(set(map_rows) & set(current_rows)):
            digest = hashlib.sha256(
                (current_rows[item_id]["name"] or "").encode("utf-8")
            ).hexdigest()
            if digest != map_rows[item_id]["original_name_sha256"]:
                map_errors.append({
                    "item_id": item_id,
                    "scene_id": current_rows[item_id]["scene_id"],
                    "error": "item text changed since identity review",
                })

        by_title = defaultdict(list)
        by_url = {}
        for card in prop_cards:
            by_title[folded(card.get("name"))].append(card)
            if card.get("shortUrl"):
                by_url[card["shortUrl"]] = card

        rows_by_identity = defaultdict(list)
        for row in identity_map["records"]:
            rows_by_identity[row["stable_name"]].append(row)
        identity_plans = []
        target_by_identity = {}
        identity_conflicts = []
        for stable_name, rows in sorted(rows_by_identity.items()):
            linked_urls = sorted({
                row["existing_registry_url"] for row in rows
                if row.get("existing_registry_url")
            })
            title_cards = by_title[folded(stable_name)]
            open_cards = [card for card in title_cards if not card.get("closed")]
            closed_cards = [card for card in title_cards if card.get("closed")]
            target = None
            action = None
            conflict = None
            if len(linked_urls) > 1:
                conflict = "identity points to multiple existing registry cards"
            elif linked_urls:
                target = by_url.get(linked_urls[0])
                if not target:
                    conflict = "linked registry card missing from registry list"
                else:
                    action = "reuse_open" if not target.get("closed") else "reopen"
            elif len(open_cards) == 1:
                target = open_cards[0]
                action = "reuse_open"
            elif len(open_cards) > 1:
                conflict = "duplicate open registry identity"
            elif len(closed_cards) == 1:
                target = closed_cards[0]
                action = "reopen"
            elif len(closed_cards) > 1:
                conflict = "multiple archived registry identities"
            else:
                action = "create"
            if conflict:
                identity_conflicts.append({
                    "stable_name": stable_name, "error": conflict,
                    "urls": linked_urls,
                })
            categories = sorted({
                category for row in rows for category in row["categories"]
            })
            plan = {
                "stable_name": stable_name,
                "occurrences": len(rows),
                "scene_ids": sorted({row["scene_id"] for row in rows}),
                "categories": categories,
                "action": action,
                "target": None if not target else {
                    "id": target["id"], "name": target.get("name"),
                    "url": target.get("shortUrl"),
                    "closed": target.get("closed"),
                },
                "archived_same_title_not_selected": [
                    card.get("shortUrl") for card in closed_cards
                    if not target or card["id"] != target["id"]
                ],
                "conflict": conflict,
            }
            identity_plans.append(plan)
            target_by_identity[stable_name] = target

        item_plans = []
        for row in identity_map["records"]:
            current = current_rows.get(row["item_id"])
            target = target_by_identity.get(row["stable_name"])
            target_url = target.get("shortUrl") if target else None
            current_urls = [] if not current else current["urls"]
            if row.get("conflict"):
                action = "manual_conflict_no_write"
            elif not current:
                action = "blocked_missing_item"
            elif target_url and current_urls == [target_url]:
                action = "unchanged"
            elif not current_urls:
                action = "append_registry_url"
            else:
                action = "replace_registry_url"
            item_plans.append({
                "scene_id": row["scene_id"], "item_id": row["item_id"],
                "stable_name": row["stable_name"], "action": action,
                "target_url": target_url,
                "ambiguity_question": row.get("ambiguity_question"),
                "conflict": row.get("conflict"),
            })

        existing_questions = set()
        for scene_id, card in scene_cards.items():
            for checklist in exact_named(
                support["checklists"].get(card["id"], []),
                "OTĂZKY NA PORADU",
            ):
                existing_questions.update(
                    folded(item.get("name"))
                    for item in checklist.get("checkItems", [])
                )
        proposed_questions = sorted({
            row["ambiguity_question"] for row in identity_map["records"]
            if row.get("ambiguity_question")
        })
        questions_to_add = [
            question for question in proposed_questions
            if folded(question) not in existing_questions
        ]

        missing_labels = [
            name for name, matches in label_matches.items() if not matches
        ]
        duplicate_labels = {
            name: len(matches) for name, matches in label_matches.items()
            if len(matches) > 1
        }
        set_label_matches = label_matches["NadvĂ¤znĂ˝ priestor"]
        set_cards_to_label = []
        if len(set_label_matches) == 1:
            set_label_id = set_label_matches[0]["id"]
            set_cards_to_label = [
                card.get("shortUrl") for card in set_cards
                if set_label_id not in card.get("idLabels", [])
            ]
        elif not set_label_matches:
            set_cards_to_label = [card.get("shortUrl") for card in set_cards]

        dry_blockers = list(map_errors) + list(identity_conflicts)
        if duplicate_labels:
            dry_blockers.append({"duplicate_labels": duplicate_labels})
        action_counts = Counter(plan["action"] for plan in identity_plans)
        item_action_counts = Counter(plan["action"] for plan in item_plans)
        category_identity_counts = Counter(
            category for plan in identity_plans for category in plan["categories"]
        )
        result.update({
            "status": "dry-run",
            "valid": not dry_blockers,
            "blockers": dry_blockers,
            "identity_map_stats": identity_map["stats"],
            "identity_map_errors": map_errors,
            "identity_plans": identity_plans,
            "item_plans": item_plans,
            "identity_conflicts": identity_conflicts,
            "questions": {
                "unique_proposed": len(proposed_questions),
                "to_add": len(questions_to_add),
                "items": questions_to_add,
            },
            "planned_labels": {
                "create": missing_labels,
                "duplicates": duplicate_labels,
                "category_identity_counts": dict(category_identity_counts),
                "continuity_set_cards_to_label": len(set_cards_to_label),
                "continuity_set_urls": set_cards_to_label,
            },
            "plan_counts": {
                "identities": len(identity_plans),
                "identity_actions": dict(action_counts),
                "item_actions": dict(item_action_counts),
                "master_auto_blocks_to_refresh": len(identity_plans),
            },
        })
        return jsonify(result), 200 if not dry_blockers else 409

    original_view = flask_app.view_functions[
        "cierny_kamen_all_props_registry"
    ]

    def guarded_all_props_registry(*args, **kwargs):
        try:
            return original_view(*args, **kwargs)
        except Exception as error:
            return jsonify({
                "status": "error", "writes": 0,
                "error_type": type(error).__name__,
                "error": str(error),
            }), 500

    flask_app.view_functions[
        "cierny_kamen_all_props_registry"
    ] = guarded_all_props_registry
