from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from flask import jsonify, request

from cierny_kamen_reference_all import board_support_data


KEY = "cierny-kamen-personal-props-markdown-8aug-4c91e7a2"
BOARD_REF = "CzuD55PR"
PROP_LIST_NAME = "REGISTER REKVIZÍT"
PERSONAL_LABEL = "Osobná rekvizita"
PERSONAL_LIST_SUFFIX = " – OS. REKVIZITY"
CARD_URL = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+")
CARD_SUFFIX = re.compile(
    r"\s*\|\s*KARTA:\s*(https://trello\.com/c/[A-Za-z0-9]+)\s*$",
    re.IGNORECASE,
)
AUTO_START = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:START -->"
NON_PROP_ITEM_IDS = {
    # 01/32FLASH: the earlier audit proved this is only a dialogue mention of
    # a weapon, not a physical prop occurrence.
    "6a6b93696e3a87e94cd1015a",
}


# Explicitly reviewed ownership only.  It is not a main-character list and it
# is never extended by frequency or a generic possessive-name classifier.
OWNER_BY_IDENTITY = {
    "Alexov osobný mobil": "ALEX",
    "Alexov školský batoh": "ALEX",
    "Alexova gitara od Lukáša": "ALEX",
    "Alexova stará gitara": "ALEX",
    "Alexova školská taška": "ALEX",
    "Alicin MacBook s internet bankingom": "ALICA",
    "Alicin mobil s diktafónom": "ALICA",
    "Alicin reportérsky mobil": "ALICA",
    "Betin batoh s planžetou": "BETY",
    "Betin notebook na pátranie po Olasovej": "BETY",
    "Betin notebook na pátranie v DCčku": "BETY",
    "Betin nový denník": "BETY",
    "Betin osobný mobil": "BETY",
    "Betin pôvodný denník": "BETY",
    "Betin tanečný batoh": "BETY",
    "Betina školská taška": "BETY",
    "Dogyho mobil na fotografovanie Alicinho účtu": "DOGY",
    "Dogyho mobil s fotografiami obsahu Sofiinho auta": "DOGY",
    "Dogyho mobil s oznámením mesta": "DOGY",
    "Dogyho osobný mobil": "DOGY",
    "Dogyho spisovateľský notebook": "DOGY",
    "Dogyho školský batoh": "DOGY",
    "Fifov osobný mobil": "FIFO",
    "Gonzov osobný mobil": "GONZO",
    "Ivanov mobil s videom malej Sofie": "IVAN",
    "Ivanov osobný laptop": "IVAN",
    "Kikov osobný mobil": "KIKO",
    "Kikovo auto": "KIKO",
    "Laurin osobný mobil": "LAURA",
    "Laurina kožená taška s iniciálami L.S.": "LAURA",
    "Laurina osobná taška": "LAURA",
    "Laurine nákupné tašky": "LAURA",
    "Lein osobný mobil": "LEA",
    "Meryin DJ laptop": "MERY",
    "Meryine DJ slúchadlá": "MERY",
    "Olasovej pištoľ": "OLASOVÁ",
    "Sofiino auto": "SOFIA",
    "Sárin laptop s Jakubovými fotografiami": "SÁRA",
    "Sárin mobil s fotografiou Laury a Andyho": "SÁRA",
    "Sárin mobil s hudbou na konkurz": "SÁRA",
    "Sárin osobný mobil": "SÁRA",
    "Sárina šatka — 01/11FLASH": "SÁRA",
    "Tomiho výkonný laptop": "TOMI",
    "Veronikin osobný mobil": "VERONIKA",
    "Veronikin osobný mobil so Scrollom": "VERONIKA",
    "Veronikin školský batoh": "VERONIKA",
    "Veronikina papierová taška s jedlom": "VERONIKA",
    "Čmelského mobil s tajným kanálom": "ČMELSKÝ",
}


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


def exact_named(items, name):
    expected = folded(name)
    return [item for item in items if folded(item.get("name")) == expected]


def strip_markdown_name(value):
    value = value.strip()
    if value.startswith("**") and value.endswith("**") and len(value) >= 4:
        return value[2:-2]
    return value


