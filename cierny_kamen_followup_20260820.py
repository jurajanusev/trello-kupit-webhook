from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from flask import jsonify, request

from cierny_kamen_all_props_registry import (
    PROP_AUTO_END,
    PROP_AUTO_START,
    exact_named,
    folded,
    replace_auto_block,
)
from cierny_kamen_global_reference import desired_description
from cierny_kamen_meeting_semantic_dryrun import load_board
from cierny_kamen_prop_identity_resolution import strip_technical_wrappers


KEY = "ck-followup-20aug-4f91d37c"
ENDPOINT_DISABLED = False
URL_RE = re.compile(r"https://trello\.com/c/[A-Za-z0-9]+", re.I)
LEGACY_HEADINGS = {
    "rekvizity v kontexte", "nadvaznost", "odkazy",
    "kontinuita priestoru", "kontinuita postav",
}
EXCLUDED_LIST_PARTS = (
    "original screener", "register", "rekvizit", "os. rekvizity",
    "nadvazne sety", "todo", "priestor", "auta",
)
MAP_PATH = Path(__file__).with_name("cierny_kamen_all_props_registry_map.json")
CONTINUITY_LABEL = "Nadväzná rekvizita"
QUESTION_CHECKLIST = "OTÁZKY NA PORADU"
GLOBAL_PROP_LIST = "REGISTER REKVIZÍT"
AUTO_BLOCK_RE = re.compile(r"<!--\s*[A-Z0-9_-]+(?::[A-Z0-9_-]+)*:START\s*-->.*?<!--\s*[A-Z0-9_-]+(?::[A-Z0-9_-]+)*:END\s*-->", re.S | re.I)
KNOWN_AUTOMATED_N_IDENTITIES = {
    "Doggyho slúchadlá",
    "BANNER NA OTVORENIE BASKETBALOVEJ SEZÓNY",
    "Drevená pramica Jakuba a Sáry",
    "Výbava skautskej skupiny",
}
OWNER_ALIASES = {
    "alex": ("alexov", "alexova", "alexove", "alex"),
    "bety": ("betin", "betina", "betynina", "bety"),
    "kiko": ("kikov", "kikova", "kiko"),
    "veronika": ("veronikin", "veronikina", "veronika"),
    "dogy": ("dogyho", "dogy", "dagyho", "dagy"),
}


def starts_n(value):
    return bool(re.match(r"^\s*<n>(?:\s|\*|$)", value or "", re.I))


def contains_z(value):
    return "[z]" in (value or "").casefold()


def sha(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def without_card_suffix(value):
    return re.sub(r"\s*\|\s*KARTA:\s*https://trello\.com/c/[A-Za-z0-9]+", "", value or "", flags=re.I).rstrip()


def with_card_suffix(value, url):
    return f"{without_card_suffix(value)} | KARTA: {url}"


def clean_alias(value):
    text = strip_technical_wrappers(value)
    text = re.sub(r"^niekde v priestore\s+", "", text, flags=re.I)
    text = re.split(r"\s+-\s+|\s+nadv\.?\s*|\s+z\s+\d{1,2}/", text, maxsplit=1, flags=re.I)[0]
    text = text.replace("[z]", "").strip(" .,-")
    return text if 2 < len(text) <= 100 else ""


def master_block(canonical, rows, aliases=(), source_urls=(), categories=()):
    alias_values = {alias.strip() for alias in aliases if alias and folded(alias) != folded(canonical)}
    for row in rows:
        alias = clean_alias(row.get("text") or row.get("identity_core") or "")
        if alias and folded(alias) != folded(canonical):
            alias_values.add(alias)
    occurrences = []
    seen = set()
    for row in sorted(rows, key=lambda item: (item["scene_id"], item.get("pos") or 0)):
        if row["scene_id"] in seen:
            continue
        seen.add(row["scene_id"])
        occurrences.append(f"- [{row['scene_id']}]({row['scene_url']})")
    timeline = [f"- {row['scene_id']}: {without_card_suffix(row.get('text') or row.get('identity_core') or '')}"
                for row in sorted(rows, key=lambda item: (item["scene_id"], item.get("pos") or 0))]
    sources = ""
    if source_urls:
        sources = "\n\n### ZLÚČENÉ ZDROJOVÉ KARTY\n" + "\n".join(f"- {url}" for url in sorted(set(source_urls)))
    category_values = {CONTINUITY_LABEL, *(category for category in categories if category and category != "—")}
    return (
        f"{PROP_AUTO_START}\nKANONICKÝ NÁZOV: {canonical}\n"
        f"ALIASY: {', '.join(sorted(alias_values, key=folded)) if alias_values else '—'}\n"
        f"KATEGÓRIE: {', '.join(sorted(category_values, key=folded))}\n\n### VÝSKYTY V OBRAZOCH\n"
        + ("\n".join(occurrences) if occurrences else "- —")
        + "\n\n### ČASOVÁ OS\n" + ("\n".join(timeline) if timeline else "- —")
        + sources + f"\n{PROP_AUTO_END}"
    )


def is_production_list(name):
    key = folded(name)
    return bool(key) and not any(part in key for part in EXCLUDED_LIST_PARTS)


def bag_type(value):
    key = folded(strip_technical_wrappers(value))
    if re.search(r"\b(?:batoh|skolsk\w*\s+(?:task|batoh))", key):
        return "školská taška"
    return None


def explicit_school_bag(value):
    key = folded(strip_technical_wrappers(value))
    return bool(re.search(r"\bskolsk\w*\b", key) and re.search(r"\b(?:task|batoh)\w*\b", key))


def bag_owner(value):
    key = folded(strip_technical_wrappers(value))
    for owner, aliases in OWNER_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\w*\b", key) for alias in aliases):
            return owner
    return None


def known_automated_n(value):
    core = folded(strip_technical_wrappers(value))
    return core in {folded(name) for name in KNOWN_AUTOMATED_N_IDENTITIES}


def owner_from_list(list_name):
    match = re.match(r"^\s*(.+?)\s*[–—-]\s*OS\.\s*REKVIZITY\s*$", list_name or "", re.I)
    return match.group(1).strip() if match else None


def card_prop_rows(card):
    rows = []
    for checklist in card.get("checklists", []):
        if folded(checklist.get("name")) != "rekvizity":
            continue
        for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
            text = item.get("name") or ""
            rows.append({
                "card_id": card["id"], "checklist_id": checklist["id"],
                "item_id": item["id"], "text": text,
                "state": item.get("state"), "pos": item.get("pos"),
                "urls": URL_RE.findall(text), "has_n": starts_n(text),
                "has_z": contains_z(text), "text_sha256": sha(text),
            })
    return rows


def production_scenes(api, state):
    groups = defaultdict(list)
    for card in state["cards"]:
        if not is_production_list(card.get("list_name")):
            continue
        info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
        if not info or info.get("test"):
            continue
        groups[info["scene_id"]].append(card)
    return dict(groups)


def load_archived_list_cards(api, state):
    result = []
    for board_list in state["lists"]:
        if not board_list.get("closed"):
            continue
        if "rekviz" not in folded(board_list.get("name")) and folded(board_list.get("name")) != "auta":
            continue
        rows = api["trello_get"](f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels,dateLastActivity",
            "filter": "all", "limit": 1000,
        })
        for card in rows:
            result.append({**card, "list_name": board_list.get("name")})
    return result


