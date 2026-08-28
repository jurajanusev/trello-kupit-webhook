"""Read-only safety audit for authoritative Čierny Kameň episodes 11–13."""
from __future__ import annotations

import json
from pathlib import Path

from flask import jsonify, request

KEY = "cierny-kamen-ep11-13-28aug-64d3f5a1"
BOARD_REF = "CzuD55PR"
PAYLOAD_PATH = Path(__file__).with_name("cierny_kamen_ep11_13_scenes.json")
EXCLUDED = ("original screener", "register", "rekvizit", "nadvazne", "todo", "auta")


def scene_info(api, name):
    return api["cierny_kamen_scene_name_info"](name or "")


def is_scene_list(name):
    key = (name or "").casefold()
    return not any(item in key for item in EXCLUDED)


def audit(api):
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    board = api["trello_get"](f"/boards/{BOARD_REF}", {"fields": "id,name,url"})
    lists = api["trello_get"](f"/boards/{board['id']}/lists", {"fields": "id,name,closed", "filter": "all"})
    found = {}
    archived = {}
    for listing in lists:
        cards = api["trello_get"](f"/lists/{listing['id']}/cards", {"fields": "id,name,shortUrl,closed,idList", "filter": "all", "limit": 1000})
        for card in cards:
            info = scene_info(api, card.get("name"))
            if not info or info.get("test"):
                continue
            target = archived if listing.get("closed") or card.get("closed") else found
            target.setdefault(info["scene_id"], []).append({"name": card["name"], "url": card.get("shortUrl"), "list": listing["name"]})
    ids = [scene["scene_id"] for scene in payload["scenes"]]
    duplicates = {key: value for key, value in found.items() if len(value) > 1 and key in ids}
    existing = {key: value for key, value in found.items() if key in ids}
    missing = [key for key in ids if key not in found]
    return {"status": "read-only-dry-run", "writes": 0, "board": board,
            "source_scenes": len(ids), "unique_source_ids": len(set(ids)),
            "existing": len(existing), "create": len(missing), "missing_ids": missing,
            "duplicates": duplicates, "archived_matches": {key: archived[key] for key in ids if key in archived},
            "excluded_lists": EXCLUDED, "source_stats": payload["stats"]}


def register_routes(app, api):
    @app.route("/api/cierny-kamen-ep11-13", methods=["POST"])
    def endpoint():
        if request.headers.get("X-CK-Ep11-13-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        if request.args.get("mode", "dry-run").casefold() not in {"dry-run", "audit"}:
            return jsonify({"error": "read-only dry-run only", "writes": 0}), 409
        return jsonify(audit(api))
