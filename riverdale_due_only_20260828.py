"""One-off due-date-only sync for the 28 Aug 2026 Riverdale schedule."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KEY = "riverdale-due-only-28aug-91c7e430"
BOARD_REF = "CzuD55PR"
SCHEDULE_PATH = Path(__file__).with_name("riverdale_schedule_due_only_2026-08-28.json")


def due_utc(date_text):
    local = datetime.fromisoformat(date_text + "T12:00:00").replace(
        tzinfo=ZoneInfo("Europe/Bratislava")
    )
    return local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def date_only(value):
    return (value or "")[:10]


def todo_due_plan(state):
    todo_lists = [item for item in state["lists"] if item["name"].strip().casefold() == "todo"]
    if len(todo_lists) != 1:
        return [], [{"reason": "todo-list-count", "count": len(todo_lists)}]
    scene_dates = {}
    for item in state["matches"]:
        scene_dates[item["card"]["shortUrl"]] = item["row"]["shooting_date"]
    plans = []
    conflicts = []
    for card in state["cards"]:
        if card.get("idList") != todo_lists[0]["id"]:
            continue
        linked = sorted({date for url, date in scene_dates.items() if url in (card.get("desc") or "")})
        if not linked:
            # Existing task titles conventionally end in the earliest scene ID.
            for episode, scene in re.findall(r"\b(\d{1,2})\s*/\s*(\d+[A-Z]*)\b", card.get("name", ""), re.I):
                normalized = f"{int(episode):02d}/{int(re.match(r'\d+', scene).group())}{scene[len(re.match(r'\d+', scene).group()):].upper()}"
                matches = [x for x in state["matches"] if x["row"]["scene_id"] == normalized]
                linked.extend(x["row"]["shooting_date"] for x in matches)
        linked = sorted(set(linked))
        if not linked:
            continue
        desired = linked[0]
        plans.append({
            "card": card, "desired_date": desired,
            "current_date": date_only(card.get("due")),
            "linked_dates": linked,
        })
    return plans, conflicts


def build_report(api):
    document = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    rows = document["rows"]
    if len(rows) != 163 or len({row["scene_id"] for row in rows}) != 163:
        raise ValueError("schedule validation failed")
    trello = api["Dok4ScheduleTrello"](api["API_KEY"], api["TOKEN"])
    state = api["build_dok4_schedule_state"](
        trello, rows, source_date="2026-08-28", as_of="2026-08-28",
        board_ref=BOARD_REF, ignore_scene_suffix=True,
    )
    scene_updates = [{
        "scene_id": item["row"]["scene_id"],
        "matched_id": item["matched_id"],
        "fallback": item["fallback"],
        "current_date": date_only(item["card"].get("due")),
        "desired_date": item["row"]["shooting_date"],
        "url": item["card"]["shortUrl"],
        "card": item["card"],
    } for item in state["matches"] if date_only(item["card"].get("due")) != item["row"]["shooting_date"]]
    todo_plans, todo_conflicts = todo_due_plan(state)
    todo_updates = [item for item in todo_plans if item["current_date"] != item["desired_date"]]
    blockers = {
        "wrong_board": state["board"].get("shortLink") != BOARD_REF,
        "duplicates": len(state["duplicates"]),
        "fallback_collisions": len(state["reused_card_conflicts"]),
        "todo_conflicts": len(todo_conflicts),
    }
    return trello, state, scene_updates, todo_updates, blockers


def public_report(state, scene_updates, todo_updates, blockers):
    return {
        "status": "dry-run", "writes": 0,
        "board": state["board"]["name"], "board_url": state["board"]["url"],
        "schedule_rows": 163, "schedule_unique_scene_ids": 163,
        "shooting_dates": sorted({item["row"]["shooting_date"] for item in state["matches"]}),
        "matched": len(state["matches"]), "missing_count": len(state["missing"]),
        "missing": state["missing"], "duplicates_count": len(state["duplicates"]),
        "duplicates": state["duplicates"], "fallbacks_count": len(state["fallbacks"]),
        "fallbacks": state["fallbacks"],
        "fallback_collisions_count": len(state["reused_card_conflicts"]),
        "scene_due_updates": len(scene_updates),
        "scene_due_sample": [{k: v for k, v in item.items() if k != "card"} for item in scene_updates[:100]],
        "todo_due_updates": len(todo_updates),
        "todo_due_sample": [{"name": item["card"]["name"], "url": item["card"]["shortUrl"],
                             "current_date": item["current_date"], "desired_date": item["desired_date"],
                             "linked_dates": item["linked_dates"]} for item in todo_updates[:100]],
        "blockers": blockers,
        "protected_fields": ["name", "desc", "idList", "dueComplete", "labels", "checklists", "attachments", "comments"],
        "allowed_write_fields": ["due"],
    }


def microsoft_due_report(api):
    lists = api["trello_get"](f"/boards/{BOARD_REF}/lists", {
        "fields": "id,name,closed", "filter": "open",
    })
    todo_lists = [item for item in lists if item.get("name", "").strip().casefold() == "todo"]
    if len(todo_lists) != 1:
        return None, [], [], [{"reason": "todo-list-count", "count": len(todo_lists)}]
    cards = api["trello_get"](f"/lists/{todo_lists[0]['id']}/cards", {
        "fields": "id,name,desc,due,shortUrl,closed,pos", "filter": "open", "limit": 1000,
    })
    token = api["get_microsoft_access_token"]()
    tasks = api["graph_get_all"](
        f"/me/todo/lists/{api['TODO_LIST_ID']}/tasks", token
    )
    by_title = {}
    for task in tasks:
        by_title.setdefault(task.get("title", "").strip().casefold(), []).append(task)
    plans = []
    missing = []
    conflicts = []
    for card in cards:
        url_matches = [task for task in tasks
                       if card["shortUrl"] in (task.get("body") or {}).get("content", "")]
        title_matches = by_title.get(card["name"].strip().casefold(), [])
        matches = url_matches or title_matches
        if not matches:
            missing.append({"name": card["name"], "url": card["shortUrl"]})
            continue
        if len(matches) > 1:
            conflicts.append({"name": card["name"], "url": card["shortUrl"],
                              "matches": len(matches)})
            continue
        task = matches[0]
        current_due = ((task.get("dueDateTime") or {}).get("dateTime") or "")[:10]
        desired_due = date_only(card.get("due"))
        plans.append({"card": card, "task": task, "current_due": current_due,
                      "desired_due": desired_due})
    return token, plans, missing, conflicts


def register_routes(app, api):
    from flask import jsonify, request

    @app.route("/api/riverdale-due-only-20260828", methods=["POST"])
    def riverdale_due_only_20260828_endpoint():
        if request.headers.get("X-Riverdale-Due-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run")
        if mode not in {"dry-run", "apply-scenes", "apply-todo", "ms-dry-run", "ms-apply"}:
            return jsonify({"error": "unsupported mode"}), 400
        if mode in {"ms-dry-run", "ms-apply"}:
            token, plans, missing, conflicts = microsoft_due_report(api)
            updates = [item for item in plans if item["current_due"] != item["desired_due"]]
            report = {
                "status": "dry-run", "writes": 0, "matched": len(plans),
                "to_create": 0, "missing_existing_tasks": len(missing),
                "to_update": len(updates), "duplicate_exact_titles": len(conflicts),
                "sample": [{"name": item["card"]["name"],
                            "current_due": item["current_due"] or None,
                            "desired_due": item["desired_due"] or None}
                           for item in updates[:100]],
                "allowed_write_fields": ["dueDateTime"],
            }
            if conflicts:
                return jsonify({**report, "conflicts": conflicts}), 409
            if mode == "ms-dry-run":
                return jsonify(report)
            limit = min(25, max(1, int(request.args.get("limit", "20"))))
            selected = updates[:limit]
            updated = []
            for item in selected:
                payload = api["todo_due_payload"](item["card"].get("due")) if item["desired_due"] else None
                result = api["graph_patch"](
                    f"/me/todo/lists/{api['TODO_LIST_ID']}/tasks/{item['task']['id']}",
                    token, {"dueDateTime": payload},
                )
                updated.append({"title": result.get("title"), "due": item["desired_due"] or None})
            return jsonify({"status": "applied", "selected": len(selected), "updated": updated,
                            "remaining": max(0, len(updates) - len(selected)),
                            "missing_existing_tasks": len(missing), "created": 0})
        trello, state, scene_updates, todo_updates, blockers = build_report(api)
        report = public_report(state, scene_updates, todo_updates, blockers)
        if any(blockers.values()):
            return jsonify(report), 409
        if mode == "dry-run":
            return jsonify(report)
        targets = scene_updates if mode == "apply-scenes" else todo_updates
        start = max(0, int(request.args.get("start", "0")))
        limit = min(30, max(1, int(request.args.get("limit", "20"))))
        selected = targets[start:start + limit]
        updated = []
        for item in selected:
            card = item["card"]
            desired = item.get("desired_date")
            result = trello.put(f"/cards/{card['id']}", {"due": due_utc(desired)})
            updated.append({"name": result["name"], "url": result["shortUrl"], "due": result.get("due")})
        return jsonify({"status": "applied", "mode": mode, "selected": len(selected),
                        "updated": updated, "remaining": max(0, len(targets) - start - len(selected))})
