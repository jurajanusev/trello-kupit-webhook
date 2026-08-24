from __future__ import annotations

import re
import unicodedata

from flask import jsonify, request


KEY = "ck-police-cars-audit-24aug-2d691fb0"
ENDPOINT_DISABLED = False
BOARD_REF = "CzuD55PR"
MASTER_URL = re.compile(r"\|\s*KARTA:\s*(https://trello\.com/c/[A-Za-z0-9]+)", re.I)


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


def police_car_classification(item_text, master_name=""):
    identity = re.split(r"\s+[–—]\s+", item_text or "", maxsplit=1)[0]
    identity = re.sub(r"^(?:<n>|\[n\])\s*", "", identity, flags=re.I)
    identity = identity.replace("*", "").strip()
    combined = folded(f"{identity} {master_name}")
    if "cln" in combined and not any(word in combined for word in ("auto", "vozidlo", "voz")):
        return None
    police = any(word in combined for word in ("policajn", "policie", "policajt"))
    vehicle = any(word in combined for word in ("auto", "vozidlo", "automobil"))
    if police and vehicle:
        return "confirmed"
    local = folded(identity)
    generic_river = any(phrase in combined for phrase in (
        "auto pri rieke", "auto odstavene pri rieke", "vozidlo pri rieke",
    ))
    owner_specific = any(name in combined for name in ("jakub", "sara", "olasovej"))
    if vehicle and generic_river and not owner_specific:
        return "ambiguous"
    return None


def _excluded_list(name):
    value = folded(name)
    return any(fragment in value for fragment in (
        "original screener", "todo", "register", "rekvizit", "nadvazne sety",
        "priestor", "auta",
    ))


def build_audit(api):
    board = api["trello_get"](f"/boards/{BOARD_REF}", {"fields": "id,name,url,shortLink"})
    lists = api["trello_get"](f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed,pos", "filter": "open",
    })
    all_cards = {}
    production = []
    for board_list in lists:
        cards = api["trello_get"](f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,idList,shortUrl,closed,idLabels,pos",
            "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name,pos",
        })
        for card in cards:
            all_cards[card["id"]] = card
        if _excluded_list(board_list.get("name")):
            continue
        for card in cards:
            info = api["cierny_kamen_scene_name_info"](card.get("name", ""))
            if info and not info.get("test"):
                production.append({**card, "scene_id": info["scene_id"], "list_name": board_list["name"]})
    by_url = {(card.get("shortUrl") or "").rstrip("/").casefold(): card for card in all_cards.values()
              if card.get("shortUrl")}
    rows = []
    unresolved = []
    for card in production:
        for checklist in card.get("checklists", []):
            if folded(checklist.get("name")) != "rekvizity":
                continue
            for item in sorted(checklist.get("checkItems", []), key=lambda row: row.get("pos", 0)):
                text = item.get("name", "").strip()
                match = MASTER_URL.search(text)
                master_url = match.group(1) if match else None
                master = by_url.get((master_url or "").rstrip("/").casefold())
                master_name = master.get("name", "") if master else ""
                classification = police_car_classification(text, master_name)
                if not classification:
                    continue
                row = {
                    "scene_id": card["scene_id"], "scene_name": card.get("name"),
                    "scene_url": card.get("shortUrl"), "production_list": card["list_name"],
                    "item_id": item.get("id"), "item_state": item.get("state"),
                    "item_text": text, "classification": classification,
                    "master_url": master_url, "master_name": master_name or None,
                    "master_list": next((lst["name"] for lst in lists if master and lst["id"] == master.get("idList")), None),
                }
                rows.append(row)
                if not master_url or not master:
                    unresolved.append(row)
    confirmed = [row for row in rows if row["classification"] == "confirmed"]
    ambiguous = [row for row in rows if row["classification"] == "ambiguous"]
    identities = {}
    for row in confirmed:
        key = row["master_url"] or f"UNRESOLVED:{row['master_name'] or row['item_text']}"
        group = identities.setdefault(key, {
            "master_url": row["master_url"], "master_name": row["master_name"],
            "master_list": row["master_list"], "scenes": [],
        })
        group["scenes"].append({
            "scene_id": row["scene_id"], "item_text": row["item_text"],
            "scene_url": row["scene_url"],
        })
    return {
        "status": "read-only", "writes": 0,
        "board": {"name": board["name"], "url": board["url"], "shortLink": board["shortLink"]},
        "production_lists_scanned": sum(not _excluded_list(item["name"]) for item in lists),
        "production_scene_cards_scanned": len(production),
        "confirmed_count": len(confirmed), "ambiguous_count": len(ambiguous),
        "identity_count": len(identities), "identities": list(identities.values()),
        "confirmed": confirmed, "ambiguous": ambiguous,
        "unresolved_master_links": unresolved,
        "exclusions": ["policajný čln", "dialógové zmienky mimo REKVIZITY", "SET",
                       "original screener", "archív", "ToDo", "registry karty"],
    }


def register_routes(app, api):
    @app.route("/api/cierny-kamen-police-cars-audit", methods=["POST"])
    def cierny_kamen_police_cars_audit():
        if ENDPOINT_DISABLED:
            return jsonify({"status": "disabled"}), 410
        if request.headers.get("X-CK-Police-Cars-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        if request.args.get("mode", "dry-run").casefold() not in {"dry-run", "audit"}:
            return jsonify({"error": "read-only endpoint", "writes": 0}), 409
        try:
            return jsonify(build_audit(api)), 200
        except Exception as exc:
            app.logger.exception("Čierny Kameň police car audit failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