def parse_item(value):
    value = value or ""
    match = CARD_SUFFIX.search(value)
    if not match:
        raise ValueError("missing or malformed KARTA suffix")
    url = match.group(1)
    body = value[:match.start()].rstrip()
    if body.lstrip().startswith("↳"):
        return {"kind": "companion", "url": url, "body": body}
    prefix_match = re.match(r"^(?P<prefix><[^>]+>\s*)", body)
    prefix = prefix_match.group("prefix") if prefix_match else ""
    content = body[len(prefix):]
    parts = re.split(r"\s+—\s+", content, maxsplit=1)
    name = strip_markdown_name(parts[0])
    context = parts[1] if len(parts) == 2 else None
    if context and context.startswith("*") and context.endswith("*"):
        context = context[1:-1]
    if "*" in name or (context and "*" in context):
        raise ValueError("ambiguous existing Markdown delimiters")
    if not name.strip():
        raise ValueError("empty prop identity")
    return {
        "kind": "prop", "url": url, "prefix": prefix,
        "name": name, "context": context,
    }


def format_item(value):
    parsed = parse_item(value)
    if parsed["kind"] != "prop":
        return value
    context = (
        f" — *{parsed['context']}*" if parsed["context"] is not None else ""
    )
    return (
        f"{parsed['prefix']}**{parsed['name']}**{context}"
        f" | KARTA: {parsed['url']}"
    )


def explicit_main_characters(payload, workflow_text):
    payload_value = payload.get("main_characters")
    if isinstance(payload_value, list) and payload_value:
        return {"source": "payload.main_characters", "names": payload_value}
    match = re.search(
        r"(?im)^HLAVNÉ POSTAVY:\s*(.+)$", workflow_text or ""
    )
    if match:
        names = [item.strip() for item in match.group(1).split(",") if item.strip()]
        if names:
            return {"source": "WORKFLOW_SPEC.md", "names": names}
    return None


