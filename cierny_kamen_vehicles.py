from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from flask import jsonify, request
from cierny_kamen_all_props_registry import (
    PROP_AUTO_END, PROP_AUTO_START, ensure_attachment, replace_auto_block,
)


KEY = "ck-vehicles-24aug-c3857a14"
ENDPOINT_DISABLED = False
BOARD_REF = "CzuD55PR"
CARD_URL = re.compile(r"\|\s*KARTA:\s*(https://trello\.com/c/[A-Za-z0-9]+)", re.I)
VEHICLE_WORDS = ("auto", "vozidl", "taxi", "taxik", "dodav", "pickup", "pohreb", "koroner", "cln", "pramica", "lod")
SAFE_CREATE_IDENTITIES = {"auto sary"}
CONFIRMED_ALIAS_TARGETS = {
    "cln sary a jakuba": "drevena pramica jakuba a sary",
}


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


def identity_text(item):
    value = re.split(r"\s+[–—]\s+", item or "", maxsplit=1)[0]
    value = re.sub(r"^(?:<n>|\[n\])\s*", "", value, flags=re.I)
    # [z] is a protected ToDo marker, never a part of the prop identity.
    value = re.sub(r"\s*\[z\]\s*", " ", value, flags=re.I)
    return value.replace("*", "").strip()


def vehicle_kind(value):
    value = folded(value)
    if any(value.startswith(prefix) for prefix in (
        "majak", "drot", "plachta", "veci", "kufor", "krabice", "vesla", "odznaky", "vybava", "rozpisana",
    )):
        return None
    if any(fragment in value for fragment in (
        " s ktorym ", " ktorym je auto", " na auto", " v aute", "pohrebna rec",
    )):
        return None
    if "automat" in value and not any(word in value for word in ("auto ", "auto-", "automobil")):
        return None
    if not any(word in value for word in VEHICLE_WORDS):
        return None
    if any(word in value for word in ("cln", "pramica", "lod")):
        return "watercraft"
    if "taxi" in value or "taxik" in value:
        return "taxi"
    if "pohreb" in value:
        return "hearse"
    if "koroner" in value:
        return "coroner_car"
    if "dodav" in value:
        return "van"
    if "pickup" in value:
        return "pickup"
    if "policajn" in value:
        return "police_car"
    return "car"


def aliases(card):
    result = {card.get("name", "")}
    desc = card.get("desc") or ""
    for field in ("KANONICKÝ NÁZOV", "ALIASY"):
        for value in re.findall(rf"(?mi)^{field}:\s*(.+)$", desc):
            result.update(part.strip() for part in value.split(",") if part.strip() not in {"—", "-"})
    return sorted(result, key=folded)


def prop_block(name, rows, categories):
    """Only the marked automatic block may be changed on a master card."""
    aliases = sorted({row["identity"] for row in rows if folded(row["identity"]) != folded(name)}, key=folded)
    timeline = []
    seen = set()
    for row in sorted(rows, key=lambda item: item["scene_id"]):
        if row["scene_id"] in seen:
            continue
        seen.add(row["scene_id"])
        timeline.append(f"- [{row['scene_id']}]({row['scene_url']}) — {row['identity']}")
    occurrence_links = [
        f"- [{row['scene_id']}]({row['scene_url']})"
        for row in sorted(rows, key=lambda item: item["scene_id"])
    ]
    return (
        f"{PROP_AUTO_START}\n"
        f"KANONICKÝ NÁZOV: {name}\n"
        f"ALIASY: {', '.join(aliases) if aliases else '—'}\n"
        f"KATEGÓRIE: {', '.join(sorted(categories, key=folded))}\n\n"
        "### VÝSKYTY V OBRAZOCH\n"
        f"{chr(10).join(occurrence_links) or '- —'}\n\n"
        "### ČASOVÁ OS\n"
        f"{chr(10).join(timeline) or '- —'}\n"
        f"{PROP_AUTO_END}"
    )


def excluded_scene_list(name):
    name = folded(name)
    return any(value in name for value in (
        "original screener", "todo", "register", "rekvizit", "nadvazne sety", "priestor", "auta",
    ))