def master_cards(api, state):
    candidates = []
    for card in state["cards"]:
        list_name = card.get("list_name") or ""
        if "rekviz" in folded(list_name) or folded(list_name) == "auta":
            candidates.append(card)
    known = {card["id"] for card in candidates}
    for card in load_archived_list_cards(api, state):
        if card["id"] not in known:
            candidates.append(card); known.add(card["id"])
    return candidates


def aliases_from_master(card):
    desc = card.get("desc") or ""
    aliases = []
    match = re.search(r"(?im)^ALIASY:\s*(.+)$", desc)
    if match and match.group(1).strip() != "—":
        aliases.extend(part.strip() for part in match.group(1).split(",") if part.strip())
    return aliases


def categories_from_master(card):
    match = re.search(r"(?im)^KATEGÓRIE:\s*(.+)$", card.get("desc") or "")
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _manual_n_status(row, previous):
    if not row["has_n"]:
        return None
    if not previous:
        return "new_item_after_identity_map"
    if not starts_n(previous.get("original_name")):
        return "n_added_after_identity_map"
    return "already_known_n"


def card_detail(api, card_id):
    detail = api["trello_get"](f"/cards/{card_id}", {
        "fields": "id,name,desc,shortUrl,idList,closed,pos,idLabels,dateLastActivity",
        "checklists": "all", "checklist_fields": "name,pos",
        "attachments": "true", "attachment_fields": "id,name,url,bytes,date",
    })
    detail["comments"] = api["trello_get"](f"/cards/{card_id}/actions", {
        "filter": "commentCard", "limit": 1000,
    })
    return detail


def bag_survivor_plan(api, duplicate_group, bag_occurrences):
    evidence = []
    for candidate in duplicate_group["cards"]:
        detail = card_detail(api, candidate["id"])
        manual_desc = AUTO_BLOCK_RE.sub("", detail.get("desc") or "").strip()
        occurrence_count = sum(
            candidate["url"].casefold() in {url.casefold() for url in row["urls"]}
            for row in bag_occurrences
        )
        row = {
            **candidate,
            "manual_desc_chars": len(manual_desc),
            "attachment_count": len(detail.get("attachments", [])),
            "comment_count": len(detail.get("comments", [])),
            "linked_occurrences": occurrence_count,
        }
        row["evidence_score"] = (
            row["manual_desc_chars"] + row["attachment_count"] * 500
            + row["comment_count"] * 200 + row["linked_occurrences"] * 100
        )
        evidence.append(row)
    evidence.sort(key=lambda row: (-row["evidence_score"], row["id"]))
    return {
        "owner": duplicate_group["owner"], "survivor": evidence[0],
        "duplicates": evidence[1:], "evidence": evidence,
        "action": "merge_confirmed_school_bag_aliases",
    }


