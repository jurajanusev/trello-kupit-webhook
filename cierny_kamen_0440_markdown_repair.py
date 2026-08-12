from collections import Counter
import re

from flask import jsonify, request

from cierny_kamen_all_props_registry import ensure_attachment
from cierny_kamen_prop_markdown_format import (
    _card_projection,
    classify_item,
    exact_named,
    format_registry_item,
)
from cierny_kamen_reference_all import board_support_data


KEY = "cierny-kamen-0440-markdown-repair-12aug-a7e142c9"
EMBEDDED_CARD_ID = "6a67b0fd060d03b43843c129"
AUTO_START = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:START -->"
AUTO_END = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:END -->"
PROP_SPECS = {
    "6a7cce7a46d65f7ceceb59ed": ("papiere s notami", "Dokument"),
    "6a7cceb277fb569ce63f1cad": (
        "Darčeková škatuľa na sláčik na violončelo", None,
    ),
    "6a7ccf10dc5234c8a025285e": ("nový sláčik na violončelo", None),
}


def load_audit(api):
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
    embedded = [
        card for card in active_cards
        if card["id"] == EMBEDDED_CARD_ID
        and re.search(r"PARALELNÉ\s+4/40\b", card.get("desc") or "", re.I)
    ]
    blockers = []
    if len(scene_cards) != 313:
        blockers.append(f"expected 313 scenes, found {len(scene_cards)}")
    if groups.get("04/40"):
        blockers.append("unexpected standalone 04/40 card now exists")
    if len(embedded) != 1:
        blockers.append(f"expected one embedded 04/40 container, found {len(embedded)}")
    container = embedded[0] if len(embedded) == 1 else None

    all_plans = []
    for scene in payload["scenes"]:
        card = scene_cards.get(scene["scene_id"])
        if not card:
            continue
        prop_lists = exact_named(
            support["checklists"].get(card["id"], []), "REKVIZITY"
        )
        if len(prop_lists) != 1:
            blockers.append(f"{scene['scene_id']}: REKVIZITY checklist mismatch")
            continue
        for item in prop_lists[0].get("checkItems", []):
            result = classify_item(item.get("name") or "", cards_by_url)
            all_plans.append({
                "scene_id": scene["scene_id"], "scene_url": card.get("shortUrl"),
                "item_id": item["id"], "before": item.get("name") or "",
                "after": result.get("after", item.get("name") or ""),
                **{key: value for key, value in result.items() if key != "after"},
            })

    target_items = []
    if container:
        prop_lists = exact_named(
            support["checklists"].get(container["id"], []), "REKVIZITY"
        )
        if len(prop_lists) != 1:
            blockers.append("embedded 04/40 REKVIZITY checklist mismatch")
        else:
            target_items = sorted(
                prop_lists[0].get("checkItems", []),
                key=lambda item: item.get("pos", 0),
            )
            if {item["id"] for item in target_items} != set(PROP_SPECS):
                blockers.append("embedded 04/40 prop item set changed")

    counts = Counter(plan["action"] for plan in all_plans)
    reasons = Counter(
        plan.get("reason") for plan in all_plans if plan["action"] == "conflict"
    )
    exact_masters = {}
    for item_id, (identity, _category) in PROP_SPECS.items():
        exact_masters[item_id] = [
            card for card in state["cards"]
            if (card.get("name") or "").casefold() == identity.casefold()
        ]
        if len(exact_masters[item_id]) > 1:
            blockers.append(f"duplicate master identity {identity}")
    return {
        "payload": payload, "state": state, "support": support,
        "container": container, "target_items": target_items,
        "exact_masters": exact_masters,
        "response": {
            "status": "audit", "writes": 0, "blockers": blockers,
            "board": {"name": state["board"].get("name"),
                      "url": state["board"].get("url")},
            "scene_0440": {
                "resolution": "embedded_parallel_in_04/39",
                "standalone_cards": len(groups.get("04/40", [])),
                "container": ({"id": container["id"], "name": container.get("name"),
                               "url": container.get("shortUrl")}
                              if container else None),
                "items": [{
                    "id": item["id"], "text": item.get("name"),
                    "state": item.get("state"), "pos": item.get("pos"),
                    "identity": PROP_SPECS.get(item["id"], (None, None))[0],
                    "existing_master_matches": len(exact_masters.get(item["id"], [])),
                } for item in target_items],
                "cause": (
                    "04/40 is embedded in 04/39 and all three manual prop items "
                    "were added without KARTA URLs after the Markdown migration"
                ),
            },
            "all_scenes": {
                "scene_cards": len(scene_cards), "prop_items": len(all_plans),
                "counts": dict(counts), "conflict_reasons": dict(reasons),
                "unformatted_registry_linked": [
                    plan for plan in all_plans if plan["action"] == "format"
                ],
            },
        },
    }


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-0440-markdown-repair", methods=["POST"])
    def repair_0440():
        return jsonify({
            "error": "completed 04/40 Markdown repair endpoint disabled"
        }), 410

        if request.headers.get("X-0440-Repair-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").casefold().strip()
        if mode not in {"audit", "dry-run", "apply"}:
            return jsonify({"error": "invalid mode"}), 400
        audit = load_audit(api)
        response = audit["response"]
        response["status"] = mode
        if mode != "apply":
            return jsonify(response), 200 if not response["blockers"] else 409
        if response["blockers"]:
            return jsonify(response), 409

        state = audit["state"]
        card = audit["container"]
        prop_lists = exact_named(state["lists"], "REGISTER REKVIZÍT")
        document_labels = exact_named(state["labels"], "Dokument")
        if len(prop_lists) != 1 or len(document_labels) != 1:
            return jsonify({
                **response, "status": "blocked", "writes": 0,
                "error": "registry list or Dokument label mismatch",
            }), 409

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
        for item in audit["target_items"]:
            live = before_items.get(item["id"])
            if not live or live.get("name") != item.get("name"):
                return jsonify({
                    **response, "status": "blocked", "writes": 0,
                    "error": f"item {item['id']} changed after audit",
                }), 409

        writes = 0
        operations = []
        targets = {}
        for item_id, (identity, category) in PROP_SPECS.items():
            matches = audit["exact_masters"][item_id]
            if matches:
                target = matches[0]
                if target.get("closed"):
                    target = api["trello_put_body"](
                        f"/cards/{target['id']}", {"closed": "false"}
                    )
                    writes += 1
                    operations.append({"type": "reopen_master", "name": identity})
            else:
                block = (
                    f"{AUTO_START}\nKANONICKÝ NÁZOV: {identity}\nALIASY: —\n"
                    f"KATEGÓRIE: {category or '—'}\n\n### VÝSKYTY V OBRAZOCH\n"
                    f"- [04/40 – paralelná časť karty 04/39]({card['shortUrl']})\n"
                    f"{AUTO_END}"
                )
                target = api["trello_post_body"]("/cards", {
                    "idList": prop_lists[0]["id"], "name": identity,
                    "desc": block, "pos": "bottom",
                    "idLabels": document_labels[0]["id"] if category else "",
                })
                writes += 1
                operations.append({"type": "create_master", "name": identity,
                                   "url": target.get("shortUrl")})
            targets[item_id] = target

        expected_names = {}
        for item in audit["target_items"]:
            identity = PROP_SPECS[item["id"]][0]
            target = targets[item["id"]]
            linked = f"{item['name']} | KARTA: {target['shortUrl']}"
            desired = format_registry_item(linked, identity, target["shortUrl"])
            api["trello_put_body"](
                f"/cards/{card['id']}/checkItem/{item['id']}", {"name": desired}
            )
            writes += 1
            expected_names[item["id"]] = desired
            operations.append({"type": "link_and_format_item", "item_id": item["id"],
                               "before": item["name"], "after": desired})
            if ensure_attachment(api, card, target["shortUrl"], identity):
                writes += 1
            if ensure_attachment(api, target, card["shortUrl"], "04/40"):
                writes += 1

        errors = []
        if _card_projection(api["trello_get"](
            f"/cards/{card['id']}", {"fields": fields}
        )) != before_card:
            errors.append("non-checklist card fields changed")
        after_lists = api["trello_get"](f"/cards/{card['id']}/checklists", {
            "checkItems": "all", "fields": "id,name,pos",
        })
        after_by_list = {value["id"]: value for value in after_lists}
        for before_list in before_lists:
            after_list = after_by_list.get(before_list["id"])
            if not after_list or (before_list.get("name"), before_list.get("pos")) != (
                after_list.get("name"), after_list.get("pos")
            ):
                errors.append(f"checklist {before_list['id']} changed")
                continue
            after_items = {value["id"]: value for value in after_list.get("checkItems", [])}
            for before_item in before_list.get("checkItems", []):
                after_item = after_items.get(before_item["id"])
                expected = expected_names.get(before_item["id"], before_item.get("name"))
                if not after_item or after_item.get("name") != expected or (
                    after_item.get("state"), after_item.get("pos")
                ) != (before_item.get("state"), before_item.get("pos")):
                    errors.append(f"item {before_item['id']} changed unexpectedly")
        after_attachments = api["trello_get"](
            f"/cards/{card['id']}/attachments",
            {"fields": "id,name,url,bytes,date"},
        )
        if not {item.get("id") for item in before_attachments}.issubset(
            {item.get("id") for item in after_attachments}
        ) or not all(
            any(item.get("url") == target.get("shortUrl") for item in after_attachments)
            for target in targets.values()
        ):
            errors.append("attachments not preserved or backlinks missing")
        if api["trello_get"](
            f"/cards/{card['id']}/actions",
            {"filter": "commentCard", "limit": "1000", "fields": "data,date"},
        ) != before_comments:
            errors.append("comments changed")
        return jsonify({
            "status": "applied" if not errors else "error", "writes": writes,
            "operations": operations, "protected_preserved": not errors,
            "protection_errors": errors,
        }), 200 if not errors else 500
