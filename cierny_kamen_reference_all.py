from __future__ import annotations

import copy
import re
from collections import defaultdict

from flask import jsonify, request

from cierny_kamen_reference_0116 import (
    CARD_URL,
    RELATED_HEADING,
    desired_description,
    desired_set_item,
    metadata_characters,
    metadata_location_urls,
    normalize_name,
    parse_description,
    related_section,
    stable_hash,
)


KEY = "cierny-kamen-reference-all-4aug-5cf2187b"
BOARD_REF = "CzuD55PR"
REFERENCE_SCENE_ID = "01/16"


def board_support_data(api, board_id):
    checklists = api["trello_get"](f"/boards/{board_id}/checklists", {
        "checkItems": "all", "fields": "id,name,idCard,pos", "filter": "all",
    })
    attachment_cards = api["trello_get"](f"/boards/{board_id}/cards", {
        "fields": "id", "filter": "open", "limit": 1000,
        "attachments": "true", "attachment_fields": "id,name,url,bytes,date",
    })
    actions = api["trello_get"](f"/boards/{board_id}/actions", {
        "filter": "commentCard", "limit": 1000,
        "fields": "id,data,date,idMemberCreator",
    })
    by_card = defaultdict(list)
    for checklist in checklists:
        by_card[checklist.get("idCard")].append(checklist)
    attachments = {
        card["id"]: sorted(card.get("attachments", []),
                           key=lambda item: item.get("id", ""))
        for card in attachment_cards
    }
    comments = defaultdict(list)
    for action in actions:
        card_id = (action.get("data") or {}).get("card", {}).get("id")
        if card_id:
            comments[card_id].append({
                "id": action.get("id"), "date": action.get("date"),
                "member": action.get("idMemberCreator"),
                "text": (action.get("data") or {}).get("text"),
            })
    return {
        "checklists": {
            key: sorted(value, key=lambda item: item.get("id", ""))
            for key, value in by_card.items()
        },
        "attachments": attachments,
        "comments": {
            key: sorted(value, key=lambda item: item.get("id", ""))
            for key, value in comments.items()
        },
        "comment_limit_reached": len(actions) >= 1000,
    }


def protected_card_value(card, support):
    return {
        "card": {
            "id": card.get("id"), "name": card.get("name"),
            "desc": card.get("desc"), "idList": card.get("idList"),
            "shortUrl": card.get("shortUrl"), "closed": card.get("closed"),
            "idLabels": sorted(card.get("idLabels", [])),
        },
        "checklists": support["checklists"].get(card["id"], []),
        "attachments": support["attachments"].get(card["id"], []),
        "comments": support["comments"].get(card["id"], []),
    }


def story_space_key(parsed, scene):
    try:
        return ("registry", tuple(sorted(metadata_location_urls(parsed["metadata"]))))
    except ValueError:
        raw = re.sub(r"\s+", " ", (scene.get("location") or "").strip()).casefold()
        if not raw:
            raise ValueError(f"{scene['scene_id']} has no story-space identity")
        return ("source-exact", raw)


def same_story_space(left, right):
    if left[0] == "registry" and right[0] == "registry":
        return bool(set(left[1]) & set(right[1]))
    return left == right


def prepare_descriptions(payload, scene_cards):
    scenes = payload["scenes"]
    if len(scene_cards) != len(scenes):
        raise ValueError(
            f"expected {len(scenes)} unique cards; found {len(scene_cards)}"
        )
    parsed = {}
    spaces = {}
    characters = {}
    for scene in scenes:
        card = scene_cards.get(scene["scene_id"])
        if not card:
            raise ValueError(f"missing card {scene['scene_id']}")
        try:
            parsed[scene["scene_id"]] = parse_description(card.get("desc") or "")
        except ValueError as exc:
            headings = re.findall(r"(?m)^### .*?$", card.get("desc") or "")
            raise ValueError(
                f"{scene['scene_id']}: {exc}; actual H3 headings={headings}"
            ) from exc
        spaces[scene["scene_id"]] = story_space_key(
            parsed[scene["scene_id"]], scene
        )
        characters[scene["scene_id"]] = metadata_characters(
            parsed[scene["scene_id"]]["metadata"]
        )

    desired = {}
    relationships = {}
    for index, scene in enumerate(scenes):
        scene_id = scene["scene_id"]

        def nearest(predicate):
            previous = next(
                (item for item in reversed(scenes[:index]) if predicate(item)), None
            )
            following = next(
                (item for item in scenes[index + 1:] if predicate(item)), None
            )
            return previous, following

        current_space = spaces[scene_id]
        previous_space, next_space = nearest(
            lambda item: same_story_space(
                spaces[item["scene_id"]], current_space
            )
        )
        char_neighbors = []
        for character in characters[scene_id]:
            key = normalize_name(character)
            previous, following = nearest(
                lambda item, key=key: key in {
                    normalize_name(value)
                    for value in characters[item["scene_id"]]
                }
            )
            char_neighbors.append({
                "character": character, "previous": previous, "next": following,
            })
        cast = {normalize_name(value) for value in characters[scene_id]}
        previous_cast, next_cast = nearest(
            lambda item: {
                normalize_name(value)
                for value in characters[item["scene_id"]]
            } == cast
        )
        neighbors = {
            "space_previous": previous_space, "space_next": next_space,
            "character_neighbors": char_neighbors,
            "same_cast_previous": previous_cast, "same_cast_next": next_cast,
        }
        related = related_section(neighbors, scene_cards)
        new_desc = desired_description(scene_cards[scene_id].get("desc") or "", related)
        reparsed = parse_description(new_desc)
        original = parsed[scene_id]
        for key in (
            "title", "### REKVIZITY V KONTEXTE", "### KONTINUITA",
            "### ODKAZY", "### RUČNÉ DOPLNENIA", "### AKCIA A DIALÓGY",
        ):
            before = original[key] if key == "title" else original["chunks"][key]
            after = reparsed[key] if key == "title" else reparsed["chunks"][key]
            if before.strip("\r\n") != after.strip("\r\n"):
                raise ValueError(f"{scene_id} protected section changed: {key}")
        if reparsed["metadata"] != original["metadata"]:
            raise ValueError(f"{scene_id} metadata content changed")
        desired[scene_id] = new_desc
        relationships[scene_id] = neighbors
    return {
        "parsed": parsed, "desired": desired,
        "relationships": relationships, "spaces": spaces,
        "characters": characters,
    }


