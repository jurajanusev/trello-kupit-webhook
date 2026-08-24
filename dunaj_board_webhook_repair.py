from __future__ import annotations

import threading
import time

from flask import jsonify, request


KEY = "dunaj-board-webhook-24aug-69a4c8d2"
ENDPOINT_DISABLED = True
CALLBACK_URL = "https://trello-kupit-webhook.onrender.com/trello-webhook"
BOARDS = {"dunaj": "qCPeWA3e", "riverdale": "CzuD55PR"}
BACKGROUND = {"status": "idle", "result": None, "http_status": None}


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


def apply_subscription(api):
    before = build_audit(api)
    dunaj_board = before["_boards"]["dunaj"]
    board_hooks = [row for row in before["_rows"] if row["project"] == "dunaj"
                   and row["model_type"] == "board" and row["is_production_callback"]
                   and row["active"]]
    writes = 0
    created = None
    if not board_hooks:
        response = api["trello_request"]("POST", f"{api['BASE']}/webhooks/", params={
            "description": "Dunaj board-wide [z] ToDo synchronization",
            "callbackURL": CALLBACK_URL,
            "idModel": dunaj_board["id"],
            "key": api["API_KEY"], "token": api["TOKEN"],
        })
        if not response.ok:
            return {"status": "blocked", "writes": 0,
                    "reason": "Trello rejected board webhook registration",
                    "trello_status": response.status_code,
                    "trello_error": response.text[:1000]}, 409
        created = response.json()
        writes += 1
    verification = build_audit(api)
    verified_board_hooks = [row for row in verification["_rows"] if row["project"] == "dunaj"
                            and row["model_type"] == "board" and row["is_production_callback"]
                            and row["active"]]
    if len(verified_board_hooks) != 1:
        return {"status": "blocked", "writes": writes,
                "reason": "Dunaj board webhook did not verify after create",
                "audit": public(verification)}, 409
    removed = []
    for row in verification["_rows"]:
        if row["project"] != "dunaj" or row["model_type"] != "list" or not row["is_production_callback"]:
            continue
        api["trello_delete"](f"/webhooks/{row['id']}")
        removed.append(row["id"])
        writes += 1
    after = build_audit(api)
    if not after["diagnosis"]["dunaj_delivery_scope_correct"]:
        return {"status": "audit-failed", "writes": writes, "audit": public(after)}, 409
    return {
        "status": "applied", "writes": writes,
        "created": {"id": created.get("id"), "idModel": created.get("idModel")} if created else None,
        "removed_list_webhooks": removed, "audit": public(after),
    }, 200


def register_routes(app, api):
    def background_apply():
        time.sleep(1.0)
        try:
            result, status = apply_subscription(api)
        except Exception as exc:
            app.logger.exception("background Dunaj webhook subscription failed")
            result, status = {"status": "failed", "writes": 0,
                              "error": f"{type(exc).__name__}: {exc}"}, 502
        BACKGROUND.update({"status": "complete", "result": result, "http_status": status})

    @app.route("/api/repair-dunaj-board-webhook", methods=["POST"])
    def repair_dunaj_board_webhook():
        if ENDPOINT_DISABLED:
            return jsonify({"status": "disabled"}), 410
        if request.headers.get("X-Dunaj-Webhook-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").casefold()
        if mode not in {"dry-run", "audit", "apply-subscription", "queue-subscription", "poll"}:
            return jsonify({"error": "unsupported mode", "writes": 0}), 409
        try:
            if mode == "poll":
                return jsonify(BACKGROUND), 200
            if mode == "queue-subscription":
                if BACKGROUND["status"] == "running":
                    return jsonify({"status": "already-running", "writes": 0}), 202
                BACKGROUND.update({"status": "running", "result": None, "http_status": None})
                threading.Thread(target=background_apply, daemon=True).start()
                return jsonify({"status": "queued", "writes": 0}), 202
            if mode == "apply-subscription":
                result, status = apply_subscription(api)
                return jsonify(result), status
            audit = build_audit(api)
            return jsonify(public(audit)), 200 if not audit["blockers"] else 409
        except Exception as exc:
            app.logger.exception("Dunaj board webhook diagnostic failed")
            return jsonify({"status": "failed", "writes": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 502