def build_audit(api):
    state = load_board(api)
    groups = production_scenes(api, state)
    scene_cards = {scene_id: rows[0] for scene_id, rows in groups.items() if len(rows) == 1}
    collisions = {scene_id: [card.get("shortUrl") for card in rows]
                  for scene_id, rows in groups.items() if len(rows) != 1}
    payload = api["cierny_kamen_import_payload"]()
    source_ids = {scene["scene_id"] for scene in payload["scenes"]}

    description_ops, description_conflicts, old_description_cards = [], [], []
    all_rows = []
    for scene_id, card in sorted(scene_cards.items()):
        rows = card_prop_rows(card)
        all_rows.extend({"scene_id": scene_id, "scene_url": card.get("shortUrl"), **row} for row in rows)
        desc = card.get("desc") or ""
        heading_keys = {folded(value) for value in re.findall(r"(?m)^#{2,3}\s+(.+?)\s*$", desc)}
        legacy = sorted(heading_keys & LEGACY_HEADINGS)
        if not legacy:
            continue
        old_description_cards.append({"scene_id": scene_id, "url": card.get("shortUrl"), "legacy": legacy})
        desired, conflict, preserved = desired_description(desc, rows)
        if conflict:
            description_conflicts.append({"scene_id": scene_id, "url": card.get("shortUrl"), "reason": conflict})
        elif desired != desc.strip():
            description_ops.append({
                "scene_id": scene_id, "card_id": card["id"], "url": card.get("shortUrl"),
                "before": desc, "after": desired,
                "before_sha256": sha(desc), "preserved_origins": [origin for origin, _ in preserved],
                "protected_z": [{"item_id": row["item_id"], "sha256": row["text_sha256"]}
                                for row in rows if row["has_z"]],
            })

    masters = master_cards(api, state)
    list_by_id = state["list_by_id"]
    masters_by_url = {(card.get("shortUrl") or "").casefold(): card for card in masters if card.get("shortUrl")}
    bag_rows = [row for row in all_rows if bag_type(row["text"])]
    bag_occurrences = []
    for row in bag_rows:
        linked = [masters_by_url[url.casefold()] for url in row["urls"] if url.casefold() in masters_by_url]
        bag_occurrences.append({
            **{key: row[key] for key in ("scene_id", "scene_url", "item_id", "text", "state", "urls", "has_n", "has_z")},
            "linked_masters": [{
                "id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
                "closed": card.get("closed"),
                "list": list_by_id.get(card.get("idList"), {}).get("name") or card.get("list_name"),
            } for card in linked],
        })
    bag_master_candidates = []
    for card in masters:
        aliases = aliases_from_master(card)
        if bag_type(card.get("name")) or any(bag_type(alias) for alias in aliases):
            list_name = list_by_id.get(card.get("idList"), {}).get("name") or card.get("list_name")
            bag_master_candidates.append({
                "id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
                "closed": card.get("closed"), "list": list_name,
                "owner_from_list": owner_from_list(list_name), "aliases": aliases,
                "desc_sha256": sha(card.get("desc") or ""),
            })
    by_owner = defaultdict(list)
    for card in bag_master_candidates:
        if not card["closed"] and card["owner_from_list"] and explicit_school_bag(card["name"]):
            by_owner[folded(card["owner_from_list"])].append(card)
    bag_duplicate_groups = [
        {"owner": owner, "cards": cards, "action": "review_same_owner_school_bag_identity"}
        for owner, cards in sorted(by_owner.items()) if len(cards) > 1
    ]
    bag_merge_plans = [bag_survivor_plan(api, group, bag_occurrences)
                       for group in bag_duplicate_groups]
    bag_conflicts = [row for row in bag_occurrences if len(row["linked_masters"]) != 1]

    identity_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    old_by_item = {row["item_id"]: row for row in identity_map["records"]}
    canonical_lookup = defaultdict(list)
    alias_lookup = defaultdict(list)
    owner_school_lookup = defaultdict(list)
    for card in masters:
        if card.get("closed"):
            continue
        canonical_lookup[folded(card.get("name"))].append(card)
        for alias in aliases_from_master(card):
            alias_lookup[folded(alias)].append(card)
        if explicit_school_bag(card.get("name")):
            owner = bag_owner(card.get("name")) or folded(owner_from_list(
                list_by_id.get(card.get("idList"), {}).get("name") or card.get("list_name")
            ))
            if owner:
                owner_school_lookup[owner].append(card)

    def resolve_manual(row):
        linked = [masters_by_url[url.casefold()] for url in row["urls"] if url.casefold() in masters_by_url]
        if len(linked) == 1:
            return linked, "existing_master_url", None
        if len(linked) > 1:
            return linked, "conflict_multiple_master_urls", None
        core = folded(strip_technical_wrappers(row["text"]))
        exact = canonical_lookup.get(core, []) or alias_lookup.get(core, [])
        if len(exact) == 1:
            return exact, "canonical_or_alias", None
        prefix = []
        for name, cards in list(canonical_lookup.items()) + list(alias_lookup.items()):
            if core == name or re.match(rf"^{re.escape(name)}(?:\s+(?:-|nadv|z\b|v\b|pri\b|z\s+\d))", core):
                prefix.extend(cards)
        prefix = list({card["id"]: card for card in prefix}.values())
        if len(prefix) == 1:
            return prefix, "canonical_or_alias_prefix", None
        contained = []
        for name, cards in list(canonical_lookup.items()) + list(alias_lookup.items()):
            if len(name) >= 10 and re.search(rf"\b{re.escape(name)}\b", core):
                contained.extend(cards)
        contained = list({card["id"]: card for card in contained}.values())
        if len(contained) == 1:
            return contained, "canonical_or_alias_contained", None
        explicit_create = (
            ("plachta na mrtve telo", "Plachta na mŕtve telo"),
            ("flasa na hru", "Fľaša na hru"),
        )
        for token, canonical in explicit_create:
            if core.startswith(token):
                return [], "create_explicit_continuity_identity", canonical
        if bag_type(row["text"]):
            owner = bag_owner(row["text"])
            owner_cards = owner_school_lookup.get(owner, []) if owner else []
            if len(owner_cards) == 1:
                return owner_cards, "owner_plus_school_bag_type", None
            if owner and not owner_cards:
                canonical = {
                    "alex": "Alexova školská taška", "bety": "Betina školská taška",
                    "kiko": "Kikova školská taška", "veronika": "Veronikina školská taška",
                    "dogy": "Dogyho školská taška",
                }.get(owner)
                return [], "create_confirmed_owner_school_bag", canonical
            if len(owner_cards) > 1:
                return owner_cards, "conflict_duplicate_owner_school_bag_masters", None
        return [], "conflict_unresolved_identity", None

    manual_n = []
    automated_n_excluded = []
    for row in all_rows:
        if not (row["scene_id"].startswith("01/") or row["scene_id"].startswith("02/")):
            continue
        status = _manual_n_status(row, old_by_item.get(row["item_id"]))
        if status in {"new_item_after_identity_map", "n_added_after_identity_map"}:
            if known_automated_n(row["text"]):
                automated_n_excluded.append({"scene_id": row["scene_id"], "item_id": row["item_id"],
                                             "identity_core": strip_technical_wrappers(row["text"])})
                continue
            linked, resolution, create_name = resolve_manual(row)
            manual_n.append({
                **{key: row[key] for key in ("scene_id", "scene_url", "card_id", "checklist_id", "item_id", "text", "state", "pos", "urls", "has_z", "text_sha256")},
                "status": status,
                "identity_core": strip_technical_wrappers(row["text"]),
                "linked_masters": [{"id": card["id"], "name": card.get("name"),
                                    "url": card.get("shortUrl"), "closed": card.get("closed"),
                                    "idLabels": card.get("idLabels", [])} for card in linked],
                "resolution": resolution, "create_name": create_name,
            })

    labels = exact_named(state["labels"], CONTINUITY_LABEL)
    safe_manual_resolutions = {
        "existing_master_url", "canonical_or_alias", "canonical_or_alias_prefix",
        "canonical_or_alias_contained", "owner_plus_school_bag_type",
        "create_confirmed_owner_school_bag", "create_explicit_continuity_identity",
    }
    manual_n_planned = [row for row in manual_n if row["resolution"] in safe_manual_resolutions]
    full_master_by_id = {card["id"]: card for card in masters}
    identity_groups = defaultdict(list)
    for row in manual_n_planned:
        if row["linked_masters"]:
            key = f"card:{row['linked_masters'][0]['id']}"
        else:
            key = f"create:{folded(row['create_name'])}"
        identity_groups[key].append(row)
    identity_plans = []
    for key, rows in sorted(identity_groups.items()):
        target = None
        canonical = rows[0].get("create_name")
        if key.startswith("card:"):
            target = full_master_by_id.get(key.split(":", 1)[1])
            canonical = target.get("name") if target else rows[0]["linked_masters"][0]["name"]
        target_url = target.get("shortUrl") if target else None
        confirmed = list(rows)
        if target_url:
            confirmed.extend(row for row in all_rows
                             if row["has_n"] and target_url.casefold() in {url.casefold() for url in row["urls"]}
                             and row["item_id"] not in {item["item_id"] for item in confirmed})
        expected_block = master_block(
            canonical, confirmed,
            aliases_from_master(target) if target else (),
            categories=categories_from_master(target) if target else (),
        )
        item_updates = [row["item_id"] for row in rows
                        if not row["has_z"] and (not target_url or [url.casefold() for url in row["urls"]] != [target_url.casefold()])]
        identity_plans.append({
            "key": key, "canonical": canonical,
            "target": None if not target else {"id": target["id"], "name": target.get("name"),
                                                "url": target_url, "closed": target.get("closed"),
                                                "idLabels": target.get("idLabels", [])},
            "scene_ids": sorted({row["scene_id"] for row in rows}),
            "rows": rows, "protected_z_rows": sum(row["has_z"] for row in rows),
            "item_updates_pending": len(item_updates),
            "label_pending": bool(target and len(labels) == 1 and labels[0]["id"] not in target.get("idLabels", [])),
            "block_pending": bool(target and expected_block not in (target.get("desc") or "")),
            "create_pending": target is None, "expected_block": expected_block,
        })

    existing_questions = defaultdict(set)
    for scene_id, card in scene_cards.items():
        for checklist in card.get("checklists", []):
            if folded(checklist.get("name")) == folded(QUESTION_CHECKLIST):
                existing_questions[scene_id].update(folded(item.get("name")) for item in checklist.get("checkItems", []))
    question_plans = []
    for row in manual_n:
        if row["resolution"] in safe_manual_resolutions:
            continue
        core = (row["identity_core"] or "").replace("[z]", "").strip()
        question = f"Potvrdiť identitu <n> rekvizity v obraze {row['scene_id']}: „{core}“ a jej master kartu."
        if folded(question) not in existing_questions[row["scene_id"]]:
            question_plans.append({"scene_id": row["scene_id"], "card_id": row["card_id"],
                                   "item_id": row["item_id"], "question": question,
                                   "source_has_z": row["has_z"], "source_sha256": row["text_sha256"]})
    identity_pending = sum(
        plan["item_updates_pending"] + int(plan["create_pending"])
        + int(plan["label_pending"]) + int(plan["block_pending"])
        for plan in identity_plans
    )
    z_rows = [row for row in all_rows if row["has_z"]]
    return {
        "status": "read-only-dry-run", "writes": 0,
        "board": state["board"],
        "counts": {
            "production_scene_cards": len(scene_cards), "source_scene_ids": len(source_ids),
            "extra_scene_ids": len(set(scene_cards) - source_ids), "collisions": len(collisions),
            "old_descriptions": len(old_description_cards),
            "description_updates": len(description_ops), "description_conflicts": len(description_conflicts),
            "prop_items": len(all_rows), "protected_z_items": len(z_rows),
            "bag_occurrences": len(bag_occurrences), "bag_master_candidates": len(bag_master_candidates),
            "bag_duplicate_groups": len(bag_duplicate_groups), "bag_conflicts": len(bag_conflicts),
            "manual_n_new_or_changed_ep01_02": len(manual_n),
            "known_automated_n_excluded": len(automated_n_excluded),
            "manual_n_with_existing_master": len(manual_n_planned),
            "manual_n_conflicts": len(manual_n) - len(manual_n_planned),
        },
        "production_lists": sorted({card.get("list_name") for card in scene_cards.values()}),
        "extra_scene_ids": sorted(set(scene_cards) - source_ids), "collisions": collisions,
        "old_description_cards": old_description_cards,
        "description_conflicts": description_conflicts,
        "description_ops": description_ops,
        "bag_occurrences": bag_occurrences,
        "bag_master_candidates": bag_master_candidates,
        "bag_duplicate_groups": bag_duplicate_groups, "bag_conflicts": bag_conflicts,
        "bag_merge_plans": bag_merge_plans,
        "manual_n": manual_n,
        "manual_identity_plans": identity_plans,
        "manual_question_plans": question_plans,
        "known_automated_n_excluded": automated_n_excluded,
        "continuity_label_matches": [{"id": row["id"], "name": row.get("name")} for row in labels],
        "protected_z": [{"scene_id": row["scene_id"], "item_id": row["item_id"],
                         "text": row["text"], "sha256": row["text_sha256"]} for row in z_rows],
        "planned": {
            "description_writes": len(description_ops),
            "bag_identity_writes": len(bag_merge_plans),
            "manual_identity_groups": len(identity_plans),
            "manual_item_updates": sum(plan["item_updates_pending"] for plan in identity_plans),
            "manual_master_creates": sum(plan["create_pending"] for plan in identity_plans),
            "manual_master_label_updates": sum(plan["label_pending"] for plan in identity_plans),
            "manual_master_block_updates": sum(plan["block_pending"] or plan["create_pending"] for plan in identity_plans),
            "questions_to_add": len(question_plans),
            "total_pending_writes": (len(description_ops) + len(bag_merge_plans)
                                     + identity_pending + len(question_plans)),
            "todo_writes": 0, "microsoft_todo_writes": 0, "due_writes": 0,
        },
        "_state": state, "_scene_cards": scene_cards, "_masters": masters, "_all_rows": all_rows,
    }


