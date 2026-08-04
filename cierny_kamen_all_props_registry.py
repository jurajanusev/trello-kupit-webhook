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
QUESTION_LIST_NAME = "OTÁZKY NA PORADU"
CATEGORY_LABELS = (
    "Auto", "Osobná rekvizita", "Dokument", "Screen",
    "Nadväzná rekvizita", "Nadväzný priestor",
)
CARD_URL = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+")
MAP_PATH = Path(__file__).with_name("cierny_kamen_all_props_registry_map.json")
PROP_AUTO_START = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:START -->"
PROP_AUTO_END = "<!-- CIERNY-KAMEN-PROP-REGISTRY-AUTO:END -->"
SAMPLE_IDENTITIES = (
    "Magnetka „I love Barcelona“ pre Kika",
    "Policajný čln pátracieho tímu",
    "Policajné auto pri rieke",
    "Sárin fotoalbum s Jakubovými fotografiami",
    "Fotografie z Alicinho internet bankingu",
)
LABEL_COLORS = {
    "Osobná rekvizita": "purple",
    "Dokument": "yellow",
    "Nadväzný priestor": "lime",
}


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


def without_card_suffix(value):
    return re.sub(
        r"\s*\|\s*KARTA:\s*https://trello\.com/c/[A-Za-z0-9]+\s*$",
        "", value or "", flags=re.IGNORECASE,
    ).rstrip()


def with_card_suffix(value, url):
    return f"{without_card_suffix(value)} | KARTA: {url}"


def alias_core(value):
    value = without_card_suffix(value).strip()
    value = re.sub(r"^(?:<[^>]+>\s*|↳\s*)", "", value).strip()
    return re.split(r"\s+—\s+", value, maxsplit=1)[0].strip()


def replace_auto_block(value, block):
    value = value or ""
    if value.count(PROP_AUTO_START) != value.count(PROP_AUTO_END):
        raise ValueError("unbalanced prop registry auto markers")
    if value.count(PROP_AUTO_START) > 1:
        raise ValueError("duplicate prop registry auto markers")
    if PROP_AUTO_START in value:
        start = value.index(PROP_AUTO_START)
        end = value.index(PROP_AUTO_END, start) + len(PROP_AUTO_END)
        return value[:start] + block + value[end:]
    return (value.rstrip() + "\n\n" + block).lstrip("\n")


def outside_auto_block(value):
    value = value or ""
    if PROP_AUTO_START not in value:
        return value.rstrip()
    start = value.index(PROP_AUTO_START)
    end = value.index(PROP_AUTO_END, start) + len(PROP_AUTO_END)
    return (value[:start] + value[end:]).rstrip()


def master_auto_block(stable_name, rows):
    aliases = sorted({
        alias_core(row["original_name"])
        for row in rows
        if folded(alias_core(row["original_name"])) != folded(stable_name)
    }, key=folded)
    categories = sorted({
        category for row in rows for category in row["categories"]
    }, key=folded)
    occurrences = []
    seen = set()
    for row in sorted(rows, key=lambda item: (item["scene_id"], item["item_id"])):
        if row.get("conflict") or row["scene_id"] in seen:
            continue
        seen.add(row["scene_id"])
        occurrences.append(
            f"- [{row['scene_id']}]({row['scene_url']})"
        )
    return (
        f"{PROP_AUTO_START}\n"
        f"KANONICKÝ NÁZOV: {stable_name}\n"
        f"ALIASY: {', '.join(aliases) if aliases else '—'}\n"
        f"KATEGÓRIE: {', '.join(categories) if categories else '—'}\n\n"
        "### VÝSKYTY V OBRAZOCH\n"
        + ("\n".join(occurrences) if occurrences else "- —") + "\n"
        f"{PROP_AUTO_END}"
    )


def attachment_projection(items):
    return {
        item.get("id"): {
            "id": item.get("id"), "name": item.get("name"),
            "url": item.get("url"), "bytes": item.get("bytes"),
            "date": item.get("date"),
        }
        for item in items
    }


