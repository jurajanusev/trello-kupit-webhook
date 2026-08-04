from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from flask import jsonify, request


KEY = "cierny-kamen-set-audit-4aug-84c2d9ef"
BOARD_REF = "CzuD55PR"
SOURCE_LIST_NAME = "REGISTER SETOV"
TARGET_LIST_NAME = "NADVÄZNÉ SETY"
SET_LABEL_NAME = "Nadväzný set"
SET_MARKER = re.compile(r"<!-- CIERNY-KAMEN-REGISTRY:SET:([^>]+) -->")
N_PREFIX = re.compile(r"^\s*<n>(?:\s|$)")
CARD_URL = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+")


def stable_hash(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def base_card_url(value):
    match = CARD_URL.search(value or "")
    return match.group(0) if match else None


def marker_key(card):
    match = SET_MARKER.search(card.get("desc") or "")
    return match.group(1) if match else None


def expected_set_scenes(payload):
    result = defaultdict(set)
    for scene in payload["scenes"]:
        for item in scene.get("set_items", []):
            if item.get("continuity") and item.get("registry_key"):
                result[item["registry_key"]].add(scene["scene_id"])
    return {key: sorted(value) for key, value in result.items()}


def protected_snapshot(api, state):
    board_id = state["board"]["id"]
    checklists = api["trello_get"](f"/boards/{board_id}/checklists", {
        "checkItems": "all", "fields": "id,name,idCard,pos", "filter": "all",
    })
    cards_with_attachments = api["trello_get"](
        f"/boards/{board_id}/cards", {
            "fields": "id", "filter": "all", "limit": 1000,
            "attachments": "true",
            "attachment_fields": "id,name,url,bytes,date",
        },
    )
    comments = api["trello_get"](f"/boards/{board_id}/actions", {
        "filter": "commentCard", "limit": 1000,
        "fields": "id,data,date,idMemberCreator",
    })
    value = {
        "cards": sorted([
            {
                "id": card.get("id"), "name": card.get("name"),
                "desc": card.get("desc"), "idList": card.get("idList"),
                "shortUrl": card.get("shortUrl"), "closed": card.get("closed"),
                "idLabels": sorted(card.get("idLabels", [])),
            }
            for card in state["cards"]
        ], key=lambda item: item["id"]),
        "checklists": sorted(checklists, key=lambda item: item.get("id", "")),
        "attachments": sorted([
            {
                "card_id": card.get("id"),
                "items": sorted(card.get("attachments", []),
                                key=lambda item: item.get("id", "")),
            }
            for card in cards_with_attachments
        ], key=lambda item: item["card_id"]),
        "comments": sorted(comments, key=lambda item: item.get("id", "")),
    }
    return {
        "sha256": stable_hash(value),
        "cards": len(value["cards"]),
        "checklists": len(value["checklists"]),
        "check_items": sum(
            len(item.get("checkItems", [])) for item in value["checklists"]
        ),
        "attachments": sum(
            len(item["items"]) for item in value["attachments"]
        ),
        "comments": len(value["comments"]),
    }


def build_audit(api, payload, state, checklists):
    source_lists = api["cierny_kamen_exact_named"](
        state["lists"], SOURCE_LIST_NAME
    )
    target_lists = api["cierny_kamen_exact_named"](
        state["lists"], TARGET_LIST_NAME
    )
    registry_lists = source_lists + target_lists
    registry_list_ids = {item["id"] for item in registry_lists}
    masters = [
        card for card in state["cards"]
        if not card.get("closed") and card.get("idList") in registry_list_ids
    ]
    master_by_url = {
        base_card_url(card.get("shortUrl")): card
        for card in masters if base_card_url(card.get("shortUrl"))
    }
    master_by_key = defaultdict(list)
    for card in masters:
        if marker_key(card):
            master_by_key[marker_key(card)].append(card)

    label_matches = api["cierny_kamen_exact_named"](
        state["labels"], SET_LABEL_NAME, True
    )
    label_id = label_matches[0]["id"] if len(label_matches) == 1 else None
    scene_groups = api["cierny_kamen_scene_cards_by_id"](state)
    scene_cards = {
        scene_id: cards[0] for scene_id, cards in scene_groups.items()
        if len(cards) == 1
    }
    checklists_by_card = defaultdict(list)
    for checklist in checklists:
        checklists_by_card[checklist.get("idCard")].append(checklist)

    label_scene_ids = set()
    n_scene_ids = set()
    details = {}
    references_by_master = defaultdict(set)
    errors = []
    expected = expected_set_scenes(payload)

    for scene_id, card in sorted(scene_cards.items()):
        has_label = bool(label_id and label_id in card.get("idLabels", []))
        if has_label:
            label_scene_ids.add(scene_id)
        set_lists = [
            item for item in checklists_by_card.get(card["id"], [])
            if api["cierny_kamen_audit_folded"](item.get("name"))
            == api["cierny_kamen_audit_folded"]("SET")
        ]
        n_items = []
        for checklist in set_lists:
            for item in checklist.get("checkItems", []):
                text = item.get("name") or ""
                if N_PREFIX.match(text):
                    url = base_card_url(text)
                    target = master_by_url.get(url)
                    key = marker_key(target) if target else None
                    n_items.append({
                        "item_id": item.get("id"), "text": text,
                        "url": url,
                        "master": ({
                            "id": target.get("id"), "name": target.get("name"),
                            "url": target.get("shortUrl"), "key": key,
                        } if target else None),
                    })
                    if target:
                        references_by_master[target["id"]].add(scene_id)
                    if not url:
                        errors.append({
                            "scene_id": scene_id, "type": "missing_registry_url",
                            "item": text,
                        })
                    elif not target:
                        errors.append({
                            "scene_id": scene_id, "type": "invalid_registry_link",
                            "item": text, "url": url,
                        })
                    elif key not in expected or scene_id not in expected[key]:
                        errors.append({
                            "scene_id": scene_id,
                            "type": "semantic_chain_mismatch",
                            "master": target.get("name"), "key": key,
                        })
        if n_items:
            n_scene_ids.add(scene_id)
        if has_label or n_items:
            details[scene_id] = {
                "scene_id": scene_id, "card_name": card.get("name"),
                "card_url": card.get("shortUrl"), "has_label": has_label,
                "n_item_count": len(n_items), "n_items": n_items,
            }

    for scene_id in sorted(label_scene_ids - n_scene_ids):
        errors.append({"scene_id": scene_id, "type": "label_without_n_item"})
    for scene_id in sorted(n_scene_ids - label_scene_ids):
        errors.append({"scene_id": scene_id, "type": "n_item_without_label"})
    for key, cards in master_by_key.items():
        if len(cards) > 1:
            errors.append({
                "type": "duplicate_master_marker", "key": key,
                "cards": [card.get("shortUrl") for card in cards],
            })

    master_summary = []
    for card in sorted(masters, key=lambda item: item.get("name") or ""):
        key = marker_key(card)
        actual_scenes = sorted(references_by_master.get(card["id"], set()))
        expected_scenes = expected.get(key, [])
        legitimate = bool(
            key in expected
            and len(expected_scenes) >= 2
            and set(actual_scenes).issubset(expected_scenes)
        )
        master_summary.append({
            "id": card.get("id"), "name": card.get("name"),
            "url": card.get("shortUrl"), "registry_key": key,
            "linked_scene_count": len(actual_scenes),
            "linked_scenes": actual_scenes,
            "expected_scene_count": len(expected_scenes),
            "expected_scenes": expected_scenes,
            "legitimate_specific_state_chain": legitimate,
        })
        if not key:
            errors.append({
                "type": "master_without_registry_marker",
                "master": card.get("name"), "url": card.get("shortUrl"),
            })
        elif not legitimate:
            errors.append({
                "type": "master_not_validated_as_specific_state_chain",
                "master": card.get("name"), "key": key,
            })
        if not actual_scenes:
            errors.append({
                "type": "master_without_scene_link",
                "master": card.get("name"), "url": card.get("shortUrl"),
            })

    union = sorted(label_scene_ids | n_scene_ids)
    rename_blockers = []
    if len(source_lists) != 1:
        rename_blockers.append(
            f"expected exactly one open {SOURCE_LIST_NAME} list; found "
            f"{len(source_lists)}"
        )
    if target_lists:
        rename_blockers.append(
            f"target list {TARGET_LIST_NAME} already exists ({len(target_lists)})"
        )
    return {
        "board": {
            "id": state["board"]["id"], "name": state["board"].get("name"),
            "url": state["board"].get("url"), "ref": BOARD_REF,
        },
        "lists": {
            "source": [{"id": item["id"], "name": item.get("name")}
                       for item in source_lists],
            "target": [{"id": item["id"], "name": item.get("name")}
                       for item in target_lists],
        },
        "counts": {
            "unique_scene_cards": len(scene_cards),
            "label_scenes": len(label_scene_ids),
            "n_item_scenes": len(n_scene_ids),
            "union_scenes": len(union),
            "intersection_scenes": len(label_scene_ids & n_scene_ids),
            "label_only_scenes": len(label_scene_ids - n_scene_ids),
            "n_only_scenes": len(n_scene_ids - label_scene_ids),
            "n_items": sum(item["n_item_count"] for item in details.values()),
            "master_cards": len(masters),
            "mapping_errors": len(errors),
        },
        "scene_ids": {
            "label": sorted(label_scene_ids), "n_item": sorted(n_scene_ids),
            "union": union, "label_only": sorted(label_scene_ids - n_scene_ids),
            "n_only": sorted(n_scene_ids - label_scene_ids),
        },
        "scenes": [details[scene_id] for scene_id in union],
        "masters": master_summary,
        "mapping_errors": errors,
        "rename": {
            "from": SOURCE_LIST_NAME, "to": TARGET_LIST_NAME,
            "blockers": rename_blockers, "safe": not rename_blockers,
        },
    }


def register_routes(flask_app, api):
    @flask_app.route("/api/audit-cierny-kamen-set-registry", methods=["POST"])
    def audit_cierny_kamen_set_registry():
        if request.headers.get("X-Set-Audit-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "rename-dry-run", "rename-apply", "read-back"}:
            return jsonify({"error": "unsupported mode"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        checklists = api["trello_get"](
            f"/boards/{state['board']['id']}/checklists", {
                "checkItems": "all", "fields": "id,name,idCard,pos",
                "filter": "all",
            },
        )
        audit = build_audit(api, payload, state, checklists)
        if mode in {"audit", "rename-dry-run", "read-back"}:
            return jsonify({
                "status": mode, "writes": 0,
                "rename_would_write": bool(
                    mode == "rename-dry-run" and audit["rename"]["safe"]
                ),
                **audit,
            }), 200
        if audit["rename"]["blockers"]:
            return jsonify({"status": "blocked", "writes": 0, **audit}), 409

        before = protected_snapshot(api, state)
        source = audit["lists"]["source"][0]
        api["trello_put_body"](
            f"/lists/{source['id']}", {"name": TARGET_LIST_NAME}
        )
        after_state = api["cierny_kamen_import_state"](payload)
        after = protected_snapshot(api, after_state)
        renamed = [
            item for item in after_state["lists"]
            if item.get("id") == source["id"]
        ]
        protected_equal = before["sha256"] == after["sha256"]
        valid = bool(
            len(renamed) == 1
            and renamed[0].get("name") == TARGET_LIST_NAME
            and protected_equal
        )
        return jsonify({
            "status": "renamed" if valid else "verification-failed",
            "writes": 1, "list_id": source["id"],
            "before_name": SOURCE_LIST_NAME,
            "after_name": renamed[0].get("name") if renamed else None,
            "protected_before": before, "protected_after": after,
            "protected_equal": protected_equal, "valid": valid,
        }), 200 if valid else 409