def build_audit(api):
    board = api["trello_get"](f"/boards/{BOARD_REF}", {"fields": "id,name,url,shortLink"})
    lists = api["trello_get"](f"/boards/{board['id']}/lists", {"fields": "id,name,pos,closed", "filter": "all"})
    list_by_id = {item["id"]: item for item in lists}
    label_by_id = {item["id"]: item["name"] for item in api["trello_get"](
        f"/boards/{board['id']}/labels", {"fields": "id,name,color", "limit": 1000}
    )}
    all_cards, scene_cards = {}, []
    for board_list in lists:
        cards = api["trello_get"](f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,idList,shortUrl,closed,idLabels,pos", "filter": "all", "limit": 1000,
            "checklists": "all", "checklist_fields": "name,pos", "checklist_checkItems": "all",
        })
        for card in cards:
            all_cards[card["id"]] = card
        if board_list.get("closed") or excluded_scene_list(board_list["name"]):
            continue
        for card in cards:
            if card.get("closed"):
                continue
            info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
            if info and not info.get("test"):
                scene_cards.append({**card, "scene_id": info["scene_id"], "list_name": board_list["name"]})
    card_by_url = {(card.get("shortUrl") or "").casefold(): card for card in all_cards.values() if card.get("shortUrl")}
    auto_label_ids = {label_id for label_id, name in label_by_id.items() if folded(name) == "auto"}
    master_cards = []
    for card in all_cards.values():
        list_name = list_by_id.get(card.get("idList"), {}).get("name", "")
        list_fold = folded(list_name)
        is_vehicle_registry = (
            list_fold == "auta" or "register rekvizit" in list_fold
            or list_fold.endswith("os. rekvizity")
        )
        if not is_vehicle_registry:
            continue
        card_aliases = aliases(card)
        # An alias must not turn an unrelated registry card into a vehicle.
        # `Auto` is the only permitted fallback for a legacy vehicle whose
        # canonical title does not state its type (for example a limuzína).
        kind = vehicle_kind(card.get("name", ""))
        labels = sorted(label_by_id.get(label_id, label_id) for label_id in card.get("idLabels", []))
        if kind or auto_label_ids & set(card.get("idLabels", [])):
            master_cards.append({
                "id": card["id"], "name": card.get("name"), "url": card.get("shortUrl"),
                "list": list_name, "list_id": card.get("idList"), "closed": card.get("closed"),
                "aliases": card_aliases, "labels": labels, "kind": kind or "unknown_vehicle",
                "in_autá": folded(list_name) == "auta",
            })
    master_by_url = {card["url"].casefold(): card for card in master_cards if card.get("url")}
    master_by_alias = defaultdict(list)
    for master in master_cards:
        for alias in master["aliases"]:
            master_by_alias[folded(alias)].append(master)
    occurrences, unresolved = [], []
    for card in scene_cards:
        for checklist in card.get("checklists", []):
            if folded(checklist.get("name")) != "rekvizity":
                continue
            for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
                raw = item.get("name", "")
                core = identity_text(raw)
                link = CARD_URL.search(raw)
                url = link.group(1) if link else None
                master = master_by_url.get((url or "").casefold())
                alias_matches = master_by_alias.get(folded(core), []) if not master else []
                if not master and not alias_matches:
                    approved_target = CONFIRMED_ALIAS_TARGETS.get(folded(core))
                    alias_matches = master_by_alias.get(approved_target, []) if approved_target else []
                if not master and len(alias_matches) == 1:
                    master = alias_matches[0]
                    url = master["url"]
                core_kind = vehicle_kind(core)
                master_is_vehicle = bool(master and (master.get("kind") or any(
                    folded(label) == "auto" for label in master.get("labels", [])
                )))
                if not core_kind and not master_is_vehicle:
                    continue
                kind = core_kind or master.get("kind") or "unknown_vehicle"
                evidence = "checklist identity" if core_kind else "linked vehicle master"
                row = {
                    "card_id": card["id"], "scene_id": card["scene_id"], "scene_url": card.get("shortUrl"), "scene_list": card["list_name"],
                    "item_id": item.get("id"), "item_state": item.get("state"), "item_text": raw,
                    "identity": core, "kind": kind, "master_url": url,
                    "master_name": (master or {}).get("name"), "master_list": (master or {}).get("list"),
                    "evidence": evidence,
                }
                occurrences.append(row)
                if not master:
                    unresolved.append(row)
    by_master = defaultdict(list)
    for row in occurrences:
        key = row["master_url"] or f"MISSING:{folded(row['identity'])}:{row['scene_id']}"
        by_master[key].append(row)
    candidates = []
    for key, rows in sorted(by_master.items(), key=lambda row: (folded(row[1][0].get("master_name") or row[1][0]["identity"]), row[0])):
        first = rows[0]
        master = master_by_url.get((first.get("master_url") or "").casefold())
        if master:
            has_auto_label = any(folded(label) == "auto" for label in master["labels"])
            action = "conflict" if master.get("closed") else ("unchanged" if master["in_autá"] and has_auto_label else "move+label" if not master["in_autá"] else "label")
            confidence = "confirmed"
        else:
            identity_key = folded(first["identity"])
            action = "create" if identity_key in SAFE_CREATE_IDENTITIES else "defer"
            confidence = "confirmed" if action == "create" else "ambiguous"
        candidates.append({
            "canonical_name": (master or {}).get("name") or first["identity"],
            "master_id": (master or {}).get("id"),
            "aliases": (master or {}).get("aliases", [first["identity"]]),
            "kind": first["kind"], "owner": None,
            "current_list": (master or {}).get("list"), "labels": (master or {}).get("labels", []),
            "master_closed": (master or {}).get("closed", False),
            "master_url": first.get("master_url"), "occurrences": [{
                "card_id": row["card_id"], "scene_id": row["scene_id"], "item_id": row["item_id"],
                "item_text": row["item_text"], "scene_url": row["scene_url"], "item_state": row["item_state"],
            } for row in rows],
            "planned_action": action, "identity_evidence": [row["evidence"] for row in rows],
            "confidence": confidence,
        })
    source_candidates = []
    try:
        payload = api["cierny_kamen_import_payload"]()
        for scene in payload.get("scenes", []):
            for prop in scene.get("props", []):
                if "Auto" in prop.get("categories", []) or vehicle_kind(prop.get("stable_name", "")):
                    source_candidates.append({"scene_id": scene["scene_id"], "name": prop.get("stable_name"),
                                              "kind": vehicle_kind(prop.get("stable_name", "")),
                                              "categories": prop.get("categories", [])})
    except Exception as exc:
        source_candidates = [{"error": f"{type(exc).__name__}: {exc}"}]
    duplicates = [row for row in candidates if row["master_url"] and sum(
        1 for master in master_cards
        if not master.get("closed") and folded(master["name"]) == folded(row["canonical_name"])
    ) > 1]
    return {
        "status": "read-only-dry-run", "writes": 0,
        "board": {"name": board["name"], "url": board["url"]},
        "scene_cards_scanned": len(scene_cards), "vehicle_occurrences": len(occurrences),
        "vehicle_masters": len(master_cards), "candidates": candidates,
        "master_inventory": [{
            "name": item["name"], "url": item["url"], "list": item["list"],
            "closed": item["closed"], "labels": item["labels"], "aliases": item["aliases"],
        } for item in master_cards],
        "source_vehicle_candidates": source_candidates, "unresolved": unresolved,
        "duplicates_or_aliases": duplicates,
        "planned": {"move": sum(row["planned_action"] == "move+label" for row in candidates),
                    "label": sum(row["planned_action"] == "label" for row in candidates),
                    "create": sum(row["planned_action"] == "create" for row in candidates),
                    "defer": sum(row["planned_action"] == "defer" for row in candidates),
                    "conflicts": sum(row["planned_action"] == "conflict" for row in candidates),
                    "todo_writes": 0, "microsoft_writes": 0},
        "exclusions": ["original screener", "archív", "ToDo", "registry karty ako scény", "SET", "[z]"],
    }


