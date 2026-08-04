from __future__ import annotations

import copy
import re
import unicodedata
from collections import defaultdict

from flask import jsonify, request

from cierny_kamen_reference_all import board_support_data, protected_card_value
from cierny_kamen_spaces_props import build_space_catalog


KEY = "cierny-kamen-set-links-dedup-5aug-91e2a6c4"
SPACE_LIST_NAME = "REGISTER PRIESTOROV"
SET_LIST_NAME = "NADVÄZNÉ SETY"
SPACE_MARKER = re.compile(r"<!-- CIERNY-KAMEN-SPACE:([^>]+) -->")
SET_MARKER = re.compile(r"<!-- CIERNY-KAMEN-REGISTRY:SET:([^>]+) -->")
CARD_URL = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+")
KARTA_SUFFIX = re.compile(
    r"(?:\s*\|\s*KARTA:\s*https://trello\.com/c/[A-Za-z0-9]+)+\s*$"
)


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


def marker_key(card, pattern):
    match = pattern.search(card.get("desc") or "")
    return match.group(1) if match else None


def desired_karta_suffix(original, urls):
    core = KARTA_SUFFIX.sub("", original or "").rstrip()
    return core + "".join(f" | KARTA: {url}" for url in urls)


def duplicate_groups(scene_id, card, checklists):
    result = []
    for checklist in checklists:
        groups = defaultdict(list)
        for item in checklist.get("checkItems", []):
            groups[(item.get("name") or "", item.get("state"))].append(item)
        for (name, state), items in groups.items():
            if len(items) < 2:
                continue
            ordered = sorted(items, key=lambda item: item.get("id") or "")
            result.append({
                "scene_id": scene_id, "card_id": card["id"],
                "card_url": card.get("shortUrl"),
                "checklist_id": checklist["id"],
                "checklist": checklist.get("name"),
                "name": name, "state": state,
                "keep_id": ordered[0]["id"],
                "delete_ids": [item["id"] for item in ordered[1:]],
            })
    return result


def one_marker_map(cards, pattern):
    grouped = defaultdict(list)
    for card in cards:
        key = marker_key(card, pattern)
        if key:
            grouped[key].append(card)
    unique = {key: values[0] for key, values in grouped.items()
              if len(values) == 1}
    duplicates = {
        key: [{"name": card.get("name"), "url": card.get("shortUrl")}
              for card in values]
        for key, values in grouped.items() if len(values) > 1
    }
    return unique, duplicates


def strip_karta(value):
    return KARTA_SUFFIX.sub("", value or "").rstrip()


def find_plain_set_item(scene, checklist):
    marker = folded(f"prostredie obrazu {scene['scene_id']}")
    matches = [item for item in checklist.get("checkItems", [])
               if marker in folded(strip_karta(item.get("name")))]
    if len(matches) == 1:
        return matches[0], None
    return None, {
        "scene_id": scene["scene_id"], "type": "plain_set_item_match",
        "match_count": len(matches),
        "items": [item.get("name") for item in checklist.get("checkItems", [])],
    }


def find_continuity_set_item(scene, source_item, checklist):
    prefix = folded(f"<n> {source_item['stable_name']} —")
    matches = [item for item in checklist.get("checkItems", [])
               if folded(item.get("name")).startswith(prefix)]
    if len(matches) == 1:
        return matches[0], None
    return None, {
        "scene_id": scene["scene_id"], "type": "continuity_set_item_match",
        "stable_name": source_item.get("stable_name"),
        "match_count": len(matches),
        "items": [item.get("name") for item in checklist.get("checkItems", [])],
    }


def verify_expected(before, after, operations):
    expected = copy.deepcopy(before)
    by_checklist = {item["id"]: item for item in expected["checklists"]}
    for operation in operations:
        checklist = by_checklist[operation["checklist_id"]]
        if operation["type"] == "delete_duplicate":
            checklist["checkItems"] = [
                item for item in checklist.get("checkItems", [])
                if item.get("id") != operation["item_id"]
            ]
        elif operation["type"] == "set_link":
            for item in checklist.get("checkItems", []):
                if item.get("id") == operation["item_id"]:
                    item["name"] = operation["after"]
                    break
    return expected == after


