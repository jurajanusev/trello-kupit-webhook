from __future__ import annotations

import re
import unicodedata
from collections import Counter

from flask import jsonify, request

from cierny_kamen_reference_all import board_support_data


KEY = "cierny-kamen-prop-markdown-format-8aug-72c4a1e9"
PROP_CHECKLIST = "REKVIZITY"
MASTER_AUTO_START = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:START -->"
CARD_SUFFIX = re.compile(
    r"(?P<separator>\s*\|\s*KARTA:\s*)"
    r"(?P<url>https://trello\.com/c/[A-Za-z0-9]+)(?P<trailing>\s*)$",
    re.IGNORECASE,
)
CONTINUITY_PREFIX = re.compile(r"^(?P<prefix><n>\s*)")
COMPANION_PREFIX = re.compile(r"^\s*↳")


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


def exact_named(items, name):
    expected = folded(name)
    return [item for item in items if folded(item.get("name")) == expected]


def remove_allowed_delimiters(value):
    return (value or "").replace("*", "")


def format_registry_item(value, canonical_name, expected_url=None):
    """Insert only Markdown asterisks around a verified canonical identity."""
    if COMPANION_PREFIX.match(value or ""):
        raise ValueError("companion item")
    suffix = CARD_SUFFIX.search(value or "")
    if not suffix:
        raise ValueError("missing or malformed KARTA suffix")
    if expected_url and suffix.group("url") != expected_url:
        raise ValueError("KARTA URL does not match master card")

    body = value[:suffix.start()]
    prefix_match = CONTINUITY_PREFIX.match(body)
    prefix = prefix_match.group("prefix") if prefix_match else ""
    content = body[len(prefix):]

    bold_name = f"**{canonical_name}**"
    if content.startswith(bold_name):
        tail = content[len(bold_name):]
    elif content.startswith(canonical_name):
        tail = content[len(canonical_name):]
    else:
        raise ValueError("item text does not begin with canonical master identity")

    if not tail:
        formatted_body = f"{prefix}{bold_name}"
    else:
        context_match = re.fullmatch(r"(?P<dash>\s+—\s+)(?P<context>.*)", tail)
        if not context_match:
            raise ValueError("identity/context boundary is ambiguous")
        dash = context_match.group("dash")
        context = context_match.group("context")
        if context.startswith("*") and context.endswith("*") and len(context) >= 2:
            context = context[1:-1]
        if "*" in context:
            raise ValueError("ambiguous existing Markdown delimiters")
        formatted_body = f"{prefix}{bold_name}{dash}*{context}*"

    result = (
        formatted_body + suffix.group("separator") + suffix.group("url")
        + suffix.group("trailing")
    )
    if remove_allowed_delimiters(result) != remove_allowed_delimiters(value):
        raise ValueError("formatting would change non-delimiter characters")
    return result


def classify_item(value, cards_by_url):
    if COMPANION_PREFIX.match(value or ""):
        return {"action": "skip_companion", "reason": "companion marker"}
    suffix = CARD_SUFFIX.search(value or "")
    if not suffix:
        return {"action": "conflict", "reason": "missing or malformed KARTA suffix"}
    target = cards_by_url.get(suffix.group("url"))
    if not target or MASTER_AUTO_START not in (target.get("desc") or ""):
        return {
            "action": "conflict",
            "reason": "KARTA URL does not target an active master card",
        }
    try:
        after = format_registry_item(
            value, target.get("name") or "", target.get("shortUrl")
        )
    except ValueError as error:
        return {
            "action": "conflict", "reason": str(error),
            "target": {"name": target.get("name"), "url": target.get("shortUrl")},
        }
    return {
        "action": "correct" if after == value else "format",
        "after": after,
        "target": {"name": target.get("name"), "url": target.get("shortUrl")},
    }