def live_card(api, card_id):
    return api["trello_get"](f"/cards/{card_id}", {
        "fields": "id,name,desc,idList,shortUrl,idLabels,closed",
    })


def add_card_link(raw, url):
    if CARD_URL.search(raw or ""):
        return raw
    return f"{(raw or '').rstrip()} | KARTA: {url}"


def sync_master(api, master, auto_list_id, auto_label_id, candidate, rows):
    current = live_card(api, master["id"])
    if current.get("closed"):
        raise ValueError(f"master {current['name']} is archived")
    label_ids = set(current.get("idLabels", []))
    label_ids.add(auto_label_id)
    block = prop_block(current["name"], rows, {"Auto"} | set(candidate.get("labels", [])))
    description = replace_auto_block(current.get("desc", ""), block)
    api["trello_put_body"](f"/cards/{current['id']}", {
        "idList": auto_list_id, "idLabels": ",".join(sorted(label_ids)), "desc": description,
    })
    return live_card(api, current["id"])


def create_master(api, auto_list_id, auto_label_id, candidate, rows):
    created = api["trello_post_body"]("/cards", {
        "idList": auto_list_id, "name": candidate["canonical_name"],
        "desc": prop_block(candidate["canonical_name"], rows, {"Auto"}),
        "idLabels": auto_label_id,
    })
    return live_card(api, created["id"])