def public(audit, details=False):
    hidden = {"_state", "_scene_cards", "_masters", "_all_rows"}
    if not details:
        hidden |= {"description_ops", "protected_z"}
    return {key: value for key, value in audit.items() if key not in hidden}


def _item_lookup(detail):
    return {item["id"]: (checklist, item)
            for checklist in detail.get("checklists", [])
            for item in checklist.get("checkItems", [])}


def _protected_without_desc(detail):
    return {
        "name": detail.get("name"), "idList": detail.get("idList"),
        "closed": detail.get("closed"), "idLabels": sorted(detail.get("idLabels", [])),
        "checklists": detail.get("checklists", []),
        "attachments": detail.get("attachments", []), "comments": detail.get("comments", []),
    }


def apply_description_sample(api, audit):
    if not audit["description_ops"]:
        return {"writes": 0, "scene_ids": [], "errors": []}
    op = audit["description_ops"][0]
    before = card_detail(api, op["card_id"])
    if sha(before.get("desc") or "") != op["before_sha256"]:
        return {"writes": 0, "scene_ids": [], "errors": ["description changed after dry-run"]}
    protected = _protected_without_desc(before)
    api["trello_put_body"](f"/cards/{op['card_id']}", {"desc": op["after"]})
    after = card_detail(api, op["card_id"])
    errors = []
    if after.get("desc") != op["after"]:
        errors.append("description read-back mismatch")
    if _protected_without_desc(after) != protected:
        errors.append("protected card data changed with description")
    return {"writes": 1, "scene_ids": [op["scene_id"]], "errors": errors,
            "url": op["url"], "before_sha256": op["before_sha256"],
            "after_sha256": sha(after.get("desc") or "")}


