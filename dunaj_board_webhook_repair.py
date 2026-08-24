from __future__ import annotations

from flask import jsonify, request


KEY = "dunaj-board-webhook-24aug-69a4c8d2"
ENDPOINT_DISABLED = False
CALLBACK_URL = "https://trello-kupit-webhook.onrender.com/trello-webhook"
BOARDS = {"dunaj": "qCPeWA3e", "riverdale": "CzuD55PR"}


def classify_webhooks(webhooks, boards, list_owners):
    rows = []
    for hook in webhooks:
        model_id = hook.get("idModel")
        board_name = next((name for name, board in boards.items() if board.get("id") == model_id), None)
        model_type = "board" if board_name else "list" if model_id in list_owners else "other"
        if not board_name and model_type == "list":
            owner_id = list_owners[model_id]
            board_name = next((name for name, board in boards.items() if board.get("id") == owner_id), None)
        rows.append({
            "id": hook.get("id"), "active": hook.get("active"),
            "callbackURL": hook.get("callbackURL"), "idModel": model_id,
            "model_type": model_type, "project": board_name,
            "is_production_callback": (hook.get("callbackURL") or "").rstrip("/") == CALLBACK_URL,
        })
    return rows


def build_audit(api):
    boards = {
        name: api["trello_get"](f"/boards/{ref}", {"fields": "id,name,url,shortLink"})
        for name, ref in BOARDS.items()
    }
    webhooks = api["trello_get"](f"/tokens/{api['TOKEN']}/webhooks", {})
    list_owners = {}
    for hook in webhooks:
        model_id = hook.get("idModel")
        if model_id in {board["id"] for board in boards.values()}:
            continue
        try:
            list_info = api["trello_get"](f"/lists/{model_id}", {"fields": "id,idBoard,name,closed"})
        except Exception:
            continue
        list_owners[model_id] = list_info.get("idBoard")
    rows = classify_webhooks(webhooks, boards, list_owners)
    by_project = {
        name: [row for row in rows if row["project"] == name]
        for name in BOARDS
    }
    dunaj_board_hooks = [row for row in by_project["dunaj"] if row["model_type"] == "board"
                         and row["is_production_callback"] and row["active"]]
    riverdale_board_hooks = [row for row in by_project["riverdale"] if row["model_type"] == "board"
                             and row["is_production_callback"] and row["active"]]
    dunaj_list_hooks = [row for row in by_project["dunaj"] if row["model_type"] == "list"
                        and row["is_production_callback"]]
    blockers = []
    if len(riverdale_board_hooks) != 1:
        blockers.append(f"Riverdale production board webhook count is {len(riverdale_board_hooks)}")
    return {
        "status": "read-only-diagnostic", "writes": 0,
        "boards": {name: {key: value for key, value in board.items() if key != "id"}
                   for name, board in boards.items()},
        "subscriptions": by_project,
        "diagnosis": {
            "dunaj_board_webhooks": len(dunaj_board_hooks),
            "dunaj_list_webhooks": len(dunaj_list_hooks),
            "riverdale_board_webhooks": len(riverdale_board_hooks),
            "dunaj_delivery_scope_correct": len(dunaj_board_hooks) == 1 and not dunaj_list_hooks,
        },
        "planned": {
            "create_dunaj_board_webhook": int(not dunaj_board_hooks),
            "remove_dunaj_list_webhooks": len(dunaj_list_hooks),
            "trello_todo_writes": 0, "microsoft_todo_writes": 0,
        },
        "blockers": blockers,
        "_boards": boards, "_rows": rows,
    }


def public(audit):
    return {key: value for key, value in audit.items() if not key.startswith("_")}


def register_routes(app, api):
    @app.route("/api/repair-dunaj-board-webhook", methods=["POST"])
    def repair_dunaj_board_webhook():
        if ENDPOINT_DISABLED:
            return jsonify({"status": "disabled"}), 410
        if request.headers.get("X-Dunaj-Webhook-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        if mode not in {"dry-run", "audit"}:
            return jsonify({"error": "apply is disabled until diagnostic is reviewed", "writes": 0}), 409
        try:
            audit = build_audit(api)
            return jsonify(public(audit)), 200 if not audit["blockers"] else 409
        except Exception as exc:
            app.logger.exception("Dunaj board webhook diagnostic failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
