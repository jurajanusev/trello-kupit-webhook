from collections import Counter
import re

from flask import jsonify, request

from cierny_kamen_prop_markdown_format import (
    _card_projection,
    classify_item,
    exact_named,
)
from cierny_kamen_reference_all import board_support_data


KEY = "cierny-kamen-0440-markdown-repair-12aug-a7e142c9"
SCENE_ID = "04/40"


def build_audit(api):
    payload = api["cierny_kamen_import_payload"]()
    state = api["cierny_kamen_import_state"](payload)
    groups = api["cierny_kamen_scene_cards_by_id"](state)
    scene_cards = {
        scene_id: cards[0] for scene_id, cards in groups.items()
        if len(cards) == 1
    }
    support = board_support_data(api, state["board"]["id"])
    active_cards = [card for card in state["cards"] if not card.get("closed")]
    cards_by_url = {
        card.get("shortUrl"): card for card in active_cards if card.get("shortUrl")
    }
    blockers = []
    if len(scene_cards) != 313:
        blockers.append(f"expected 313 scenes, found {len(scene_cards)}")
    target_cards = groups.get(SCENE_ID, [])
    scene_pattern = re.compile(r"(?<!\d)0?4\s*/\s*0?40(?!\d)", re.I)
    discovery_candidates = []
    for card in state["cards"]:
        card_checklists = support["checklists"].get(card["id"], [])
        matching_items = [
            {
                "checklist": checklist.get("name"),
                "item_id": item.get("id"), "text": item.get("name"),
            }
            for checklist in card_checklists
            for item in checklist.get("checkItems", [])
            if scene_pattern.search(item.get("name") or "")
        ]
        if (
            scene_pattern.search(card.get("name") or "")
            or scene_pattern.search(card.get("desc") or "")
            or matching_items
        ):
            description = card.get("desc") or ""
            description_match = scene_pattern.search(description)
            discovery_candidates.append({
                "id": card["id"], "name": card.get("name"),
                "url": card.get("shortUrl"), "closed": card.get("closed"),
                "list": state["lists_by_id"].get(card.get("idList"), {}).get("name"),
                "name_match": bool(scene_pattern.search(card.get("name") or "")),
                "description_match": bool(description_match),
                "description_excerpt": (
                    description[max(0, description_match.start() - 500):
                                description_match.end() + 500]
                    if description_match else None
                ),
                "checklists": [{
                    "id": checklist.get("id"), "name": checklist.get("name"),
                    "pos": checklist.get("pos"),
                    "items": [{
                        "id": item.get("id"), "name": item.get("name"),
                        "state": item.get("state"), "pos": item.get("pos"),
                    } for item in checklist.get("checkItems", [])],
                } for checklist in card_checklists],
                "matching_checklist_items": matching_items,
            })
    registry_terms = re.compile(
        r"not(?:y|ami)|sláčik|violončel|darčekov[áú]\s+škatu",
        re.I,
    )
    registry_candidates = []
    for card in state["cards"]:
        if (
            "CIERNY-KAMEN-PROP-REGISTRY-AUTO:START" not in (card.get("desc") or "")
            and not registry_terms.search(card.get("name") or "")
        ):
            continue
        haystack = f"{card.get('name') or ''}\n{card.get('desc') or ''}"
        if registry_terms.search(haystack):
            registry_candidates.append({
                "id": card["id"], "name": card.get("name"),
                "url": card.get("shortUrl"), "closed": card.get("closed"),
                "list": state["lists_by_id"].get(card.get("idList"), {}).get("name"),
                "description": card.get("desc"),
            })
    if len(target_cards) != 1:
        blockers.append(f"expected one {SCENE_ID} card, found {len(target_cards)}")

    plans = []
    for scene in payload["scenes"]:
        scene_id = scene["scene_id"]
        card = scene_cards.get(scene_id)
        if not card:
            continue
        prop_lists = exact_named(
            support["checklists"].get(card["id"], []), "REKVIZITY"
        )
        if len(prop_lists) != 1:
            blockers.append(f"{scene_id}: REKVIZITY checklist mismatch")
            continue
        for item in sorted(
            prop_lists[0].get("checkItems", []), key=lambda value: value.get("pos", 0)
        ):
            before = item.get("name") or ""
            result = classify_item(before, cards_by_url)
            plans.append({
                "scene_id": scene_id, "scene_name": card.get("name"),
                "scene_url": card.get("shortUrl"), "card_id": card["id"],
                "checklist_id": prop_lists[0]["id"], "item_id": item["id"],
                "state": item.get("state"), "pos": item.get("pos"),
                "before": before, "after": result.get("after", before),
                **{key: value for key, value in result.items() if key != "after"},
            })
    target_plans = [plan for plan in plans if plan["scene_id"] == SCENE_ID]
    counts = Counter(plan["action"] for plan in plans)
    target_counts = Counter(plan["action"] for plan in target_plans)
    reasons = Counter(
        plan.get("reason") for plan in plans if plan["action"] == "conflict"
    )
    return {
        "payload": payload, "state": state, "support": support,
        "scene_cards": scene_cards, "plans": plans, "target_plans": target_plans,
        "response": {
            "status": "audit", "writes": 0, "blockers": blockers,
            "board": {
                "id": state["board"]["id"], "name": state["board"].get("name"),
                "url": state["board"].get("url"),
            },
            "scene_0440": {
                "card": ({
                    "id": target_cards[0]["id"], "name": target_cards[0].get("name"),
                    "url": target_cards[0].get("shortUrl"),
                } if len(target_cards) == 1 else None),
                "counts": dict(target_counts), "items": target_plans,
                "discovery_candidates": discovery_candidates,
                "registry_candidates": registry_candidates,
            },
            "all_scenes": {
                "scene_cards": len(scene_cards), "prop_items": len(plans),
                "counts": dict(counts), "conflict_reasons": dict(reasons),
                "unformatted_registry_linked": [
                    plan for plan in plans if plan["action"] == "format"
                ],
            },
        },
    }


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-0440-markdown-repair", methods=["POST"])
    def cierny_kamen_0440_markdown_repair():
        if request.headers.get("X-0440-Repair-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "dry-run", "apply"}:
            return jsonify({"error": "invalid mode"}), 400
        audit = build_audit(api)
        response = audit["response"]
        response["status"] = mode
        if mode != "apply":
            return jsonify(response), 200 if not response["blockers"] else 409
        if response["blockers"]:
            return jsonify(response), 409

        selected = [
            plan for plan in audit["target_plans"] if plan["action"] == "format"
        ]
        unresolved = [
            plan for plan in audit["target_plans"] if plan["action"] == "conflict"
        ]
        if unresolved:
            return jsonify({
                **response, "status": "blocked", "writes": 0,
                "error": "04/40 contains unresolved prop items",
            }), 409
        if not selected:
            return jsonify({
                **response, "status": "unchanged", "writes": 0,
                "protected_preserved": True,
            }), 200

        card = audit["scene_cards"][SCENE_ID]
        fields = "id,name,desc,idList,shortUrl,closed,idLabels,due,dueComplete,pos"
        before_card = _card_projection(api["trello_get"](
            f"/cards/{card['id']}", {"fields": fields}
        ))
        before_lists = api["trello_get"](f"/cards/{card['id']}/checklists", {
            "checkItems": "all", "fields": "id,name,pos",
        })
        before_attachments = api["trello_get"](
            f"/cards/{card['id']}/attachments",
            {"fields": "id,name,url,bytes,date"},
        )
        before_comments = api["trello_get"](
            f"/cards/{card['id']}/actions",
            {"filter": "commentCard", "limit": "1000", "fields": "data,date"},
        )
        before_items = {
            item["id"]: item for checklist in before_lists
            for item in checklist.get("checkItems", [])
        }
        for plan in selected:
            live = before_items.get(plan["item_id"])
            if not live or live.get("name") != plan["before"]:
                return jsonify({
                    **response, "status": "blocked", "writes": 0,
                    "error": f"item {plan['item_id']} changed after audit",
                }), 409

        for plan in selected:
            api["trello_put_body"](
                f"/cards/{card['id']}/checkItem/{plan['item_id']}",
                {"name": plan["after"]},
            )

        after_card = _card_projection(api["trello_get"](
            f"/cards/{card['id']}", {"fields": fields}
        ))
        after_lists = api["trello_get"](f"/cards/{card['id']}/checklists", {
            "checkItems": "all", "fields": "id,name,pos",
        })
        expected_names = {plan["item_id"]: plan["after"] for plan in selected}
        errors = []
        if before_card != after_card:
            errors.append("non-checklist card fields changed")
        after_by_list = {value["id"]: value for value in after_lists}
        for before_list in before_lists:
            after_list = after_by_list.get(before_list["id"])
            if not after_list or (
                before_list.get("name"), before_list.get("pos")
            ) != (after_list.get("name"), after_list.get("pos")):
                errors.append(f"checklist {before_list['id']} changed")
                continue
            after_items = {
                value["id"]: value for value in after_list.get("checkItems", [])
            }
            for before_item in before_list.get("checkItems", []):
                after_item = after_items.get(before_item["id"])
                expected = expected_names.get(before_item["id"], before_item.get("name"))
                if not after_item or (
                    after_item.get("name") != expected
                    or after_item.get("state") != before_item.get("state")
                    or after_item.get("pos") != before_item.get("pos")
                ):
                    errors.append(f"item {before_item['id']} changed unexpectedly")
        if api["trello_get"](
            f"/cards/{card['id']}/attachments",
            {"fields": "id,name,url,bytes,date"},
        ) != before_attachments:
            errors.append("attachments changed")
        if api["trello_get"](
            f"/cards/{card['id']}/actions",
            {"filter": "commentCard", "limit": "1000", "fields": "data,date"},
        ) != before_comments:
            errors.append("comments changed")
        return jsonify({
            "status": "applied" if not errors else "error",
            "writes": len(selected), "operations": selected,
            "protected_preserved": not errors, "protection_errors": errors,
        }), 200 if not errors else 500