def register_routes(flask_app, api):
    @flask_app.route(
        "/api/cierny-kamen-personal-props-markdown", methods=["POST"]
    )
    def cierny_kamen_personal_props_markdown():
        if request.headers.get("X-Personal-Props-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "dry-run", "sample", "apply"}:
            return jsonify({
                "error": "mode must be audit, dry-run, sample, or apply"
            }), 400
        try:
            start = int(request.args.get("start", "0"))
            limit = int(request.args.get("limit", "10"))
        except ValueError:
            return jsonify({"error": "start and limit must be integers"}), 400
        if start < 0 or limit < 1 or limit > 10:
            return jsonify({"error": "invalid start/limit"}), 400

        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        scene_cards = {
            scene_id: cards[0] for scene_id, cards in groups.items()
            if len(cards) == 1
        }
        collisions = {
            scene_id: len(cards) for scene_id, cards in groups.items()
            if len(cards) != 1
        }
        support = board_support_data(api, state["board"]["id"])
        prop_lists = exact_named(state["lists"], PROP_LIST_NAME)
        personal_lists = [
            item for item in state["lists"]
            if folded(item.get("name")).endswith(folded(PERSONAL_LIST_SUFFIX))
        ]
        personal_labels = exact_named(state["labels"], PERSONAL_LABEL)
        blockers = []
        if len(prop_lists) != 1:
            blockers.append(f"expected one {PROP_LIST_NAME}")
        if len(personal_labels) != 1:
            blockers.append(f"expected one {PERSONAL_LABEL} label")
        if collisions:
            blockers.append("scene card collisions")

        workflow_text = Path(api["__file__"]).with_name(
            "WORKFLOW_SPEC.md"
        ).read_text(encoding="utf-8")
        main_characters = explicit_main_characters(payload, workflow_text)
        owner_rule = {
            "source": "explicitly reviewed ownership by canonical prop identity",
            "behavior": (
                "every unambiguous owner gets an OS. REKVIZITY list; "
                "shared and ambiguous identities stay in the global register"
            ),
        }

        active_cards = [card for card in state["cards"] if not card.get("closed")]
        cards_by_url = {
            card.get("shortUrl"): card for card in active_cards
            if card.get("shortUrl")
        }
        prop_master_cards = [
            card for card in active_cards
            if AUTO_START in (card.get("desc") or "")
        ]
        personal_cards = [
            card for card in prop_master_cards
            if personal_labels
            and personal_labels[0]["id"] in card.get("idLabels", [])
        ]
        ownership = []
        for card in personal_cards:
            owner = OWNER_BY_IDENTITY.get(card.get("name"))
            ownership.append({
                "name": card.get("name"), "url": card.get("shortUrl"),
                "current_list": state["lists_by_id"].get(
                    card.get("idList"), {}
                ).get("name"),
                "owner_candidate": owner,
                "proposed_list": (
                    f"{owner}{PERSONAL_LIST_SUFFIX}" if owner else None
                ),
                "status": "explicit_owner" if owner else "unassigned_or_shared",
            })

        items = []
        scene_by_id = {scene["scene_id"]: scene for scene in payload["scenes"]}
        for scene_id in [scene["scene_id"] for scene in payload["scenes"]]:
            card = scene_cards.get(scene_id)
            if not card:
                continue
            prop_checklists = exact_named(
                support["checklists"].get(card["id"], []), "REKVIZITY"
            )
            if len(prop_checklists) != 1:
                blockers.append(f"{scene_id}: REKVIZITY checklist mismatch")
                continue
            for item in sorted(
                prop_checklists[0].get("checkItems", []),
                key=lambda value: value.get("pos", 0),
            ):
                before = item.get("name") or ""
                plan = {
                    "scene_id": scene_id,
                    "scene_name": card.get("name"),
                    "scene_title": scene_by_id.get(scene_id, {}).get("prepis"),
                    "scene_url": card.get("shortUrl"),
                    "card_id": card["id"],
                    "checklist_id": prop_checklists[0]["id"],
                    "item_id": item["id"], "state": item.get("state"),
                    "pos": item.get("pos"), "before": before,
                    "after": before, "action": None, "reason": None,
                }
                if item["id"] in NON_PROP_ITEM_IDS:
                    plan.update(
                        action="skip_non_prop_conflict",
                        reason="known dialogue-only false positive",
                    )
                    items.append(plan)
                    continue
                try:
                    parsed = parse_item(before)
                    if parsed["kind"] == "companion":
                        plan.update(action="skip_companion", reason="↳ marker")
                    else:
                        target = cards_by_url.get(parsed["url"])
                        if not target or target not in prop_master_cards:
                            plan.update(
                                action="conflict",
                                reason="KARTA URL does not target an active master card",
                            )
                        elif folded(parsed["name"]) != folded(target.get("name")):
                            plan.update(
                                action="conflict",
                                reason=(
                                    "item identity is an alias, not the canonical "
                                    f"master name {target.get('name')!r}"
                                ),
                            )
                        else:
                            after = format_item(before)
                            plan.update(
                                after=after,
                                action="unchanged" if after == before else "format",
                                target={
                                    "id": target["id"],
                                    "name": target.get("name"),
                                    "url": target.get("shortUrl"),
                                },
                            )
                except ValueError as error:
                    plan.update(action="conflict", reason=str(error))
                items.append(plan)

        sample_names = {
            "Betin osobný mobil", "Policajné auto pri rieke",
        }
        samples = []
        for plan in items:
            target = plan.get("target") or {}
            if target.get("name") in sample_names and plan["action"] == "format":
                if not any(
                    item["target"]["name"] == target["name"] for item in samples
                ):
                    samples.append(plan)

        action_counts = Counter(item["action"] for item in items)
        owner_counts = Counter(
            item["owner_candidate"] for item in ownership
            if item["owner_candidate"]
        )
        unassigned = [
            item for item in ownership if not item["owner_candidate"]
        ]
        explicit_ownership = sorted(
            (item for item in ownership if item["owner_candidate"]),
            key=lambda item: (item["owner_candidate"], folded(item["name"])),
        )
        existing_personal_names = {
            folded(item.get("name")) for item in personal_lists
        }
        planned_list_names = sorted({
            item["proposed_list"] for item in explicit_ownership
            if folded(item["proposed_list"]) not in existing_personal_names
        })
        planned_moves = [
            item for item in explicit_ownership
            if item["current_list"] != item["proposed_list"]
        ]
        response = {
            "status": mode, "writes": 0,
            "board": {
                "id": state["board"]["id"],
                "name": state["board"].get("name"),
                "url": state["board"].get("url"),
            },
            "valid_for_format_sample": not blockers,
            "valid_for_personal_lists": not blockers,
            "blockers": blockers,
            "main_characters": main_characters,
            "owner_rule": owner_rule,
            "main_character_sources_checked": [
                "payload.main_characters", "WORKFLOW_SPEC.md",
                "repository configuration (explicit constants)",
            ],
            "counts": {
                "scene_cards": len(scene_cards),
                "scene_collisions": len(collisions),
                "prop_items": len(items),
                "active_master_cards": len(prop_master_cards),
                "personal_master_cards": len(personal_cards),
                "existing_personal_lists": len(personal_lists),
                "format_actions": dict(action_counts),
                "explicit_owner_cards": sum(owner_counts.values()),
                "unassigned_or_shared_personal_cards": len(unassigned),
                "planned_personal_lists": len(planned_list_names),
                "planned_card_moves": len(planned_moves),
            },
            "owner_candidate_counts": dict(sorted(owner_counts.items())),
            "ownership": ownership,
            "unassigned_or_shared": unassigned,
            "personal_lists": [
                {"id": item["id"], "name": item.get("name"),
                 "closed": item.get("closed")}
                for item in personal_lists
            ],
            "planned_list_names": planned_list_names,
            "format_items": items,
            "samples": samples,
            "markdown_render_verification": {
                "status": "not_verifiable_read_only_via_trello_api",
                "next_step": (
                    "apply one production sample and visually confirm Trello "
                    "renders checklist bold/italic before any batch"
                ),
            },
        }
        if mode in {"audit", "dry-run"}:
            return jsonify(response), 200 if response["valid_for_format_sample"] else 409
        if blockers:
            return jsonify(response), 409

        selected = (
            [item for item in explicit_ownership
             if item["name"] == "Betin osobn\u00fd mobil"]
            if mode == "sample"
            else explicit_ownership[start:start + limit]
        )
        if mode == "sample" and len(selected) != 1:
            return jsonify({
                **response, "status": "blocked", "writes": 0,
                "error": "expected exactly one Betin osobn\u00fd mobil card",
            }), 409

        cards_by_name = {card.get("name"): card for card in personal_cards}
        writes = 0
        operations = []
        protection_errors = []
        created_lists = {}
        for plan in selected:
            card = cards_by_name[plan["name"]]
            list_name = plan["proposed_list"]
            list_matches = exact_named(state["lists"], list_name)
            if list_name in created_lists:
                target_list = created_lists[list_name]
            elif len(list_matches) == 1:
                target_list = list_matches[0]
            elif len(list_matches) > 1:
                protection_errors.append(f"duplicate personal list {list_name}")
                continue
            else:
                target_list = api["trello_post_body"]("/lists", {
                    "idBoard": state["board"]["id"],
                    "name": list_name, "pos": "bottom",
                })
                created_lists[list_name] = target_list
                writes += 1
                operations.append({"type": "create_list", "name": list_name})

            fields = (
                "id,name,desc,idList,shortUrl,closed,idLabels,due,"
                "dueComplete,pos"
            )
            before_card = api["trello_get"](
                f"/cards/{card['id']}", {"fields": fields}
            )
            before_checklists = api["trello_get"](
                f"/cards/{card['id']}/checklists",
                {"checkItems": "all", "fields": "id,name,pos"},
            )
            before_attachments = api["trello_get"](
                f"/cards/{card['id']}/attachments",
                {"fields": "id,name,url,bytes,date"},
            )
            before_comments = api["trello_get"](
                f"/cards/{card['id']}/actions",
                {"filter": "commentCard", "limit": "1000", "fields": "data,date"},
            )

            if before_card.get("idList") != target_list["id"]:
                api["trello_put_body"](
                    f"/cards/{card['id']}", {"idList": target_list["id"]},
                )
                writes += 1
                operations.append({
                    "type": "move_master", "name": card.get("name"),
                    "url": card.get("shortUrl"), "list": list_name,
                })

            after_card = api["trello_get"](
                f"/cards/{card['id']}", {"fields": fields}
            )
            expected_card = dict(before_card)
            expected_card["idList"] = target_list["id"]
            unchanged_related = (
                api["trello_get"](
                    f"/cards/{card['id']}/checklists",
                    {"checkItems": "all", "fields": "id,name,pos"},
                ) == before_checklists
                and api["trello_get"](
                    f"/cards/{card['id']}/attachments",
                    {"fields": "id,name,url,bytes,date"},
                ) == before_attachments
                and api["trello_get"](
                    f"/cards/{card['id']}/actions",
                    {"filter": "commentCard", "limit": "1000", "fields": "data,date"},
                ) == before_comments
            )
            if after_card != expected_card or not unchanged_related:
                protection_errors.append(
                    f"{card.get('name')}: changed beyond idList"
                )

        return jsonify({
            "status": (
                "sample_applied" if mode == "sample" else "batch_applied"
            ) if not protection_errors else "error",
            "writes": writes, "operations": operations,
            "selected": len(selected),
            "start": start, "limit": limit,
            "remaining": (
                max(0, len(explicit_ownership) - start - len(selected))
                if mode == "apply" else len(explicit_ownership) - len(selected)
            ),
            "protected_preserved": not protection_errors,
            "protection_errors": protection_errors,
        }), 200 if not protection_errors else 500