def _ensure_attachment(api, card_id, url, name):
    rows = api["trello_get"](f"/cards/{card_id}/attachments", {
        "fields": "id,name,url,bytes,date",
    })
    if any(row.get("url") == url for row in rows):
        return 0
    api["trello_post_body"](f"/cards/{card_id}/attachments", {"url": url, "name": name})
    return 1


def _update_item_url(api, row, target_url):
    if row.get("has_z"):
        return 0, None
    live = card_detail(api, row["card_id"])
    found = _item_lookup(live).get(row["item_id"])
    if not found:
        return 0, "checklist item missing"
    _, item = found
    if item.get("name") != row["text"] or item.get("state") != row["state"]:
        return 0, "checklist item changed after dry-run"
    desired = with_card_suffix(row["text"], target_url)
    if desired == row["text"]:
        return 0, None
    protected_z_before = {item_id: value.get("name") for item_id, (_, value) in _item_lookup(live).items()
                          if contains_z(value.get("name"))}
    api["trello_put_body"](f"/cards/{row['card_id']}/checkItem/{row['item_id']}", {"name": desired})
    after = card_detail(api, row["card_id"])
    after_item = _item_lookup(after).get(row["item_id"])
    if not after_item or after_item[1].get("name") != desired or after_item[1].get("state") != row["state"]:
        return 1, "checklist item read-back mismatch"
    protected_z_after = {item_id: value.get("name") for item_id, (_, value) in _item_lookup(after).items()
                         if contains_z(value.get("name"))}
    if protected_z_after != protected_z_before:
        return 1, "protected [z] item changed"
    return 1, None