def ensure_attachment(api, card, url, name):
    attachments = api["trello_get"](
        f"/cards/{card['id']}/attachments", {"fields": "id,name,url,bytes,date"}
    )
    if any(item.get("url") == url for item in attachments):
        return False
    api["trello_post_body"](
        f"/cards/{card['id']}/attachments", {"url": url, "name": name}
    )
    return True


def register_routes(flask_app, api):
    @flask_app.route("/api/cierny-kamen-all-props-registry", methods=["POST"])
    def cierny_kamen_all_props_registry():
        return jsonify({
            "status": "disabled",
            "message": "complete prop registry migration is finished",
        }), 410
        if request.headers.get("X-All-Props-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").strip().casefold()
        if mode not in {"audit", "dry-run", "sample", "apply"}:
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
            current_name = current_rows[item_id]["name"] or ""
            digest = hashlib.sha256(current_name.encode("utf-8")).hexdigest()
            original_name = map_rows[item_id]["original_name"]
            if (
                digest != map_rows[item_id]["original_name_sha256"]
                and without_card_suffix(current_name)
                != without_card_suffix(original_name)
            ):
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
                QUESTION_LIST_NAME,
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
        set_label_matches = label_matches[CATEGORY_LABELS[-1]]
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
        final_errors = []
        duplicate_attachment_urls = []
        for stable_name, rows in rows_by_identity.items():
            target = target_by_identity.get(stable_name)
            safe_rows = [row for row in rows if not row.get("conflict")]
            if not target or target.get("closed"):
                final_errors.append(f"{stable_name}: active master missing")
                continue
            expected_block = master_auto_block(stable_name, safe_rows)
            actual_desc = target.get("desc") or ""
            if expected_block not in actual_desc:
                final_errors.append(f"{stable_name}: master auto block differs")
            expected_label_ids = {
                label_matches[category][0]["id"]
                for category in {
                    value for row in rows for value in row["categories"]
                }
                if len(label_matches.get(category, [])) == 1
            }
            if not expected_label_ids.issubset(
                set(target.get("idLabels", []))
            ):
                final_errors.append(f"{stable_name}: category label missing")
            target_attachments = support["attachments"].get(target["id"], [])
            target_urls = [item.get("url") for item in target_attachments]
            repeated = sorted(
                url for url, count in Counter(target_urls).items()
                if url and count > 1
            )
            if repeated:
                duplicate_attachment_urls.append({
                    "card": target.get("shortUrl"), "urls": repeated,
                })
            for row in safe_rows:
                current = current_rows.get(row["item_id"])
                if not current or current["urls"] != [target.get("shortUrl")]:
                    final_errors.append(
                        f"{row['scene_id']}:{row['item_id']}: checklist URL differs"
                    )
                scene_card = scene_cards.get(row["scene_id"])
                if not scene_card:
                    continue
                scene_urls = [
                    item.get("url") for item in
                    support["attachments"].get(scene_card["id"], [])
                ]
                if target.get("shortUrl") not in scene_urls:
                    final_errors.append(
                        f"{row['scene_id']}:{stable_name}: scene backlink missing"
                    )
                if scene_card.get("shortUrl") not in target_urls:
                    final_errors.append(
                        f"{row['scene_id']}:{stable_name}: master backlink missing"
                    )
                repeated_scene = sorted(
                    url for url, count in Counter(scene_urls).items()
                    if url and count > 1
                )
                if repeated_scene:
                    duplicate_attachment_urls.append({
                        "card": scene_card.get("shortUrl"),
                        "urls": repeated_scene,
                    })
        if duplicate_attachment_urls:
            final_errors.append("duplicate attachment URLs exist")
        set_label_ids = [
            item["id"] for item in label_matches[CATEGORY_LABELS[-1]]
        ]
        set_cards_missing_label = [
            card.get("shortUrl") for card in set_cards
            if len(set_label_ids) != 1
            or set_label_ids[0] not in card.get("idLabels", [])
        ]
        if set_cards_missing_label:
            final_errors.append("continuity set cards missing category label")
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
            "final_audit": {
                "valid": not final_errors,
                "errors": final_errors,
                "active_master_cards": sum(
                    plan["action"] == "reuse_open"
                    for plan in identity_plans
                ),
                "items_with_expected_registry_url": sum(
                    plan["action"] in {"unchanged", "manual_conflict_no_write"}
                    for plan in item_plans
                ),
                "master_blocks_exact": len(identity_plans) - sum(
                    error.endswith("master auto block differs")
                    for error in final_errors
                ),
                "bidirectional_links_checked": sum(
                    1 for row in identity_map["records"]
                    if not row.get("conflict")
                ),
                "duplicate_attachment_urls": duplicate_attachment_urls,
                "continuity_set_cards_missing_label": set_cards_missing_label,
            },
        })
        if mode == "dry-run" or dry_blockers:
            return jsonify(result), 200 if not dry_blockers else 409

        start = max(0, request.args.get("start", 0, type=int))
        limit = min(20, max(1, request.args.get("limit", 10, type=int)))
        plan_by_name = {plan["stable_name"]: plan for plan in identity_plans}
        if mode == "sample":
            selected_names = list(SAMPLE_IDENTITIES)
            missing_sample = [
                name for name in selected_names if name not in plan_by_name
            ]
            if missing_sample:
                return jsonify({
                    "status": "blocked", "writes": 0,
                    "error": "sample identity missing",
                    "missing": missing_sample,
                }), 409
        else:
            selected_names = [
                plan["stable_name"] for plan in identity_plans
                if not plan["conflict"]
            ][start:start + limit]
        selected_set_cards = []
        if mode == "sample":
            selected_set_cards = [
                card for card in set_cards if not card.get("closed")
            ][:1]
        elif request.args.get("sets", "0") == "1":
            set_start = max(0, request.args.get("set_start", 0, type=int))
            set_limit = min(20, max(
                1, request.args.get("set_limit", 10, type=int)
            ))
            selected_set_cards = set_cards[set_start:set_start + set_limit]

        selected_rows = [
            row for row in identity_map["records"]
            if row["stable_name"] in selected_names and not row.get("conflict")
        ]
        rows_for_identity = defaultdict(list)
        for row in selected_rows:
            rows_for_identity[row["stable_name"]].append(row)
        selected_scene_ids = sorted({row["scene_id"] for row in selected_rows})
        selected_scene_cards = {
            scene_id: scene_cards[scene_id] for scene_id in selected_scene_ids
        }

        before_scene = {
            scene_id: {
                "card": dict(card),
                "checklists": support["checklists"].get(card["id"], []),
                "attachments": attachment_projection(
                    support["attachments"].get(card["id"], [])
                ),
                "comments": support["comments"].get(card["id"], []),
            }
            for scene_id, card in selected_scene_cards.items()
        }
        existing_targets = {}
        for stable_name in selected_names:
            target = target_by_identity.get(stable_name)
            if target:
                existing_targets[stable_name] = {
                    "card": dict(target),
                    "checklists": support["checklists"].get(target["id"], []),
                    "attachments": attachment_projection(api["trello_get"](
                        f"/cards/{target['id']}/attachments",
                        {"fields": "id,name,url,bytes,date"},
                    )),
                    "comments": support["comments"].get(target["id"], []),
                }
        before_sets = {
            card["id"]: dict(card) for card in selected_set_cards
        }

        label_by_name = {}
        writes = 0
        operations = []
        for name in CATEGORY_LABELS:
            matches = exact_named(state["labels"], name)
            if len(matches) > 1:
                return jsonify({
                    "status": "blocked", "writes": writes,
                    "error": f"duplicate label {name}",
                }), 409
            if matches:
                label_by_name[name] = matches[0]
            elif name in LABEL_COLORS:
                created = api["trello_post_body"]("/labels", {
                    "idBoard": state["board"]["id"], "name": name,
                    "color": LABEL_COLORS[name],
                })
                label_by_name[name] = created
                writes += 1
                operations.append({"type": "create_label", "name": name})

        targets = {}
        prop_list_id = prop_lists[0]["id"]
        for stable_name in selected_names:
            plan = plan_by_name[stable_name]
            rows = rows_for_identity[stable_name]
            target = target_by_identity.get(stable_name)
            block = master_auto_block(stable_name, rows)
            category_ids = {
                label_by_name[name]["id"]
                for name in plan["categories"] if name in label_by_name
            }
            if not target:
                target = api["trello_post_body"]("/cards", {
                    "idList": prop_list_id, "name": stable_name,
                    "desc": block, "pos": "bottom",
                    "idLabels": ",".join(sorted(category_ids)),
                })
                writes += 1
                operations.append({
                    "type": "create_master", "name": stable_name,
                    "url": target.get("shortUrl"),
                })
            else:
                body = {}
                if target.get("closed"):
                    body["closed"] = "false"
                desired_desc = replace_auto_block(target.get("desc") or "", block)
                if desired_desc != (target.get("desc") or ""):
                    body["desc"] = desired_desc
                desired_labels = sorted(
                    set(target.get("idLabels", [])) | category_ids
                )
                if desired_labels != sorted(target.get("idLabels", [])):
                    body["idLabels"] = ",".join(desired_labels)
                if body:
                    target = api["trello_put_body"](
                        f"/cards/{target['id']}", body,
                    )
                    writes += 1
                    operations.append({
                        "type": "update_master", "name": stable_name,
                        "fields": sorted(body), "url": target.get("shortUrl"),
                    })
            targets[stable_name] = target

        expected_item_names = {}
        for row in selected_rows:
            current = current_rows[row["item_id"]]
            target = targets[row["stable_name"]]
            desired = with_card_suffix(current["name"], target["shortUrl"])
            expected_item_names[row["item_id"]] = desired
            if desired != current["name"]:
                card = selected_scene_cards[row["scene_id"]]
                api["trello_put_body"](
                    f"/cards/{card['id']}/checkItem/{row['item_id']}",
                    {"name": desired},
                )
                writes += 1
                operations.append({
                    "type": "link_item", "scene_id": row["scene_id"],
                    "item_id": row["item_id"],
                    "master": row["stable_name"],
                })

        questions_added = []
        question_names_by_scene = {}
        for row in selected_rows:
            question = row.get("ambiguity_question")
            if not question:
                continue
            card = selected_scene_cards[row["scene_id"]]
            question_lists = exact_named(
                support["checklists"].get(card["id"], []),
                QUESTION_LIST_NAME,
            )
            if len(question_lists) != 1:
                continue
            existing = question_names_by_scene.setdefault(
                row["scene_id"], {
                    folded(item.get("name"))
                    for item in question_lists[0].get("checkItems", [])
                },
            )
            if folded(question) not in existing:
                api["trello_post_body"](
                    f"/checklists/{question_lists[0]['id']}/checkItems",
                    {"name": question, "pos": "bottom"},
                )
                existing.add(folded(question))
                questions_added.append({
                    "scene_id": row["scene_id"], "question": question,
                })
                writes += 1

        for stable_name, target in targets.items():
            rows = rows_for_identity[stable_name]
            for scene_id in sorted({row["scene_id"] for row in rows}):
                scene_card = selected_scene_cards[scene_id]
                if ensure_attachment(
                    api, scene_card, target["shortUrl"], stable_name,
                ):
                    writes += 1
                    operations.append({
                        "type": "attach_master_to_scene",
                        "scene_id": scene_id, "master": stable_name,
                    })
                if ensure_attachment(
                    api, target, scene_card["shortUrl"], scene_id,
                ):
                    writes += 1
                    operations.append({
                        "type": "attach_scene_to_master",
                        "scene_id": scene_id, "master": stable_name,
                    })

        set_label = label_by_name.get("Nadväzný priestor")
        if set_label:
            for card in selected_set_cards:
                desired = sorted(
                    set(card.get("idLabels", [])) | {set_label["id"]}
                )
                if desired != sorted(card.get("idLabels", [])):
                    api["trello_put_body"](
                        f"/cards/{card['id']}",
                        {"idLabels": ",".join(desired)},
                    )
                    writes += 1
                    operations.append({
                        "type": "label_continuity_set",
                        "name": card.get("name"), "url": card.get("shortUrl"),
                    })

        after_state = api["cierny_kamen_import_state"](payload)
        after_support = board_support_data(api, state["board"]["id"])
        after_cards = {card["id"]: card for card in after_state["cards"]}
        protection_errors = []

        def verify_checklists(before_lists, after_lists, allowed_names):
            after_by_id = {item["id"]: item for item in after_lists}
            for before_list in before_lists:
                after_list = after_by_id.get(before_list["id"])
                if not after_list or (
                    before_list.get("name"), before_list.get("pos")
                ) != (after_list.get("name"), after_list.get("pos")):
                    return False
                after_items = {
                    item["id"]: item for item in after_list.get("checkItems", [])
                }
                for before_item in before_list.get("checkItems", []):
                    after_item = after_items.get(before_item["id"])
                    if not after_item:
                        return False
                    if (
                        before_item.get("state"), before_item.get("pos")
                    ) != (after_item.get("state"), after_item.get("pos")):
                        return False
                    expected = allowed_names.get(
                        before_item["id"], before_item.get("name")
                    )
                    if after_item.get("name") != expected:
                        return False
            return True

        for scene_id, before in before_scene.items():
            card_id = before["card"]["id"]
            after = after_cards.get(card_id)
            if not after:
                protection_errors.append(f"{scene_id}: card missing")
                continue
            invariant = (
                before["card"].get("name") == after.get("name")
                and before["card"].get("desc") == after.get("desc")
                and before["card"].get("idList") == after.get("idList")
                and before["card"].get("closed") == after.get("closed")
                and sorted(before["card"].get("idLabels", []))
                == sorted(after.get("idLabels", []))
                and before["comments"]
                == after_support["comments"].get(card_id, [])
                and verify_checklists(
                    before["checklists"],
                    after_support["checklists"].get(card_id, []),
                    expected_item_names,
                )
            )
            after_attachments = attachment_projection(
                after_support["attachments"].get(card_id, [])
            )
            attachments_preserved = all(
                after_attachments.get(key) == value
                for key, value in before["attachments"].items()
            )
            if not invariant or not attachments_preserved:
                protection_errors.append(
                    f"{scene_id}: protected scene data changed"
                )

        for stable_name, before in existing_targets.items():
            card_id = before["card"]["id"]
            after = after_cards.get(card_id)
            after_attachments = attachment_projection(api["trello_get"](
                f"/cards/{card_id}/attachments",
                {"fields": "id,name,url,bytes,date"},
            ))
            invariant = bool(after) and (
                before["card"].get("name") == after.get("name")
                and before["card"].get("idList") == after.get("idList")
                and outside_auto_block(before["card"].get("desc") or "")
                == outside_auto_block(after.get("desc") or "")
                and set(before["card"].get("idLabels", []))
                .issubset(set(after.get("idLabels", [])))
                and before["comments"]
                == after_support["comments"].get(card_id, [])
                and verify_checklists(
                    before["checklists"],
                    after_support["checklists"].get(card_id, []), {},
                )
                and all(
                    after_attachments.get(key) == value
                    for key, value in before["attachments"].items()
                )
            )
            if not invariant:
                protection_errors.append(
                    f"{stable_name}: protected registry data changed"
                )

        for card_id, before in before_sets.items():
            after = after_cards.get(card_id)
            if not after or not (
                before.get("name") == after.get("name")
                and before.get("desc") == after.get("desc")
                and before.get("idList") == after.get("idList")
                and before.get("closed") == after.get("closed")
                and set(before.get("idLabels", []))
                .issubset(set(after.get("idLabels", [])))
            ):
                protection_errors.append(
                    f"set {before.get('name')}: protected data changed"
                )

        return jsonify({
            "status": mode,
            "writes": writes,
            "selected_identities": selected_names,
            "selected_scenes": selected_scene_ids,
            "selected_set_cards": len(selected_set_cards),
            "operations": operations,
            "questions_added": questions_added,
            "protected_preserved": not protection_errors,
            "protection_errors": protection_errors,
            "remaining_identities": max(
                0, len(identity_plans) - start - len(selected_names)
            ) if mode == "apply" else len(identity_plans) - len(selected_names),
        }), 200 if not protection_errors else 500

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