def mobile_audit(api, payload, state, scene_cards, support):
    prop_lists = api["cierny_kamen_exact_named"](
        state["lists"], payload["prop_registry_list_name"]
    )
    master_candidates = []
    if len(prop_lists) == 1:
        master_candidates = [
            card for card in state["cards"]
            if not card.get("closed") and card.get("idList") == prop_lists[0]["id"]
            and "betin" in normalize_name(card.get("name"))
            and "mobil" in normalize_name(card.get("name"))
        ]
    items = []
    for scene_id, card in sorted(scene_cards.items()):
        prop_checklists = [
            checklist for checklist in support["checklists"].get(card["id"], [])
            if normalize_name(checklist.get("name")) == "rekvizity"
        ]
        for checklist in prop_checklists:
            for item in checklist.get("checkItems", []):
                name = item.get("name") or ""
                folded = normalize_name(name)
                if "betin" in folded and "mobil" in folded:
                    items.append({
                        "scene_id": scene_id, "card_id": card["id"],
                        "card_url": card.get("shortUrl"),
                        "checklist_id": checklist["id"], "item_id": item["id"],
                        "name": name, "has_card_url": bool(CARD_URL.search(name)),
                    })
    return {
        "prop_lists": [{"id": item["id"], "name": item.get("name")}
                       for item in prop_lists],
        "masters": [{"id": card["id"], "name": card.get("name"),
                     "url": card.get("shortUrl")}
                    for card in master_candidates],
        "items": items,
        "missing_link_items": [item for item in items if not item["has_card_url"]],
    }


