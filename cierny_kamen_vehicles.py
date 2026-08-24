from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from flask import jsonify, request


KEY = "ck-vehicles-24aug-c3857a14"
ENDPOINT_DISABLED = False
BOARD_REF = "CzuD55PR"
CARD_URL = re.compile(r"\|\s*KARTA:\s*(https://trello\.com/c/[A-Za-z0-9]+)", re.I)
VEHICLE_WORDS = ("auto", "vozidl", "taxi", "taxik", "dodav", "pickup", "pohreb", "koroner", "cln", "pramica", "lod")


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


def identity_text(item):
    value = re.split(r"\s+[–—]\s+", item or "", maxsplit=1)[0]
    value = re.sub(r"^(?:<n>|\[n\])\s*", "", value, flags=re.I)
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
        kind = next((vehicle_kind(value) for value in card_aliases if vehicle_kind(value)), None)
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
                if not master and len(alias_matches) == 1:
                    master = alias_matches[0]
                    url = master["url"]
                kind = vehicle_kind(core) or (master or {}).get("kind")
                if not kind:
                    continue
                evidence = "checklist identity" if vehicle_kind(core) else "linked vehicle master"
                row = {
                    "scene_id": card["scene_id"], "scene_url": card.get("shortUrl"), "scene_list": card["list_name"],
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
            action = "conflict" if master.get("closed") else ("unchanged" if master["in_autá"] and "Auto" in master["labels"] else "move+label" if not master["in_autá"] else "label")
            confidence = "confirmed"
        else:
            action = "create" if first["master_url"] is None else "conflict"
            confidence = "confirmed" if vehicle_kind(first["identity"]) else "ambiguous"
        candidates.append({
            "canonical_name": (master or {}).get("name") or first["identity"],
            "aliases": (master or {}).get("aliases", [first["identity"]]),
            "kind": first["kind"], "owner": None,
            "current_list": (master or {}).get("list"), "labels": (master or {}).get("labels", []),
            "master_closed": (master or {}).get("closed", False),
            "master_url": first.get("master_url"), "occurrences": [{"scene_id": row["scene_id"], "item_text": row["item_text"], "scene_url": row["scene_url"]} for row in rows],
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
        1 for master in master_cards if folded(master["name"]) == folded(row["canonical_name"])) > 1]
    return {
        "status": "read-only-dry-run", "writes": 0,
        "board": {"name": board["name"], "url": board["url"]},
        "scene_cards_scanned": len(scene_cards), "vehicle_occurrences": len(occurrences),
        "vehicle_masters": len(master_cards), "candidates": candidates,
        "source_vehicle_candidates": source_candidates, "unresolved": unresolved,
        "duplicates_or_aliases": duplicates,
        "planned": {"move": sum(row["planned_action"] == "move+label" for row in candidates),
                    "label": sum(row["planned_action"] == "label" for row in candidates),
                    "create": sum(row["planned_action"] == "create" for row in candidates),
                    "conflicts": sum(row["planned_action"] == "conflict" for row in candidates),
                    "todo_writes": 0, "microsoft_writes": 0},
        "exclusions": ["original screener", "archív", "ToDo", "registry karty ako scény", "SET", "[z]"],
    }


def register_routes(app, api):
    @app.route("/api/cierny-kamen-vehicles", methods=["POST"])
    def cierny_kamen_vehicles():
        if ENDPOINT_DISABLED:
            return jsonify({"status": "disabled"}), 410
        if request.headers.get("X-CK-Vehicles-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        if request.args.get("mode", "dry-run").casefold() not in {"dry-run", "audit"}:
            return jsonify({"error": "read-only dry-run only", "writes": 0}), 409
        try:
            return jsonify(build_audit(api)), 200
        except Exception as exc:
            app.logger.exception("Čierny Kameň vehicle audit failed")
            return jsonify({"status": "failed", "writes": 0, "error": f"{type(exc).__name__}: {exc}"}), 502