def apply_bag_merge(api, audit):
    if not audit["bag_merge_plans"]:
        return {"writes": 0, "merged": [], "errors": []}
    plan = audit["bag_merge_plans"][0]
    survivor = plan["survivor"]
    duplicates = plan["duplicates"]
    if len(duplicates) != 1:
        return {"writes": 0, "merged": [], "errors": ["bag merge is not one-to-one"]}
    duplicate = duplicates[0]
    rows = [row for row in audit["_all_rows"]
            if duplicate["url"].casefold() in {url.casefold() for url in row["urls"]}]
    if any(row["has_z"] for row in rows):
        return {"writes": 0, "merged": [], "errors": ["duplicate URL occurs on protected [z] item"]}
    writes, errors = 0, []
    for row in rows:
        count, error = _update_item_url(api, row, survivor["url"])
        writes += count
        if error:
            errors.append({"scene_id": row["scene_id"], "error": error})
            break
        writes += _ensure_attachment(api, row["card_id"], survivor["url"], survivor["name"])
    if errors:
        return {"writes": writes, "merged": [], "errors": errors}
    survivor_live = card_detail(api, survivor["id"])
    duplicate_live = card_detail(api, duplicate["id"])
    confirmed = [row for row in audit["_all_rows"]
                 if row["has_n"] and (
                     survivor["url"].casefold() in {url.casefold() for url in row["urls"]}
                     or duplicate["url"].casefold() in {url.casefold() for url in row["urls"]}
                     or bag_owner(row["text"]) == plan["owner"] and bag_type(row["text"])
                 )]
    block = master_block(
        survivor["name"], confirmed,
        aliases={duplicate["name"], *aliases_from_master(survivor_live), *aliases_from_master(duplicate_live)},
        source_urls=[duplicate["url"]], categories=categories_from_master(survivor_live),
    )
    desired_desc = replace_auto_block(survivor_live.get("desc") or "", block)
    label_matches = exact_named(audit["_state"]["labels"], CONTINUITY_LABEL)
    if len(label_matches) != 1:
        return {"writes": writes, "merged": [], "errors": ["continuity label is not unique"]}
    desired_labels = sorted(set(survivor_live.get("idLabels", []))
                            | set(duplicate_live.get("idLabels", [])) | {label_matches[0]["id"]})
    body = {}
    if desired_desc != (survivor_live.get("desc") or ""):
        body["desc"] = desired_desc
    if desired_labels != sorted(survivor_live.get("idLabels", [])):
        body["idLabels"] = ",".join(desired_labels)
    if body:
        api["trello_put_body"](f"/cards/{survivor['id']}", body); writes += 1
    for row in confirmed:
        writes += _ensure_attachment(api, survivor["id"], row["scene_url"], row["scene_id"])
        writes += _ensure_attachment(api, row["card_id"], survivor["url"], survivor["name"])
    api["trello_put_body"](f"/cards/{duplicate['id']}", {"closed": "true"}); writes += 1
    read_survivor = card_detail(api, survivor["id"])
    read_duplicate = card_detail(api, duplicate["id"])
    if read_survivor.get("desc") != desired_desc or sorted(read_survivor.get("idLabels", [])) != desired_labels:
        errors.append("survivor read-back mismatch")
    if not read_duplicate.get("closed"):
        errors.append("duplicate master was not archived")
    return {"writes": writes, "merged": [{"survivor": survivor["url"], "archived": duplicate["url"],
                                           "redirected_items": len(rows)}], "errors": errors,
            "evidence": plan["evidence"]}