def build_plan(api, payload, state, support):
    groups = api["cierny_kamen_scene_cards_by_id"](state)
    collisions = {
        scene_id: [card.get("shortUrl") for card in cards]
        for scene_id, cards in groups.items() if len(cards) != 1
    }
    scene_cards = {scene_id: cards[0] for scene_id, cards in groups.items()
                   if len(cards) == 1}
    by_scene = {scene["scene_id"]: scene for scene in payload["scenes"]}
    source_ids = [scene["scene_id"] for scene in payload["scenes"]]

    space_lists = exact_named(state["lists"], SPACE_LIST_NAME)
    set_lists = exact_named(state["lists"], SET_LIST_NAME)
    blockers = []
    if len(space_lists) != 1:
        blockers.append(f"expected one {SPACE_LIST_NAME}; found {len(space_lists)}")
    if len(set_lists) != 1:
        blockers.append(f"expected one {SET_LIST_NAME}; found {len(set_lists)}")
    if collisions:
        blockers.append("scene card collisions")

    space_cards = [card for card in state["cards"]
                   if space_lists and card.get("idList") == space_lists[0]["id"]
                   and not card.get("closed")]
    set_cards = [card for card in state["cards"]
                 if set_lists and card.get("idList") == set_lists[0]["id"]
                 and not card.get("closed")]
    spaces_by_key, space_duplicates = one_marker_map(space_cards, SPACE_MARKER)
    sets_by_key, set_duplicates = one_marker_map(set_cards, SET_MARKER)
    if space_duplicates:
        blockers.append("duplicate space registry markers")
    if set_duplicates:
        blockers.append("duplicate continuity-set registry markers")

    catalog = build_space_catalog(payload)
    checklists_by_card = defaultdict(list)
    for card_id, checklists in support["checklists"].items():
        checklists_by_card[card_id].extend(checklists)

    duplicates = []
    operations = []
    link_details = []
    issues = []
    for scene_id in source_ids:
        card = scene_cards.get(scene_id)
        if not card:
            continue
        checklists = checklists_by_card.get(card["id"], [])
        duplicates.extend(duplicate_groups(scene_id, card, checklists))
        set_checklists = exact_named(checklists, "SET")
        if len(set_checklists) != 1:
            issues.append({"scene_id": scene_id, "type": "set_checklist_count",
                           "count": len(set_checklists)})
            continue
        scene = by_scene[scene_id]

        continuity_sources = [
            item for item in scene.get("set_items", [])
            if item.get("continuity")
        ]

        # A scene with a continuity SET uses its <n> master instead of a
        # parallel ordinary-space checklist link.
        if not continuity_sources:
            ordinary_item, ordinary_issue = find_plain_set_item(
                scene, set_checklists[0]
            )
            names = catalog["scene_locations"].get(scene_id, [])
            missing = [name for name in names
                       if catalog["entries"][name]["key"] not in spaces_by_key]
            ordinary_urls = [
                spaces_by_key[catalog["entries"][name]["key"]].get("shortUrl")
                for name in names if name not in missing
            ]
            if missing:
                ordinary_issue = ordinary_issue or {
                    "scene_id": scene_id, "type": "missing_space_master",
                    "spaces": missing,
                }
            if not names:
                ambiguous = next(
                    (item for item in catalog["ambiguous"]
                     if item["scene_id"] == scene_id), None
                )
                ordinary_issue = ordinary_issue or {
                    "scene_id": scene_id, "type": "ambiguous_space_mapping",
                    "source": ambiguous.get("source") if ambiguous else None,
                    "question": ambiguous.get("question") if ambiguous else None,
                }
            if ordinary_issue:
                issues.append(ordinary_issue)
            else:
                desired = desired_karta_suffix(
                    ordinary_item.get("name") or "", ordinary_urls
                )
                detail = {
                    "scene_id": scene_id, "card_url": card.get("shortUrl"),
                    "kind": "ordinary", "item_id": ordinary_item["id"],
                    "before": ordinary_item.get("name"), "after": desired,
                    "current_urls": CARD_URL.findall(
                        ordinary_item.get("name") or ""
                    ),
                    "desired_urls": ordinary_urls,
                    "changed": desired != ordinary_item.get("name"),
                }
                link_details.append(detail)
                if detail["changed"]:
                    operations.append({
                        "type": "set_link", "scene_id": scene_id,
                        "card_id": card["id"],
                        "card_url": card.get("shortUrl"),
                        "checklist_id": set_checklists[0]["id"],
                        "item_id": ordinary_item["id"],
                        "before": ordinary_item.get("name"), "after": desired,
                        "kind": "ordinary",
                    })

        # Every continuity SET item gets only its NADVÄZNÉ SETY master URL.
        for source_item in continuity_sources:
            item, issue = find_continuity_set_item(
                scene, source_item, set_checklists[0]
            )
            master = sets_by_key.get(source_item.get("registry_key"))
            if not master:
                issue = issue or {
                    "scene_id": scene_id,
                    "type": "missing_continuity_set_master",
                    "key": source_item.get("registry_key"),
                }
            if issue:
                issues.append(issue)
                continue
            urls = [master.get("shortUrl")]
            desired = desired_karta_suffix(item.get("name") or "", urls)
            detail = {
                "scene_id": scene_id, "card_url": card.get("shortUrl"),
                "kind": "continuity", "item_id": item["id"],
                "before": item.get("name"), "after": desired,
                "current_urls": CARD_URL.findall(item.get("name") or ""),
                "desired_urls": urls, "changed": desired != item.get("name"),
            }
            link_details.append(detail)
            if detail["changed"]:
                operations.append({
                    "type": "set_link", "scene_id": scene_id,
                    "card_id": card["id"], "card_url": card.get("shortUrl"),
                    "checklist_id": set_checklists[0]["id"],
                    "item_id": item["id"], "before": item.get("name"),
                    "after": desired, "kind": "continuity",
                })

    for group in duplicates:
        for item_id in group["delete_ids"]:
            operations.append({
                "type": "delete_duplicate", "scene_id": group["scene_id"],
                "card_id": group["card_id"], "card_url": group["card_url"],
                "checklist_id": group["checklist_id"], "item_id": item_id,
                "checklist": group["checklist"], "name": group["name"],
                "keep_id": group["keep_id"],
            })
    return {
        "scene_ids": source_ids, "scene_cards": scene_cards,
        "blockers": blockers, "collisions": collisions,
        "space_lists": space_lists, "set_lists": set_lists,
        "space_cards": space_cards, "set_cards": set_cards,
        "space_marker_duplicates": space_duplicates,
        "set_marker_duplicates": set_duplicates,
        "catalog": catalog, "duplicates": duplicates,
        "link_details": link_details, "issues": issues,
        "operations": operations,
    }


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-set-links-dedup", methods=["POST"])
    def cierny_kamen_set_links_dedup():
        if request.headers.get("X-Set-Link-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "dry-run", "apply", "final-audit"}:
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
        support = board_support_data(api, state["board"]["id"])
        plan = build_plan(api, payload, state, support)
        counts = {
            "scene_cards": len(plan["scene_cards"]),
            "duplicate_groups": len(plan["duplicates"]),
            "duplicate_items_to_delete": sum(
                len(item["delete_ids"]) for item in plan["duplicates"]
            ),
            "set_items_audited": len(plan["link_details"]),
            "ordinary_set_items": sum(
                item["kind"] == "ordinary" for item in plan["link_details"]
            ),
            "continuity_set_items": sum(
                item["kind"] == "continuity" for item in plan["link_details"]
            ),
            "set_links_pending": sum(
                item["changed"] for item in plan["link_details"]
            ),
            "ordinary_links_pending": sum(
                item["changed"] and item["kind"] == "ordinary"
                for item in plan["link_details"]
            ),
            "continuity_links_pending": sum(
                item["changed"] and item["kind"] == "continuity"
                for item in plan["link_details"]
            ),
            "issues": len(plan["issues"]),
            "operations": len(plan["operations"]),
        }
        base = {
            "board": {"name": state["board"].get("name"),
                      "url": state["board"].get("url")},
            "counts": counts, "blockers": plan["blockers"],
            "collisions": plan["collisions"],
            "lists": {
                "spaces": [{"id": item["id"], "name": item.get("name")}
                           for item in plan["space_lists"]],
                "continuity_sets": [
                    {"id": item["id"], "name": item.get("name")}
                    for item in plan["set_lists"]
                ],
            },
            "registry_counts": {"spaces": len(plan["space_cards"]),
                                "continuity_sets": len(plan["set_cards"])},
            "duplicate_groups": plan["duplicates"],
            "issues": plan["issues"],
            "pending_link_sample": [
                item for item in plan["link_details"] if item["changed"]
            ][:30],
        }
        if mode in {"audit", "dry-run", "final-audit"}:
            valid = not plan["blockers"] and (
                mode != "final-audit" or not plan["operations"]
            )
            return jsonify({"status": mode, "writes": 0,
                            "valid": valid, **base}), 200 if valid else 409

        if plan["blockers"]:
            return jsonify({"status": "blocked", "writes": 0, **base}), 409
        selected_ids = plan["scene_ids"][start:start + limit]
        selected = [item for item in plan["operations"]
                    if item["scene_id"] in selected_ids]
        before = {
            scene_id: protected_card_value(
                plan["scene_cards"][scene_id], support
            ) for scene_id in selected_ids if scene_id in plan["scene_cards"]
        }
        writes = 0
        for operation in selected:
            if operation["type"] == "delete_duplicate":
                api["trello_delete"](
                    f"/checklists/{operation['checklist_id']}"
                    f"/checkItems/{operation['item_id']}"
                )
            else:
                api["trello_put_body"](
                    f"/cards/{operation['card_id']}"
                    f"/checkItem/{operation['item_id']}",
                    {"name": operation["after"]},
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
                card = plan["scene_cards"][scene_id]
                after = protected_card_value(after_cards[card["id"]],
                                             after_support)
                if not verify_expected(before[scene_id], after,
                                       scene_operations):
                    errors.append({"scene_id": scene_id,
                                   "error": "read-back mismatch"})
        return jsonify({
            "status": mode, "writes": writes, "start": start,
            "limit": limit, "selected_scene_ids": list(selected_ids),
            "operations": selected, "errors": errors,
            "pending_before": len(plan["operations"]),
        }), 200 if not errors else 409