def link_occurrence(api, row, master):
    """Only append a missing technical link; do not rewrite a manual item."""
    card = live_card(api, row["card_id"])
    checklists = api["trello_get"](f"/cards/{card['id']}/checklists", {
        "checkItems": "all", "fields": "id,name,pos",
    })
    found = None
    for checklist in checklists:
        if folded(checklist.get("name")) != "rekvizity":
            continue
        found = next((item for item in checklist.get("checkItems", []) if item.get("id") == row["item_id"]), None)
    if not found:
        raise ValueError(f"missing live checklist item {row['item_id']}")
    expected = add_card_link(found.get("name", ""), master["shortUrl"])
    if expected != found.get("name", ""):
        api["trello_put_body"](f"/cards/{card['id']}/checkItem/{found['id']}", {"name": expected})
    ensure_attachment(api, master, card["shortUrl"], card["name"])
    ensure_attachment(api, card, master["shortUrl"], master["name"])
    return expected


def apply_changes(api, mode, start=0, limit=5):
    audit = build_audit(api)
    board_id = api["trello_get"](f"/boards/{BOARD_REF}", {"fields": "id"})["id"]
    lists = api["trello_get"](f"/boards/{board_id}/lists", {"fields": "id,name,closed", "filter": "open"})
    auto_lists = [item for item in lists if folded(item.get("name")) == "auta"]
    labels = api["trello_get"](f"/boards/{board_id}/labels", {"fields": "id,name", "limit": 1000})
    auto_labels = [item for item in labels if folded(item.get("name")) == "auto"]
    if len(auto_lists) != 1 or len(auto_labels) != 1:
        return {"status": "blocked", "writes": 0, "reason": "AUTÁ list or Auto label is not unique", "audit": audit}
    eligible = [item for item in audit["candidates"] if item["planned_action"] in {"move+label", "label", "create"}]
    if mode == "sample":
        moves = [item for item in eligible if item["planned_action"] in {"move+label", "label"}][:1]
        creates = [item for item in eligible if item["planned_action"] == "create"][:1]
        eligible = moves + creates
    else:
        eligible = eligible[start:start + limit]
    applied = []
    for candidate in eligible:
        # Rebuild the live rows from Trello immediately before each write.
        fresh = build_audit(api)
        current = next((item for item in fresh["candidates"] if item["canonical_name"] == candidate["canonical_name"] and item.get("master_url") == candidate.get("master_url")), None)
        if not current or current["planned_action"] not in {"move+label", "label", "create"}:
            applied.append({"name": candidate["canonical_name"], "status": "skipped-concurrent-change"})
            continue
        detailed = detailed_occurrences(api, current)
        if candidate["planned_action"] == "create":
            master = create_master(api, auto_lists[0]["id"], auto_labels[0]["id"], current, detailed)
        else:
            master = sync_master(api, {"id": current["master_id"]}, auto_lists[0]["id"], auto_labels[0]["id"], current, detailed)
        linked = [link_occurrence(api, row, master) for row in detailed]
        applied.append({"name": current["canonical_name"], "master_url": master["shortUrl"], "linked_items": len(linked), "status": "applied"})
    return {"status": "applied", "writes": len([row for row in applied if row["status"] == "applied"]), "applied": applied, "remaining": build_audit(api)["planned"]}


def detailed_occurrences(api, candidate):
    """Read cards immediately before writes; matching keeps state and manual text intact."""
    rows = []
    for occurrence in candidate["occurrences"]:
        card = live_card(api, occurrence["card_id"])
        checklists = api["trello_get"](f"/cards/{card['id']}/checklists", {
            "checkItems": "all", "fields": "id,name,pos",
        })
        item = next((item for checklist in checklists for item in checklist.get("checkItems", []) if item.get("id") == occurrence["item_id"]), None)
        if not item or item.get("name") != occurrence["item_text"]:
            raise ValueError(f"concurrent checklist change for {candidate['canonical_name']}")
        rows.append({"card_id": card["id"], "scene_id": occurrence["scene_id"], "scene_url": card["shortUrl"], "item_id": occurrence["item_id"], "identity": identity_text(item["name"])})
    return rows


def register_routes(app, api):
    @app.route("/api/cierny-kamen-vehicles", methods=["POST"])
    def cierny_kamen_vehicles():
        if ENDPOINT_DISABLED:
            return jsonify({"status": "disabled"}), 410
        if request.headers.get("X-CK-Vehicles-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        if mode not in {"dry-run", "audit", "sample", "apply"}:
            return jsonify({"error": "unsupported mode", "writes": 0}), 400
        try:
            if mode in {"dry-run", "audit"}:
                return jsonify(build_audit(api)), 200
            return jsonify(apply_changes(api, mode, int(request.args.get("start", "0")), int(request.args.get("limit", "5")))), 200
        except Exception as exc:
            app.logger.exception("Čierny Kameň vehicle audit failed")
            return jsonify({"status": "failed", "writes": 0, "error": f"{type(exc).__name__}: {exc}"}), 502