def _target_list_name(canonical):
    owner = bag_owner(canonical)
    if owner:
        return f"{owner.upper()} – OS. REKVIZITY"
    return GLOBAL_PROP_LIST


def _resolve_or_create_master(api, audit, plan):
    if plan["target"]:
        return plan["target"], 0, None
    matches = [card for card in audit["_masters"] if folded(card.get("name")) == folded(plan["canonical"])]
    if len(matches) > 1:
        return None, 0, "multiple open/archived exact master cards"
    list_matches = exact_named(audit["_state"]["lists"], _target_list_name(plan["canonical"]))
    if len(list_matches) != 1:
        return None, 0, f"target list is not unique: {_target_list_name(plan['canonical'])}"
    if matches:
        card = matches[0]
        body = {}
        if card.get("closed"):
            body["closed"] = "false"
        if card.get("idList") != list_matches[0]["id"]:
            body["idList"] = list_matches[0]["id"]
        if body:
            card = api["trello_put_body"](f"/cards/{card['id']}", body)
            return {"id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
                    "closed": card.get("closed"), "idLabels": card.get("idLabels", [])}, 1, None
        return {"id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
                "closed": card.get("closed"), "idLabels": card.get("idLabels", [])}, 0, None
    card = api["trello_post_body"]("/cards", {
        "idList": list_matches[0]["id"], "name": plan["canonical"], "desc": "", "pos": "bottom",
    })
    return {"id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
            "closed": False, "idLabels": card.get("idLabels", [])}, 1, None


def apply_identity_plan(api, audit, plan):
    target, writes, error = _resolve_or_create_master(api, audit, plan)
    if error:
        return {"canonical": plan["canonical"], "writes": writes, "error": error}
    errors = []
    for row in plan["rows"]:
        count, item_error = _update_item_url(api, row, target["url"])
        writes += count
        if item_error:
            errors.append({"scene_id": row["scene_id"], "error": item_error}); continue
        writes += _ensure_attachment(api, row["card_id"], target["url"], target["name"])
        writes += _ensure_attachment(api, target["id"], row["scene_url"], row["scene_id"])
    if errors:
        return {"canonical": plan["canonical"], "writes": writes, "error": errors}
    live = card_detail(api, target["id"])
    confirmed = list(plan["rows"])
    for row in audit["_all_rows"]:
        if (row["has_n"]
                and target["url"].casefold() in {url.casefold() for url in row["urls"]}
                and row["item_id"] not in {item["item_id"] for item in confirmed}):
            confirmed.append(row)
    block = master_block(target["name"], confirmed, aliases_from_master(live),
                         categories=categories_from_master(live))
    desired_desc = replace_auto_block(live.get("desc") or "", block)
    labels = exact_named(audit["_state"]["labels"], CONTINUITY_LABEL)
    if len(labels) != 1:
        return {"canonical": plan["canonical"], "writes": writes, "error": "continuity label is not unique"}
    desired_labels = sorted(set(live.get("idLabels", [])) | {labels[0]["id"]})
    body = {}
    if desired_desc != (live.get("desc") or ""):
        body["desc"] = desired_desc
    if desired_labels != sorted(live.get("idLabels", [])):
        body["idLabels"] = ",".join(desired_labels)
    if body:
        api["trello_put_body"](f"/cards/{target['id']}", body); writes += 1
    readback = card_detail(api, target["id"])
    if readback.get("desc") != desired_desc or sorted(readback.get("idLabels", [])) != desired_labels:
        return {"canonical": plan["canonical"], "writes": writes, "error": "master read-back mismatch"}
    return {"canonical": plan["canonical"], "url": target["url"], "writes": writes, "error": None,
            "scenes": plan["scene_ids"], "protected_z_rows": plan["protected_z_rows"]}