def register_routes(flask_app, api):
    @flask_app.route("/api/reference-cierny-kamen-all-scenes", methods=["POST"])
    def reference_all_scenes():
        if request.headers.get("X-Reference-All-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        allowed = {
            "audit", "dry-run", "descriptions-dry-run", "descriptions-apply",
            "mobile-dry-run", "mobile-apply", "final-audit",
        }
        if mode not in allowed:
            return jsonify({"error": "unsupported mode"}), 400
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "10"))
        except ValueError:
            return jsonify({"error": "invalid start/limit"}), 400
        if start < 0 or limit < 1 or limit > 10:
            return jsonify({"error": "limit must be 1..10"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        collisions = {
            key: [card.get("shortUrl") for card in value]
            for key, value in groups.items() if len(value) != 1
        }
        scene_cards = {
            key: value[0] for key, value in groups.items() if len(value) == 1
        }
        try:
            support = board_support_data(api, state["board"]["id"])
            if support["comment_limit_reached"]:
                raise ValueError("comment snapshot reached Trello limit")
            prepared = prepare_descriptions(payload, scene_cards)
            mobile = mobile_audit(api, payload, state, scene_cards, support)
        except Exception as exc:
            return jsonify({
                "status": "blocked", "writes": 0,
                "collisions": collisions,
                "blockers": [f"{type(exc).__name__}: {exc}"],
            }), 409

        scenes = payload["scenes"]
        pending_ids = [
            scene["scene_id"] for scene in scenes
            if scene_cards[scene["scene_id"]].get("desc")
            != prepared["desired"][scene["scene_id"]]
        ]
        all_protected = [
            protected_card_value(scene_cards[scene["scene_id"]], support)
            for scene in scenes
        ]
        base = {
            "board": {"id": state["board"]["id"],
                      "name": state["board"].get("name"),
                      "url": state["board"].get("url"), "ref": BOARD_REF},
            "source_scenes": len(scenes), "unique_scene_cards": len(scene_cards),
            "collisions": collisions,
            "description_pending": len(pending_ids),
            "description_unchanged": len(scenes) - len(pending_ids),
            "pending_scene_ids": pending_ids,
            "protected_snapshot": {
                "sha256": stable_hash(all_protected),
                "cards": len(all_protected),
                "checklists": sum(len(item["checklists"]) for item in all_protected),
                "check_items": sum(
                    len(checklist.get("checkItems", []))
                    for item in all_protected for checklist in item["checklists"]
                ),
                "attachments": sum(len(item["attachments"])
                                   for item in all_protected),
                "comments": sum(len(item["comments"]) for item in all_protected),
            },
            "mobile": mobile,
        }
        if mode in {"audit", "dry-run", "final-audit"}:
            valid = not collisions and (
                mode != "final-audit" or (
                    not pending_ids and not mobile["missing_link_items"]
                )
            )
            return jsonify({
                "status": mode, "writes": 0, "valid": valid, **base,
            }), 200 if valid else 409

        if mode in {"descriptions-dry-run", "descriptions-apply"}:
            selected = scenes[start:start + limit]
            operations = []
            writes = 0
            errors = []
            before_values = {}
            for scene in selected:
                scene_id = scene["scene_id"]
                card = scene_cards[scene_id]
                desired = prepared["desired"][scene_id]
                changed = card.get("desc") != desired
                operations.append({
                    "scene_id": scene_id, "url": card.get("shortUrl"),
                    "changed": changed,
                    "has_related_section": RELATED_HEADING in desired,
                    "metadata_at_end": desired.endswith(
                        prepared["parsed"][scene_id]["metadata"]
                    ),
                })
                if mode != "descriptions-apply" or not changed:
                    continue
                before_values[card["id"]] = protected_card_value(card, support)
                api["trello_put_body"](f"/cards/{card['id']}", {"desc": desired})
                writes += 1
            if mode == "descriptions-apply" and before_values:
                after_state = api["cierny_kamen_import_state"](payload)
                after_support = board_support_data(api, state["board"]["id"])
                after_cards = {card["id"]: card for card in after_state["cards"]}
                for card_id, before in before_values.items():
                    after = protected_card_value(after_cards[card_id], after_support)
                    expected = copy.deepcopy(before)
                    scene_id = next(
                        item["scene_id"] for item in operations
                        if scene_cards[item["scene_id"]]["id"] == card_id
                    )
                    expected["card"]["desc"] = prepared["desired"][scene_id]
                    if after != expected:
                        errors.append({
                            "scene_id": scene_id,
                            "error": "read-back differs outside authorized description",
                        })
                        break
            return jsonify({
                "status": mode, "writes": writes, "start": start,
                "selected": len(selected), "operations": operations,
                "errors": errors,
                "remaining_source": max(0, len(scenes) - start - len(selected)),
                "pending_before_batch": len(pending_ids),
            }), 200 if not errors else 409

        if len(mobile["masters"]) != 1:
            return jsonify({
                "status": "blocked", "writes": 0,
                "error": f"expected one Betin mobil master; found {len(mobile['masters'])}",
                **base,
            }), 409
        master_url = mobile["masters"][0]["url"]
        selected_items = mobile["missing_link_items"][start:start + limit]
        operations = [{
            **item, "after": desired_set_item(item["name"], [master_url])
        } for item in selected_items]
        if mode == "mobile-dry-run":
            return jsonify({
                "status": mode, "writes": 0, "operations": operations,
                "remaining": max(
                    0, len(mobile["missing_link_items"]) - start - len(operations)
                ),
                **base,
            }), 200
        writes = 0
        errors = []
        before_by_card = {
            item["card_id"]: protected_card_value(
                next(card for card in state["cards"] if card["id"] == item["card_id"]),
                support,
            ) for item in operations
        }
        for item in operations:
            api["trello_put_body"](
                f"/cards/{item['card_id']}/checkItem/{item['item_id']}",
                {"name": item["after"]},
            )
            writes += 1
        if operations:
            after_state = api["cierny_kamen_import_state"](payload)
            after_support = board_support_data(api, state["board"]["id"])
            after_cards = {card["id"]: card for card in after_state["cards"]}
            for card_id, before in before_by_card.items():
                expected = copy.deepcopy(before)
                for checklist in expected["checklists"]:
                    for check_item in checklist.get("checkItems", []):
                        match = next((item for item in operations
                                      if item["item_id"] == check_item.get("id")), None)
                        if match:
                            check_item["name"] = match["after"]
                after = protected_card_value(after_cards[card_id], after_support)
                if after != expected:
                    errors.append({"card_id": card_id,
                                   "error": "mobile read-back mismatch"})
        return jsonify({
            "status": mode, "writes": writes, "operations": operations,
            "errors": errors,
        }), 200 if not errors else 409