def _card_projection(card):
    fields = (
        "id", "name", "desc", "idList", "shortUrl", "closed", "idLabels",
        "due", "dueComplete", "pos",
    )
    return {field: card.get(field) for field in fields}


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-prop-markdown-format", methods=["POST"])
    def cierny_kamen_prop_markdown_format():
        if request.headers.get("X-Prop-Markdown-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "dry-run", "sample", "apply"}:
            return jsonify({"error": "invalid mode"}), 400
        try:
            limit = int(request.args.get("limit", "10"))
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        if limit < 1 or limit > 10:
            return jsonify({"error": "limit must be between 1 and 10"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        collisions = {
            scene_id: len(cards) for scene_id, cards in groups.items()
            if len(cards) != 1
        }
        scene_cards = {
            scene_id: cards[0] for scene_id, cards in groups.items()
            if len(cards) == 1
        }
        support = board_support_data(api, state["board"]["id"])
        active_cards = [card for card in state["cards"] if not card.get("closed")]
        cards_by_url = {
            card.get("shortUrl"): card for card in active_cards
            if card.get("shortUrl")
        }

        blockers = []
        if len(scene_cards) != 313:
            blockers.append(f"expected 313 unique scene cards, found {len(scene_cards)}")
        if collisions:
            blockers.append(f"scene collisions: {len(collisions)}")

        plans = []
        ordered_scene_ids = [scene["scene_id"] for scene in payload["scenes"]]
        for scene_id in ordered_scene_ids:
            card = scene_cards.get(scene_id)
            if not card:
                continue
            checklists = exact_named(
                support["checklists"].get(card["id"], []), PROP_CHECKLIST
            )
            if len(checklists) != 1:
                blockers.append(f"{scene_id}: expected one REKVIZITY checklist")
                continue
            for item in sorted(
                checklists[0].get("checkItems", []),
                key=lambda item: item.get("pos", 0),
            ):
                before = item.get("name") or ""
                result = classify_item(before, cards_by_url)
                plans.append({
                    "scene_id": scene_id, "scene_name": card.get("name"),
                    "scene_url": card.get("shortUrl"), "card_id": card["id"],
                    "checklist_id": checklists[0]["id"], "item_id": item["id"],
                    "state": item.get("state"), "pos": item.get("pos"),
                    "before": before, "after": result.get("after", before),
                    **{key: value for key, value in result.items() if key != "after"},
                })

        counts = Counter(plan["action"] for plan in plans)
        linked = sum(
            1 for plan in plans
            if plan["action"] in {"format", "correct"}
            or plan.get("target") is not None
        )
        conflict_reasons = Counter(
            plan.get("reason") for plan in plans if plan["action"] == "conflict"
        )
        samples = []
        sample_targets = {
            ("01/16", "Betin osobn\u00fd mobil"),
            ("01/09", "Policajn\u00e9 auto pri rieke"),
        }
        for plan in plans:
            target_name = (plan.get("target") or {}).get("name")
            if (plan["scene_id"], target_name) in sample_targets:
                samples.append(plan)

        response = {
            "status": mode, "writes": 0, "blockers": blockers,
            "board": {
                "id": state["board"]["id"], "name": state["board"].get("name"),
                "url": state["board"].get("url"),
            },
            "counts": {
                "scene_cards": len(scene_cards), "scene_collisions": len(collisions),
                "prop_items": len(plans), "registry_linked": linked,
                "to_format": counts["format"], "already_correct": counts["correct"],
                "conflicts": counts["conflict"],
                "companions_skipped": counts["skip_companion"],
            },
            "conflict_reasons": dict(conflict_reasons),
            "samples": samples,
            "plans": plans,
        }
        if mode in {"audit", "dry-run"}:
            return jsonify(response), 200 if not blockers else 409
        if blockers:
            return jsonify(response), 409

        pending = [plan for plan in plans if plan["action"] == "format"]
        if mode == "sample":
            selected = [
                plan for plan in pending
                if plan["scene_id"] == "01/16"
                and (plan.get("target") or {}).get("name") == "Betin osobn\u00fd mobil"
            ]
            if len(selected) != 1:
                return jsonify({
                    **response, "status": "blocked",
                    "error": "expected one pending Betin osobn\u00fd mobil item on 01/16",
                }), 409
        else:
            selected = pending[:limit]

        selected_by_card = {}
        for plan in selected:
            selected_by_card.setdefault(plan["card_id"], []).append(plan)
        writes = 0
        operations = []
        protection_errors = []
        for card_id, card_plans in selected_by_card.items():
            current_card = api["trello_get"](f"/cards/{card_id}", {
                "fields": "id,name,desc,idList,shortUrl,closed,idLabels,due,dueComplete,pos"
            })
            before_card = _card_projection(current_card)
            before_lists = api["trello_get"](f"/cards/{card_id}/checklists", {
                "checkItems": "all", "fields": "id,name,pos",
            })
            before_attachments = api["trello_get"](
                f"/cards/{card_id}/attachments",
                {"fields": "id,name,url,bytes,date"},
            )
            before_comments = api["trello_get"](
                f"/cards/{card_id}/actions",
                {"filter": "commentCard", "limit": "1000", "fields": "data,date"},
            )
            before_items = {
                item["id"]: item
                for checklist in before_lists
                for item in checklist.get("checkItems", [])
            }
            allowed_names = {}
            card_conflict = False
            for plan in card_plans:
                live = before_items.get(plan["item_id"])
                if not live or live.get("name") != plan["before"]:
                    protection_errors.append(
                        f"{plan['scene_id']} {plan['item_id']}: changed after audit"
                    )
                    card_conflict = True
            if card_conflict:
                continue
            for plan in card_plans:
                api["trello_put_body"](
                    f"/cards/{card_id}/checkItem/{plan['item_id']}",
                    {"name": plan["after"]},
                )
                allowed_names[plan["item_id"]] = plan["after"]
                writes += 1
                operations.append({
                    "scene_id": plan["scene_id"], "item_id": plan["item_id"],
                    "before": plan["before"], "after": plan["after"],
                })

            after_card = _card_projection(api["trello_get"](f"/cards/{card_id}", {
                "fields": "id,name,desc,idList,shortUrl,closed,idLabels,due,dueComplete,pos"
            }))
            after_lists = api["trello_get"](f"/cards/{card_id}/checklists", {
                "checkItems": "all", "fields": "id,name,pos",
            })
            after_by_list = {item["id"]: item for item in after_lists}
            if after_card != before_card:
                protection_errors.append(f"card {card_id}: non-checklist fields changed")
            for before_list in before_lists:
                after_list = after_by_list.get(before_list["id"])
                if not after_list or (
                    before_list.get("name"), before_list.get("pos")
                ) != (after_list.get("name"), after_list.get("pos")):
                    protection_errors.append(f"checklist {before_list['id']} changed")
                    continue
                after_items = {
                    item["id"]: item for item in after_list.get("checkItems", [])
                }
                for before_item in before_list.get("checkItems", []):
                    after_item = after_items.get(before_item["id"])
                    expected_name = allowed_names.get(
                        before_item["id"], before_item.get("name")
                    )
                    if not after_item or (
                        after_item.get("name") != expected_name
                        or after_item.get("state") != before_item.get("state")
                        or after_item.get("pos") != before_item.get("pos")
                    ):
                        protection_errors.append(
                            f"check item {before_item['id']} changed unexpectedly"
                        )
            if api["trello_get"](
                f"/cards/{card_id}/attachments",
                {"fields": "id,name,url,bytes,date"},
            ) != before_attachments:
                protection_errors.append(f"card {card_id}: attachments changed")
            if api["trello_get"](
                f"/cards/{card_id}/actions",
                {"filter": "commentCard", "limit": "1000", "fields": "data,date"},
            ) != before_comments:
                protection_errors.append(f"card {card_id}: comments changed")

        return jsonify({
            "status": (
                "sample_applied" if mode == "sample" else "batch_applied"
            ) if not protection_errors else "error",
            "writes": writes, "selected": len(selected),
            "operations": operations,
            "protected_preserved": not protection_errors,
            "protection_errors": protection_errors,
            "remaining_before_reaudit": max(0, len(pending) - len(selected)),
        }), 200 if not protection_errors else 500