def apply_questions(api, audit, start, limit):
    selected = audit["manual_question_plans"][start:start + limit]
    writes, errors = 0, []
    for plan in selected:
        live = card_detail(api, plan["card_id"])
        source = _item_lookup(live).get(plan["item_id"])
        if not source or sha(source[1].get("name") or "") != plan["source_sha256"]:
            errors.append({"scene_id": plan["scene_id"], "error": "source <n> item changed"}); continue
        checklists = [row for row in live.get("checklists", []) if folded(row.get("name")) == folded(QUESTION_CHECKLIST)]
        if len(checklists) != 1:
            errors.append({"scene_id": plan["scene_id"], "error": "question checklist is not unique"}); continue
        if any(folded(item.get("name")) == folded(plan["question"]) for item in checklists[0].get("checkItems", [])):
            continue
        api["trello_post_body"](f"/checklists/{checklists[0]['id']}/checkItems", {
            "name": plan["question"], "checked": "false", "pos": "bottom",
        }); writes += 1
        after = card_detail(api, plan["card_id"])
        after_source = _item_lookup(after).get(plan["item_id"])
        if not after_source or sha(after_source[1].get("name") or "") != plan["source_sha256"]:
            errors.append({"scene_id": plan["scene_id"], "error": "source item changed while adding question"})
    return {"status": "questions-applied", "selected": len(selected), "writes": writes,
            "errors": errors, "scene_ids": [plan["scene_id"] for plan in selected]}


def final_checks(api, audit):
    errors = []
    detail_cache = {}

    def detail(card_id):
        if card_id not in detail_cache:
            detail_cache[card_id] = card_detail(api, card_id)
        return detail_cache[card_id]

    checked_links = 0
    for plan in audit["manual_identity_plans"]:
        target = plan.get("target")
        if not target:
            errors.append(f"{plan['canonical']}: master missing")
            continue
        master = detail(target["id"])
        master_urls = {row.get("url") for row in master.get("attachments", [])}
        for row in plan["rows"]:
            scene = detail(row["card_id"])
            scene_urls = {item.get("url") for item in scene.get("attachments", [])}
            if target["url"] not in scene_urls:
                errors.append(f"{row['scene_id']}:{plan['canonical']}: scene backlink missing")
            if row["scene_url"] not in master_urls:
                errors.append(f"{row['scene_id']}:{plan['canonical']}: master backlink missing")
            checked_links += 1
    companion_rows = [row for row in audit["_all_rows"]
                      if (row.get("text") or "").lstrip().startswith(("↳", "→", "←"))]
    return {
        "valid": not errors and audit["planned"]["total_pending_writes"] == 0,
        "errors": errors, "bidirectional_links_checked": checked_links,
        "current_companion_rows": len(companion_rows),
        "companion_rows_created_by_this_migration": 0,
        "protected_z_items": audit["counts"]["protected_z_items"],
        "todo_writes": 0, "microsoft_todo_writes": 0, "due_writes": 0,
    }


def register_routes(app, api):
    @app.route("/api/ck-followup-20260820", methods=["POST"])
    def ck_followup_20260820():
        if ENDPOINT_DISABLED:
            return jsonify({"error": "completed follow-up endpoint disabled"}), 410
        if request.headers.get("X-CK-Followup-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        if mode not in {"audit", "dry-run", "final-audit", "sample", "identities-apply", "questions-apply"}:
            return jsonify({"error": "unsupported mode", "writes": 0}), 405
        try:
            audit = build_audit(api)
            if mode in {"audit", "dry-run", "final-audit"}:
                result = public(audit, request.args.get("details") == "1")
                if mode == "final-audit":
                    result["final_checks"] = final_checks(api, audit)
                return jsonify(result), 200
            start = max(0, request.args.get("start", 0, type=int))
            limit = min(5, max(1, request.args.get("limit", 3, type=int)))
            if mode == "sample":
                description = apply_description_sample(api, audit)
                bag = apply_bag_merge(api, audit)
                if description["errors"] or bag["errors"]:
                    return jsonify({"status": "sample-failed", "description": description,
                                    "bag": bag, "writes": description["writes"] + bag["writes"]}), 409
                refreshed = build_audit(api)
                candidates = [plan for plan in refreshed["manual_identity_plans"]
                              if plan["canonical"] == "Drinkové poháre na párty u Sáry"]
                if len(candidates) != 1:
                    return jsonify({"status": "sample-blocked", "writes": description["writes"] + bag["writes"],
                                    "error": "manual <n> sample identity is not unique"}), 409
                identity = apply_identity_plan(api, refreshed, candidates[0])
                status = 200 if not identity.get("error") else 409
                return jsonify({"status": "sample-applied" if status == 200 else "sample-failed",
                                "description": description, "bag": bag, "identity": identity,
                                "writes": description["writes"] + bag["writes"] + identity["writes"]}), status
            if mode == "identities-apply":
                selected = audit["manual_identity_plans"][start:start + limit]
                results = [apply_identity_plan(api, audit, plan) for plan in selected]
                errors = [row for row in results if row.get("error")]
                return jsonify({"status": "identities-applied" if not errors else "identities-partial",
                                "selected": len(selected), "writes": sum(row["writes"] for row in results),
                                "results": results, "errors": errors}), 200 if not errors else 409
            return jsonify(apply_questions(api, audit, start, limit)), 200
        except Exception as exc:
            app.logger.exception("Cierny Kamen follow-up audit failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
