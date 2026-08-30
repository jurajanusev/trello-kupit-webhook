processed_actions = set()

from flask import Flask, request, jsonify
from flask import send_from_directory
from pathlib import Path
import re
import requests
from board_routing import resolve_target_list_id
import os
import json
import unicodedata
import time
from update_dok4_plan_local import (
    Trello as Dok4ScheduleTrello,
    apply as apply_dok4_schedule,
    build_state as build_dok4_schedule_state,
    summary as summarize_dok4_schedule,
)

app = Flask(__name__)

DOK4_CURRENT_SCHEDULE_KEY = "dok4-schedule-24aug-61b7d4e9"
DOK4_CURRENT_SCHEDULE_FILE = "dok4_schedule_2026-08-24.json"
DOK4_CURRENT_SCHEDULE_AS_OF = "2026-08-24"
DOK4_CURRENT_SCHEDULE_ROWS = 482

RIVERDALE_CURRENT_SCHEDULE_KEY = "riverdale-schedule-30aug-4d82b7f1"
RIVERDALE_CURRENT_SCHEDULE_FILE = "riverdale_schedule_2026-08-30.json"
RIVERDALE_CURRENT_SCHEDULE_AS_OF = "2026-08-30"
RIVERDALE_CURRENT_SCHEDULE_ROWS = 140
RIVERDALE_BOARD_REF = "CzuD55PR"
RIVERDALE_START_MARKER = "<!-- RIVERDALE-SCHEDULE-METADATA:START -->"
RIVERDALE_END_MARKER = "<!-- RIVERDALE-SCHEDULE-METADATA:END -->"
RIVERDALE_SOURCE_LABEL = "predbežné dispo Riverdale / Čierny Kameň"

DUNAJ_CURRENT_SCHEDULE_KEY = "dunaj-schedule-14aug-5e8c219d"
DUNAJ_CURRENT_SCHEDULE_FILE = "dunaj_schedule_2026-08-14.json"
DUNAJ_CURRENT_SCHEDULE_AS_OF = "2026-08-14"
DUNAJ_CURRENT_SOURCE_LABEL = "predbežná dispo DUNAJ 16 z 14. 8. 2026"
DUNAJ_CURRENT_SOURCE_ROWS = 1148


def canonicalize_dunaj_schedule_rows(source_rows):
    """Apply stable user-approved scene aliases and merged-card rules."""
    schedule_rows = []
    merged_24 = None
    for source_row in source_rows:
        row = dict(source_row)
        if row["scene_id"] == "23/34F":
            row["scene_id"] = "23/34FLASH"
            row["scene"] = "34FLASH"
        if row["scene_id"] == "24/8A":
            merged_24 = row
            continue
        if row["scene_id"] == "24/8B":
            if merged_24 is None:
                raise ValueError("24/8B encountered before 24/8A")
            merged_24["scene_id"] = "24/8"
            merged_24["scene"] = "8"
            merged_24["order_display"] = "8-9"
            merged_24["location"] = "KABARET - ZÁZEMIE / KABARET"
            merged_24["characters"] = "René, Lena, Gita"
            schedule_rows.append(merged_24)
            merged_24 = None
            continue
        schedule_rows.append(row)
    if merged_24 is not None:
        raise ValueError("merged scene normalization failed")
    return schedule_rows


def dunaj_schedule_bucket(shooting_date, as_of, active_dates):
    """Classify a scene as already shot, currently active, or future."""
    if shooting_date < as_of:
        return "shot"
    if shooting_date in set(active_dates):
        return "active"
    return "series"


@app.errorhandler(requests.HTTPError)
def handle_requests_http_error(exc):
    response = exc.response
    return jsonify({
        "error": "upstream request failed",
        "status_code": response.status_code if response is not None else None,
        "details": response.text[:3000] if response is not None else str(exc),
        "url": response.url.split("?", 1)[0] if response is not None else None,
    }), 502

API_KEY = os.environ["TRELLO_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]
MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET")
MICROSOFT_REFRESH_TOKEN = os.environ.get("MICROSOFT_REFRESH_TOKEN")
MICROSOFT_AUTHORITY = os.environ.get("MICROSOFT_AUTHORITY", "consumers")
TODO_LIST_ID = os.environ.get("TODO_LIST_ID")
TODO_TASK_TITLE_TEMPLATE = os.environ.get("TODO_TASK_TITLE_TEMPLATE", "{item} - {card}")

DEFAULT_BOARD_CONFIG = {
    "69cd95eed6bf6120fee7dd22": {
        "target_list_id": "69e53446a823be00f2e5e837"
    },

    # DOK4: VSETKY EPIZODY -> ToDo
    "69f74077554ff079f9472308": {
        "target_list_id": "6a057f30a60d4ab5aee502b6"
    },

    # Riverdale: VSETKY EPIZODY -> ToDo
    "6a3d776cbd0488b47076d8e6": {
        "target_list_id": "6a4776f530468dee7ea5fbfc"
    },

    # Riverdale: SCENARE -> ToDo
    "6a4524898cb771a99433699b": {
        "target_list_id": "6a4776f530468dee7ea5fbfc"
    }
}


def load_board_config():
    """
    SOURCE_TARGET_LISTS format:
    source_list_id:target_list_id,source_list_id:target_list_id
    """
    raw = os.environ.get("SOURCE_TARGET_LISTS", "").strip()
    if not raw:
        return DEFAULT_BOARD_CONFIG

    # Environment mappings override defaults, but do not accidentally remove
    # another board that was added to the built-in configuration later.
    config = {
        source_list_id: values.copy()
        for source_list_id, values in DEFAULT_BOARD_CONFIG.items()
    }
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue

        if ":" not in pair:
            raise RuntimeError(f"Invalid SOURCE_TARGET_LISTS pair: {pair}")

        source_list_id, target_list_id = pair.split(":", 1)
        source_list_id = source_list_id.strip()
        target_list_id = target_list_id.strip()

        if source_list_id and target_list_id:
            config[source_list_id] = {"target_list_id": target_list_id}

    return config


BOARD_CONFIG = load_board_config()

BOARD_TARGET_LISTS = {
    "qCPeWA3e": "69e53446a823be00f2e5e837",  # Dunaj
    "CzuD55PR": "6a4776f530468dee7ea5fbfc",  # Riverdale
    "lzNy4AtY": "6a057f30a60d4ab5aee502b6",  # DOK4
}

CHECKLIST_TAG = os.environ.get("CHECKLIST_TAG", "[Z]")

BASE = "https://api.trello.com/1"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def trello_request(method, url, **kwargs):
    response = None
    for attempt in range(6):
        response = requests.request(method, url, **kwargs)
        if response.status_code != 429:
            return response
        retry_after = response.headers.get("Retry-After", "10")
        try:
            wait_seconds = max(1, min(30, int(float(retry_after))))
        except ValueError:
            wait_seconds = 10
        wait_seconds = min(30, wait_seconds + attempt * 3)
        print(f"TRELLO RATE LIMIT: attempt {attempt + 1}, retrying after {wait_seconds}s")
        time.sleep(wait_seconds)
    return response


def trello_get(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = trello_request("GET", f"{BASE}{path}", params=params, timeout=20)

    if not r.ok:
        print("TRELLO GET ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def target_list_id_for_card(card_info):
    """Resolve a same-board ToDo list for supported production boards."""

    def board_short_link(board_id):
        board_info = trello_get(
            f"/boards/{board_id}", {"fields": "shortLink"}
        )
        return board_info.get("shortLink")

    def list_board_id(list_id):
        list_info = trello_get(
            f"/lists/{list_id}", {"fields": "idBoard"}
        )
        return list_info.get("idBoard")

    return resolve_target_list_id(
        card_info,
        BOARD_CONFIG,
        BOARD_TARGET_LISTS,
        board_short_link,
        list_board_id,
    )


def trello_post(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = trello_request("POST", f"{BASE}{path}", params=params, timeout=20)

    if not r.ok:
        print("TRELLO POST ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_post_body(path, data=None):
    data = data or {}
    data.update({"key": API_KEY, "token": TOKEN})
    r = trello_request("POST", f"{BASE}{path}", data=data, timeout=20)

    if not r.ok:
        print("TRELLO POST BODY ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_put_body(path, data=None):
    data = data or {}
    data.update({"key": API_KEY, "token": TOKEN})
    r = trello_request("PUT", f"{BASE}{path}", data=data, timeout=20)

    if not r.ok:
        print("TRELLO PUT BODY ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_delete(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = trello_request("DELETE", f"{BASE}{path}", params=params, timeout=20)
    if not r.ok:
        print("TRELLO DELETE ERROR:", r.status_code, r.text)
    r.raise_for_status()
    return r.json() if r.text else {}


def normalize_scene_id(episode, scene):
    """Normalize 8/05, 08 / 5 and 08/005A to the same stable ID 08/5 or 08/5A."""
    match = re.fullmatch(r"0*([0-9]+)([A-Z]*)", str(scene).strip(), re.I)
    if not match:
        return None
    return f"{int(episode):02d}/{int(match.group(1))}{match.group(2).upper()}"


def microsoft_enabled():
    return all([
        MICROSOFT_CLIENT_ID,
        MICROSOFT_CLIENT_SECRET,
        MICROSOFT_REFRESH_TOKEN,
        TODO_LIST_ID
    ])


def get_microsoft_access_token():
    if not microsoft_enabled():
        raise RuntimeError("Microsoft To Do env variables are not configured")

    r = requests.post(
        f"https://login.microsoftonline.com/{MICROSOFT_AUTHORITY}/oauth2/v2.0/token",
        data={
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "refresh_token": MICROSOFT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
            "scope": "offline_access User.Read Tasks.ReadWrite",
        },
        timeout=20
    )

    if not r.ok:
        print("MICROSOFT TOKEN ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()["access_token"]


def graph_get(path, access_token, params=None):
    r = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params or {},
        timeout=20
    )

    if not r.ok:
        print("GRAPH GET ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def graph_post(path, access_token, payload):
    r = requests.post(
        f"{GRAPH_BASE}{path}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20
    )

    if not r.ok:
        print("GRAPH POST ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def graph_patch(path, access_token, payload):
    r = requests.patch(
        f"{GRAPH_BASE}{path}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20
    )
    if not r.ok:
        print("GRAPH PATCH ERROR:", r.status_code, r.text)
    r.raise_for_status()
    return r.json()


def graph_get_all(path, access_token, params=None):
    values = []
    url = f"{GRAPH_BASE}{path}"
    first = True
    while url:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=(params or {}) if first else None,
            timeout=20
        )
        if not r.ok:
            print("GRAPH GET ALL ERROR:", r.status_code, r.text)
        r.raise_for_status()
        data = r.json()
        values.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        first = False
    return values


def todo_due_payload(trello_due):
    if not trello_due:
        return None
    return {
        "dateTime": f"{trello_due[:10]}T12:00:00.0000000",
        "timeZone": "Central Europe Standard Time",
    }


def todo_task_exists(access_token, title):
    data = graph_get(
        f"/me/todo/lists/{TODO_LIST_ID}/tasks",
        access_token,
        params={"$top": 100}
    )

    for task in data.get("value", []):
        if task.get("title", "").strip().lower() == title.strip().lower():
            return True

    return False


def create_todo_task(item_name, original_item_name, card_info, matching_cards):
    if not microsoft_enabled():
        print("TODO SKIP: Microsoft To Do is not configured")
        return None

    title = TODO_TASK_TITLE_TEMPLATE.format(
        item=item_name,
        card=card_info["name"],
        original_item=original_item_name
    )

    found_text = ", ".join(matching_cards) if matching_cards else "nenajdene"
    body = (
        "Vytvorene automaticky z Trello checklist polozky.\n\n"
        f"Povodna karta: {card_info['name']}\n"
        f"Odkaz na povodnu kartu: {card_info['shortUrl']}\n\n"
        f"Povodna checklist polozka: {original_item_name}\n\n"
        f"Najdene v kartach:\n{found_text}"
    )

    access_token = get_microsoft_access_token()

    if todo_task_exists(access_token, title):
        print("TODO SKIP existing task:", title)
        return None

    task = graph_post(
        f"/me/todo/lists/{TODO_LIST_ID}/tasks",
        access_token,
        {
            "title": title,
            "body": {
                "content": body,
                "contentType": "text"
            }
        }
    )
    print("TODO TASK CREATED:", task.get("id"), task.get("title"))
    return task


@app.route("/api/sync-<project>-microsoft-todo", methods=["POST"])
def sync_project_microsoft_todo(project):
    if request.headers.get("X-Microsoft-Sync-Key") != "dunaj-ms-todo-sync-19jul-84c2f1a7":
        return jsonify({"error": "forbidden"}), 403
    if not microsoft_enabled():
        return jsonify({"error": "Microsoft To Do is not configured"}), 503

    projects = {
        "dunaj": {"board": "qCPeWA3e", "name": "Dunaj"},
        "riverdale": {"board": "CzuD55PR", "name": "Riverdale"},
        "dok4": {"board": "lzNy4AtY", "name": "DOK4"},
    }
    config = projects.get(project.casefold())
    if not config:
        return jsonify({"error": "unknown project"}), 404

    lists = trello_get(f"/boards/{config['board']}/lists", {
        "fields": "id,name,closed", "filter": "open"
    })
    todo_list = next((item for item in lists if item.get("name", "").strip().casefold() == "todo"), None)
    if not todo_list:
        return jsonify({"error": f"{config['name']} ToDo list not found"}), 404
    cards = trello_get(f"/lists/{todo_list['id']}/cards", {
        "fields": "id,name,desc,due,shortUrl,closed,pos", "filter": "open", "limit": 1000
    })
    cards.sort(key=lambda card: (card.get("name", "").casefold(), card.get("id", "")))

    try:
        access_token = get_microsoft_access_token()
        tasks = graph_get_all(
            f"/me/todo/lists/{TODO_LIST_ID}/tasks", access_token
        )
    except requests.HTTPError as exc:
        response = exc.response
        return jsonify({"error": "Microsoft Graph request failed",
                        "status_code": response.status_code if response is not None else None,
                        "details": (response.text[:2000] if response is not None else str(exc))}), 502
    tasks_by_title = {}
    for task in tasks:
        tasks_by_title.setdefault(task.get("title", "").strip().casefold(), []).append(task)

    plans = []
    for card in cards:
        title_matches = tasks_by_title.get(card["name"].strip().casefold(), [])
        url_matches = [task for task in tasks
                       if card["shortUrl"] in (task.get("body") or {}).get("content", "")]
        matches = url_matches or title_matches
        desired_due = todo_due_payload(card.get("due"))
        desired_date = card.get("due", "")[:10] if card.get("due") else ""
        desired_body = (
            "Synchronizované automaticky z Trello karty rekvizity.\n\n"
            f"Trello: {card['shortUrl']}\n\n{card.get('desc', '')}"
        )[:24000]
        desired_body = (
            f"SYNC PROJECT: {config['name']}\n"
            f"SYNC DUE DATE: {desired_date or 'NONE'}\n\n"
            + desired_body
        )[:24000]
        primary = matches[0] if matches else None
        changes = {}
        if primary:
            current_body = (primary.get("body") or {}).get("content", "")
            desired_due_marker = desired_date or "NONE"
            due_marker_present = bool(re.search(
                r"SYNC DUE DATE:\s*" + re.escape(desired_due_marker) + r"(?:\s|$)",
                current_body, flags=re.I,
            ))
            # Graph may normalize text bodies on write. The Trello URL is the
            # stable sync identity, so do not rewrite an already linked body.
            if card["shortUrl"] not in current_body or not due_marker_present:
                changes["body"] = {"content": desired_body, "contentType": "text"}
            if not due_marker_present:
                changes["dueDateTime"] = desired_due if desired_date else None
        plans.append({
            "card": card, "task": primary, "changes": changes,
            "duplicate_tasks": matches[1:], "desired_due": desired_due,
            "desired_body": desired_body,
        })

    summary = {
        "project": config["name"],
        "trello_cards": len(cards), "microsoft_tasks": len(tasks),
        "matched": sum(1 for plan in plans if plan["task"]),
        "to_create": sum(1 for plan in plans if not plan["task"]),
        "to_update": sum(1 for plan in plans if plan["task"] and plan["changes"]),
        "unchanged": sum(1 for plan in plans if plan["task"] and not plan["changes"]),
        "duplicate_exact_titles": sum(len(plan["duplicate_tasks"]) for plan in plans),
        "without_due": sum(1 for card in cards if not card.get("due")),
    }
    mode = request.args.get("mode", "dry-run")
    if mode == "dry-run":
        return jsonify({"status": "dry-run", **summary, "sample": [{
            "title": plan["card"]["name"], "trello_due": (plan["card"].get("due") or "")[:10] or None,
            "action": "create" if not plan["task"] else ("update" if plan["changes"] else "unchanged"),
            "fields": sorted(plan["changes"]), "duplicates": len(plan["duplicate_tasks"]),
        } for plan in plans[:30]]})
    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400

    actionable = [plan for plan in plans if not plan["task"] or plan["changes"]]
    start = max(0, int(request.args.get("start", "0")))
    limit = min(25, max(1, int(request.args.get("limit", "15"))))
    batch = actionable[start:start + limit]
    created = []; updated = []; errors = []
    for plan in batch:
        card = plan["card"]
        try:
            if plan["task"]:
                task = graph_patch(
                    f"/me/todo/lists/{TODO_LIST_ID}/tasks/{plan['task']['id']}",
                    access_token, plan["changes"]
                )
                updated.append({"title": task.get("title"), "due": (task.get("dueDateTime") or {}).get("dateTime")})
            else:
                payload = {
                    "title": card["name"],
                    "body": {"content": (
                        "Synchronizované automaticky z Trello karty rekvizity.\n\n"
                        f"Trello: {card['shortUrl']}\n\n{card.get('desc', '')}"
                    )[:24000], "contentType": "text"},
                }
                payload["body"] = {
                    "content": plan["desired_body"],
                    "contentType": "text",
                }
                if plan["desired_due"]:
                    payload["dueDateTime"] = plan["desired_due"]
                task = graph_post(f"/me/todo/lists/{TODO_LIST_ID}/tasks", access_token, payload)
                created.append({"title": task.get("title"), "due": (task.get("dueDateTime") or {}).get("dateTime")})
        except Exception as exc:
            errors.append({"title": card["name"], "error": str(exc)})
    return jsonify({"status": "applied", **summary, "actionable": len(actionable),
                    "processed": len(batch), "created": created, "updated": updated,
                    "errors": errors, "remaining": max(0, len(actionable) - start - len(batch))})


@app.route("/api/sync-<project>-continuity-registry", methods=["POST"])
def sync_project_continuity_registry(project):
    if request.headers.get("X-Continuity-Sync-Key") != "continuity-registry-19jul-51ea730c":
        return jsonify({"error": "forbidden"}), 403
    projects = {
        "dunaj": {"board": "qCPeWA3e", "name": "Dunaj"},
        "riverdale": {"board": "CzuD55PR", "name": "Riverdale"},
        "dok4": {"board": "lzNy4AtY", "name": "DOK4"},
    }
    config = projects.get(project.casefold())
    if not config:
        return jsonify({"error": "unknown project"}), 404

    board = trello_get(f"/boards/{config['board']}", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "open"
    })
    registry_list = next((item for item in lists
                          if item["name"].strip().casefold() == "register rekvizít".casefold()), None)
    ignored_list_ids = {item["id"] for item in lists
                        if item["name"].strip().casefold() in {"todo", "register rekvizít".casefold()}}

    scene_cards = []
    prop_groups = {}
    # Fetch all open board cards in one request. The earlier per-list scan
    # exceeded Trello's request limit on large productions such as DOK4.
    board_cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,due,shortUrl,closed,idList", "filter": "open", "limit": 1000,
        "checklists": "all", "checklist_fields": "name",
    })
    for card in board_cards:
        if card.get("idList") in ignored_list_ids:
            continue
        scene_id = scene_id_from_card_name(card.get("name"))
        if not scene_id:
            continue
        props = []
        for checklist in card.get("checklists", []):
            folded = unicodedata.normalize("NFKD", checklist.get("name", ""))
            folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).upper()
            if folded != "REKVIZITY":
                continue
            for item in checklist.get("checkItems", []):
                raw = item.get("name", "").strip()
                full_context = tagged_prop_text(raw)
                identity_source = re.split(r"\s+[–—-]\s+", full_context, maxsplit=1)[0].strip()
                key, display = canonical_prop(identity_source)
                if not key or key in {"test", "x"}:
                    continue
                occurrence = {"scene_id": scene_id, "card": card, "context": full_context}
                group = prop_groups.setdefault(key, {"display": display, "occurrences": []})
                group["occurrences"].append(occurrence)
                props.append({"key": key, "context": full_context})
        if props:
            scene_cards.append({"card": card, "scene_id": scene_id, "props": props})

    # Kept structurally for compatibility; all cards were handled above.
    for board_list in []:
        if board_list["id"] in ignored_list_ids:
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,due,shortUrl,closed,idList", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })
        for card in cards:
            scene_id = scene_id_from_card_name(card.get("name"))
            if not scene_id:
                continue
            props = []
            for checklist in card.get("checklists", []):
                folded = unicodedata.normalize("NFKD", checklist.get("name", ""))
                folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).upper()
                if folded != "REKVIZITY":
                    continue
                for item in checklist.get("checkItems", []):
                    raw = item.get("name", "").strip()
                    full_context = tagged_prop_text(raw)
                    identity_source = re.split(r"\s+[–—-]\s+", full_context, maxsplit=1)[0].strip()
                    key, display = canonical_prop(identity_source)
                    if not key or key in {"test", "x"}:
                        continue
                    occurrence = {"scene_id": scene_id, "card": card, "context": full_context}
                    group = prop_groups.setdefault(key, {"display": display, "occurrences": []})
                    group["occurrences"].append(occurrence)
                    props.append({"key": key, "context": full_context})
            if props:
                scene_cards.append({"card": card, "scene_id": scene_id, "props": props})

    registry_cards = trello_get(f"/lists/{registry_list['id']}/cards", {
        "fields": "id,name,desc,due,shortUrl,closed,pos", "filter": "open", "limit": 1000
    }) if registry_list else []
    registry_by_key = {}
    for card in registry_cards:
        match = re.search(r"\*\*IDENTITA:\*\*\s*`([^`]+)`", card.get("desc", ""), flags=re.I)
        key = match.group(1).strip() if match else canonical_prop(card.get("name", ""))[0]
        if key:
            registry_by_key.setdefault(key, []).append(card)

    plans = []
    for key, group in prop_groups.items():
        unique = {}
        for occurrence in group["occurrences"]:
            unique.setdefault(occurrence["card"]["id"], occurrence)
        occurrences = sorted(unique.values(), key=lambda item: (
            item["card"].get("due") or "9999-12-31", item["scene_id"]
        ))
        plans.append({"key": key, "display": group["display"], "occurrences": occurrences,
                      "existing": registry_by_key.get(key, [])})
    plans.sort(key=lambda item: item["display"].casefold())
    matched_registry_ids = {card["id"] for plan in plans for card in plan["existing"]}
    unmatched_registry = [card for card in registry_cards if card["id"] not in matched_registry_ids]

    mode = request.args.get("mode", "dry-run")
    summary = {
        "project": config["name"], "board": board["name"],
        "registry_list_exists": bool(registry_list), "scene_cards": len(scene_cards),
        "unique_props": len(plans), "registry_cards": len(registry_cards),
        "repeated_props": sum(1 for plan in plans if len(plan["occurrences"]) > 1),
        "registry_to_create": sum(1 for plan in plans if not plan["existing"]),
        "registry_to_update": sum(1 for plan in plans if plan["existing"]),
        "registry_duplicates": sum(max(0, len(plan["existing"]) - 1) for plan in plans),
        "unmatched_registry_cards": len(unmatched_registry),
        "scene_cards_to_update": len(scene_cards),
    }
    if mode == "dry-run":
        return jsonify({"status": "dry-run", **summary, "repeated_sample": [{
            "prop": plan["display"],
            "scenes": [occ["scene_id"] for occ in plan["occurrences"]],
        } for plan in plans if len(plan["occurrences"]) > 1][:40],
                        "unmatched_sample": [{"id": card["id"], "name": card["name"],
                                              "url": card["shortUrl"]}
                                             for card in unmatched_registry[:40]]})

    if not registry_list:
        registry_list = trello_post_body("/lists", {
            "name": "REGISTER REKVIZÍT", "idBoard": board["id"], "pos": "bottom"
        })
    start = max(0, int(request.args.get("start", "0")))
    limit = min(100, max(1, int(request.args.get("limit", "20"))))
    registry_marker_start = "<!-- PROP-REGISTRY:START -->"
    registry_marker_end = "<!-- PROP-REGISTRY:END -->"
    scene_marker_start = "<!-- PROP-CONTINUITY:START -->"
    scene_marker_end = "<!-- PROP-CONTINUITY:END -->"

    if mode == "archive-unmatched-auto":
        auto_cards = [card for card in unmatched_registry
                      if registry_marker_start in card.get("desc", "")
                      and registry_marker_end in card.get("desc", "")]
        batch = auto_cards[start:start + limit]
        archived = []; errors = []
        for card in batch:
            try:
                trello_put_body(f"/cards/{card['id']}", {"closed": "true"})
                archived.append(card["id"])
            except Exception as exc:
                errors.append({"card": card["name"], "error": str(exc)})
        return jsonify({"status": "unmatched-archived", **summary,
                        "eligible": len(auto_cards), "processed": len(batch),
                        "archived": archived, "errors": errors,
                        "remaining": max(0, len(auto_cards) - start - len(batch))})

    if mode == "apply-registry":
        apply_plans = ([plan for plan in plans if not plan["existing"]]
                       if request.args.get("only_missing") == "1" else plans)
        batch = apply_plans[start:start + limit]
        created = []; updated = []; archived = []; errors = []
        for plan in batch:
            lines = [registry_marker_start,
                     "Automatický register všetkých výskytov rekvizity.", "",
                     f"**REKVIZITA:** {plan['display']}", f"**IDENTITA:** `{plan['key']}`", "",
                     "**VÝSKYTY, ODKAZY A KONTEXT:**"]
            for occ in plan["occurrences"]:
                date = (occ["card"].get("due") or "")[:10] or "bez dátumu"
                lines.extend([f"- [{occ['scene_id']} — {occ['card']['name']}]({occ['card']['shortUrl']}) — {date}",
                              f"  - Akcia/kontext: {occ['context']}"])
            lines.extend(["", "**REŤAZ KONTINUITY:**",
                          " → ".join(occ["scene_id"] for occ in plan["occurrences"]), registry_marker_end])
            synced = "\n".join(lines)
            primary = plan["existing"][0] if plan["existing"] else None
            try:
                if primary:
                    old = primary.get("desc", "")
                    if registry_marker_start in old and registry_marker_end in old:
                        new = re.sub(re.escape(registry_marker_start) + r".*?" + re.escape(registry_marker_end),
                                     lambda _: synced, old, count=1, flags=re.S)
                    else:
                        new = synced + ("\n\n---\n\n**RUČNÉ POZNÁMKY:**\n\n" + old if old else "")
                    trello_put_body(f"/cards/{primary['id']}", {"desc": new})
                    updated.append(primary["id"])
                    for duplicate in plan["existing"][1:]:
                        trello_put_body(f"/cards/{duplicate['id']}", {"closed": "true"})
                        archived.append(duplicate["id"])
                else:
                    card = trello_post_body("/cards", {"idList": registry_list["id"],
                                            "name": plan["display"], "desc": synced, "pos": "bottom"})
                    created.append(card["id"])
            except Exception as exc:
                errors.append({"prop": plan["display"], "error": str(exc)})
        return jsonify({"status": "registry-applied", **summary, "processed": len(batch),
                        "created": created, "updated": updated, "archived": archived,
                        "errors": errors, "remaining": max(0, len(apply_plans) - start - len(batch))})

    if mode == "apply-scenes":
        refreshed = trello_get(f"/lists/{registry_list['id']}/cards", {
            "fields": "id,name,desc,shortUrl", "filter": "open", "limit": 1000
        })
        registry_lookup = {}
        for reg in refreshed:
            match = re.search(r"\*\*IDENTITA:\*\*\s*`([^`]+)`", reg.get("desc", ""), flags=re.I)
            if match:
                registry_lookup[match.group(1).strip()] = reg
        plan_lookup = {plan["key"]: plan for plan in plans}
        batch = scene_cards[start:start + limit]
        updated = []; errors = []
        for scene in batch:
            lines = [scene_marker_start, "### KONTINUITA REKVIZÍT — AUTOMATICKY", ""]
            seen = set()
            for prop in scene["props"]:
                if prop["key"] in seen:
                    continue
                seen.add(prop["key"])
                plan = plan_lookup[prop["key"]]
                reg = registry_lookup.get(prop["key"])
                others = [occ for occ in plan["occurrences"] if occ["card"]["id"] != scene["card"]["id"]]
                lines.append(f"**{plan['display']}**")
                lines.append(f"Akcia v tomto obraze: {prop['context']}")
                lines.append("Ďalšie výskyty: " + (", ".join(
                    f"[{occ['scene_id']}]({occ['card']['shortUrl']})" for occ in others) or "žiadne nájdené"))
                if reg:
                    lines.append(f"Register: [{reg['name']}]({reg['shortUrl']})")
                lines.append("")
            lines.append(scene_marker_end)
            synced = "\n".join(lines)
            old = scene["card"].get("desc", "")
            if scene_marker_start in old and scene_marker_end in old:
                new = re.sub(re.escape(scene_marker_start) + r".*?" + re.escape(scene_marker_end),
                             lambda _: synced, old, count=1, flags=re.S)
            else:
                new = old.rstrip() + ("\n\n" if old.strip() else "") + synced
            try:
                trello_put_body(f"/cards/{scene['card']['id']}", {"desc": new})
                updated.append(scene["card"]["id"])
            except Exception as exc:
                errors.append({"scene": scene["scene_id"], "error": str(exc)})
        return jsonify({"status": "scenes-applied", **summary, "processed": len(batch),
                        "updated": updated, "errors": errors,
                        "remaining": max(0, len(scene_cards) - start - len(batch))})
    return jsonify({"error": "invalid mode"}), 400


@app.route("/api/inspect-dok4-registry-list", methods=["GET"])
def inspect_dok4_registry_list():
    if request.headers.get("X-Continuity-Sync-Key") != "continuity-registry-19jul-51ea730c":
        return jsonify({"error": "forbidden"}), 403
    try:
        board = trello_get("/boards/lzNy4AtY", {"fields": "id,name"})
        lists = trello_get(f"/boards/{board['id']}/lists", {
            "fields": "id,name,closed", "filter": "open"
        })
        registry = next((item for item in lists
                         if item["name"].strip().casefold() == "register rekvizít".casefold()), None)
        if not registry:
            return jsonify({"error": "registry list not found"}), 404
        cards = trello_get(f"/lists/{registry['id']}/cards", {
            "fields": "id,name,desc,shortUrl,closed,pos", "filter": "open", "limit": 1000
        })
        by_identity = {}
        without_identity = []
        for card in cards:
            match = re.search(r"\*\*IDENTITA:\*\*\s*`([^`]+)`", card.get("desc", ""), flags=re.I)
            if match:
                by_identity.setdefault(match.group(1).strip(), []).append(card)
            else:
                without_identity.append(card)
        duplicates = [{"identity": key, "cards": len(value),
                       "names": [card["name"] for card in value]}
                      for key, value in by_identity.items() if len(value) > 1]
        return jsonify({"board": board["name"], "list": registry["name"],
                        "active_cards_returned": len(cards),
                        "unique_identities": len(by_identity),
                        "duplicate_identities": len(duplicates),
                        "duplicate_extra_cards": sum(item["cards"] - 1 for item in duplicates),
                        "without_identity": len(without_identity),
                        "duplicate_sample": duplicates[:30]})
    except requests.HTTPError as exc:
        response = exc.response
        return jsonify({"error": "Trello request failed",
                        "status_code": response.status_code if response is not None else None,
                        "details": response.text[:2000] if response is not None else str(exc)}), 502


@app.route("/api/inspect-scene-description-structure", methods=["GET"])
def inspect_scene_description_structure():
    if request.headers.get("X-Inspect-Key") != "scene-description-structure-22jul-3d861a9f":
        return jsonify({"error": "forbidden"}), 403
    boards = {"dok4": "lzNy4AtY", "riverdale": "CzuD55PR"}
    project = request.args.get("project", "dok4").casefold()
    board_ref = boards.get(project)
    if not board_ref:
        return jsonify({"error": "unknown project"}), 404
    limit = min(20, max(1, int(request.args.get("limit", "8"))))
    board = trello_get(f"/boards/{board_ref}", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "open"
    })
    samples = []
    for board_list in lists:
        folded_name = unicodedata.normalize("NFKD", board_list["name"])
        folded_name = "".join(ch for ch in folded_name if not unicodedata.combining(ch)).upper()
        if "NATOC" in folded_name or board_list["name"].strip().casefold() in {
            "todo", "register rekvizít".casefold()
        }:
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,shortUrl,idList,closed", "filter": "open", "limit": 1000
        })
        for card in cards:
            if not scene_id_from_card_name(card.get("name")) or not card.get("desc", "").strip():
                continue
            samples.append({"name": card["name"], "url": card["shortUrl"],
                            "list": board_list["name"], "description": card["desc"]})
            if len(samples) >= limit:
                return jsonify({"project": project, "board": board["name"], "samples": samples})
    return jsonify({"project": project, "board": board["name"], "samples": samples})


def riverdale_description_to_dok4_style(card_name, description):
    metadata_pattern = re.compile(
        r"\A(<!-- [A-Z0-9_-]*SCHEDULE[A-Z0-9_-]*:START -->.*?"
        r"<!-- [A-Z0-9_-]*SCHEDULE[A-Z0-9_-]*:END -->\s*)", re.S | re.I
    )
    metadata_match = metadata_pattern.match(description)
    metadata = metadata_match.group(1).strip() if metadata_match else ""
    remainder = description[metadata_match.end():].strip() if metadata_match else description.strip()

    continuity_start = "<!-- PROP-CONTINUITY:START -->"
    continuity_end = "<!-- PROP-CONTINUITY:END -->"
    continuity = ""
    suffix = ""
    if continuity_start in remainder and continuity_end in remainder:
        start = remainder.index(continuity_start)
        end = remainder.index(continuity_end, start) + len(continuity_end)
        continuity = remainder[start:end].strip()
        suffix = remainder[end:].strip()
        remainder = remainder[:start].strip()

    heading_match = re.match(r"^\s*\d{1,2}\s*/\s*\d+[A-Z]*\.\s*(.*?)(?:\s+—\s+.*)?$",
                             card_name, flags=re.I)
    if not heading_match:
        return None, "scene heading not found"
    heading = heading_match.group(1).strip()

    postavy_match = re.search(r"(?:\A|\n)POSTAVY:\s*(.*?)(?:\n\n|\Z)", remainder, flags=re.S | re.I)
    prepis_match = re.search(r"\*\*PREPIS:\s*(.*?)\*\*", remainder, flags=re.S | re.I)
    if not postavy_match or not prepis_match:
        if re.search(r"^\s*(?:INT\.|EXT\.).*\n\nPOSTAVY:.*\n\n####\s+\*\*", remainder,
                     flags=re.S | re.I):
            return description, "already formatted"
        return None, "POSTAVY or PREPIS not found"

    characters = postavy_match.group(1).strip()
    summary = prepis_match.group(1).strip() or "PREPIS"
    body = remainder[prepis_match.end():].strip()
    core = "\n\n".join([
        normalize_scene_heading(heading),
        f"POSTAVY: {characters}",
        f"#### **{summary}**",
        format_dok4_style_body(body) if body else "",
    ]).strip()
    pieces = [piece for piece in [metadata, core, continuity, suffix] if piece]
    return "\n\n".join(pieces), "converted"


@app.route("/api/format-riverdale-descriptions-like-dok4", methods=["POST"])
def format_riverdale_descriptions_like_dok4():
    if request.headers.get("X-Format-Key") != "riverdale-dok4-description-22jul-81c5f2a4":
        return jsonify({"error": "forbidden"}), 403
    board = trello_get("/boards/CzuD55PR", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "open"
    })
    plans = []; skipped = []; already = []
    for board_list in lists:
        if board_list["name"].strip().casefold() in {"todo", "register rekvizít".casefold()}:
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,shortUrl,idList,closed", "filter": "open", "limit": 1000
        })
        for card in cards:
            if not scene_id_from_card_name(card.get("name")):
                continue
            converted, reason = riverdale_description_to_dok4_style(card["name"], card.get("desc", ""))
            if reason == "already formatted":
                already.append(card)
            elif converted is None:
                skipped.append({"card": card, "reason": reason, "list": board_list["name"]})
            elif converted != card.get("desc", ""):
                plans.append({"card": card, "description": converted, "list": board_list["name"]})

    mode = request.args.get("mode", "dry-run")
    summary = {"board": board["name"], "to_update": len(plans),
               "already_formatted": len(already), "skipped": len(skipped)}
    if mode == "dry-run":
        return jsonify({"status": "dry-run", **summary,
                        "preview": [{"name": item["card"]["name"], "url": item["card"]["shortUrl"],
                                     "before": item["card"].get("desc", "")[:2000],
                                     "after": item["description"][:2500]}
                                    for item in plans[:8]],
                        "skipped_sample": [{"name": item["card"]["name"],
                                            "url": item["card"]["shortUrl"],
                                            "reason": item["reason"], "list": item["list"]}
                                           for item in skipped[:30]]})
    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400
    limit = min(30, max(1, int(request.args.get("limit", "15"))))
    batch = plans[:limit]
    updated = []; errors = []
    for item in batch:
        try:
            trello_put_body(f"/cards/{item['card']['id']}", {"desc": item["description"]})
            updated.append({"name": item["card"]["name"], "url": item["card"]["shortUrl"]})
        except Exception as exc:
            errors.append({"name": item["card"]["name"], "error": str(exc)})
    return jsonify({"status": "applied", **summary, "processed": len(batch),
                    "updated": updated, "errors": errors,
                    "remaining": max(0, len(plans) - len(batch))})


@app.route("/api/move-dok4-medical-prep", methods=["POST"])
def move_dok4_medical_prep():
    if request.headers.get("X-Medical-Prep-Key") != "dok4-medical-prep-19jul-70ac3e91":
        return jsonify({"error": "forbidden"}), 403

    def folded(text):
        value = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in value if not unicodedata.combining(ch)).strip().upper()

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "open"
    })
    moves = []
    for board_list in lists:
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,shortUrl,closed", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })
        for card in cards:
            if not scene_id_from_card_name(card.get("name")):
                continue
            source = next((checklist for checklist in card.get("checklists", [])
                           if folded(checklist.get("name")) == "REKVIZITY"), None)
            if not source:
                continue
            target = next((checklist for checklist in card.get("checklists", [])
                           if folded(checklist.get("name")) == "LEKARSKA PRIPRAVA"), None)
            target_names = {item.get("name", "").strip().casefold()
                            for item in (target or {}).get("checkItems", [])}
            for item in source.get("checkItems", []):
                item_name = item.get("name", "").strip()
                if not re.match(r"^LEKARSKA\s+PRIPRAVA\s*:", folded(item_name)):
                    continue
                moves.append({"card": card, "source": source, "target": target,
                              "item": item, "already_in_target": item_name.casefold() in target_names,
                              "list": board_list["name"]})

    mode = request.args.get("mode", "dry-run")
    if mode == "dry-run":
        return jsonify({"status": "dry-run", "board": board["name"],
                        "items_to_move": len(moves),
                        "cards_affected": len({move['card']['id'] for move in moves}),
                        "already_in_target": sum(1 for move in moves if move["already_in_target"]),
                        "sample": [{"card": move["card"]["name"], "url": move["card"]["shortUrl"],
                                    "list": move["list"], "item": move["item"]["name"]}
                                   for move in moves[:50]]})
    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400

    limit = min(50, max(1, int(request.args.get("limit", "25"))))
    batch = moves[:limit]
    targets_by_card = {}
    moved = []; errors = []
    for move in batch:
        try:
            target = move["target"] or targets_by_card.get(move["card"]["id"])
            if not target:
                target = trello_post_body("/checklists", {
                    "idCard": move["card"]["id"], "name": "LEKÁRSKA PRÍPRAVA", "pos": "bottom"
                })
                targets_by_card[move["card"]["id"]] = target
            if not move["already_in_target"]:
                trello_post_body(f"/checklists/{target['id']}/checkItems", {
                    "name": move["item"]["name"],
                    "checked": "true" if move["item"].get("state") == "complete" else "false",
                    "pos": move["item"].get("pos", "bottom"),
                })
            trello_delete(f"/checklists/{move['source']['id']}/checkItems/{move['item']['id']}")
            moved.append({"card": move["card"]["name"], "item": move["item"]["name"]})
        except Exception as exc:
            errors.append({"card": move["card"]["name"], "item": move["item"]["name"],
                           "error": str(exc)})
    return jsonify({"status": "applied", "processed": len(batch), "moved": moved,
                    "errors": errors, "remaining": max(0, len(moves) - len(batch))})


@app.route("/api/add-dok4-set-checklists", methods=["POST"])
def add_dok4_set_checklists():
    if request.headers.get("X-Set-Checklist-Key") != "dok4-set-checklist-19jul-3c82b75e":
        return jsonify({"error": "forbidden"}), 403
    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "open"
    })
    missing = []; present = 0; scene_count = 0
    for board_list in lists:
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,shortUrl,closed", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })
        for card in cards:
            if not scene_id_from_card_name(card.get("name")):
                continue
            scene_count += 1
            has_set = any(checklist.get("name", "").strip().casefold() == "set"
                          for checklist in card.get("checklists", []))
            if has_set:
                present += 1
            else:
                missing.append({"card": card, "list": board_list["name"]})
    mode = request.args.get("mode", "dry-run")
    if mode == "dry-run":
        return jsonify({"status": "dry-run", "board": board["name"],
                        "scene_cards": scene_count, "set_present": present,
                        "set_missing": len(missing), "sample": [{
                            "card": item["card"]["name"], "list": item["list"],
                            "url": item["card"]["shortUrl"]
                        } for item in missing[:40]]})
    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400
    limit = min(40, max(1, int(request.args.get("limit", "20"))))
    batch = missing[:limit]
    created = []; errors = []
    for item in batch:
        try:
            checklist = trello_post_body("/checklists", {
                "idCard": item["card"]["id"], "name": "SET", "pos": "bottom"
            })
            created.append({"card": item["card"]["name"], "checklist": checklist.get("id")})
        except Exception as exc:
            errors.append({"card": item["card"]["name"], "error": str(exc)})
    return jsonify({"status": "applied", "processed": len(batch), "created": created,
                    "errors": errors, "remaining": max(0, len(missing) - len(batch))})


@app.route("/api/inspect-dok4-checklist-text", methods=["GET"])
def inspect_dok4_checklist_text():
    if request.headers.get("X-Inspect-Key") != "dok4-checklist-inspect-19jul-2fa9c431":
        return jsonify({"error": "forbidden"}), 403

    def folded(text):
        value = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()

    terms = [folded(term) for term in request.args.get("terms", "straznik,vysacka,visacka").split(",")
             if term.strip()]
    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "open"
    })
    matches = []
    for board_list in lists:
        if folded(board_list["name"]).strip() != folded("VŠETKY EPIZÓDY").strip():
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,shortUrl,closed", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })
        for card in cards:
            for checklist in card.get("checklists", []):
                for item in checklist.get("checkItems", []):
                    text = item.get("name", "").strip()
                    normalized = folded(text)
                    if all(term in normalized for term in terms):
                        matches.append({"card": card["name"], "url": card["shortUrl"],
                                        "list": board_list["name"],
                                        "checklist": checklist.get("name"), "item": text,
                                        "state": item.get("state")})
    counts = {}
    for match in matches:
        counts[match["item"]] = counts.get(match["item"], 0) + 1
    return jsonify({"board": board["name"], "matches": len(matches),
                    "cards": len({match['url'] for match in matches}),
                    "exact_text_counts": sorted(
                        [{"text": text, "count": count} for text, count in counts.items()],
                        key=lambda item: (-item["count"], item["text"]))[:100],
                    "items": matches[:500]})


@app.route("/api/delete-dok4-duplicate-guard-badges", methods=["POST"])
def delete_dok4_duplicate_guard_badges():
    if request.headers.get("X-Cleanup-Key") != "dok4-guard-badge-cleanup-19jul-6e94a1bf":
        return jsonify({"error": "forbidden"}), 403

    def folded(text):
        value = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in value if not unicodedata.combining(ch)).strip().upper()

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "open"
    })
    target_list = next((item for item in lists if folded(item["name"]) == "VSETKY EPIZODY"), None)
    if not target_list:
        return jsonify({"error": "VSETKY EPIZODY list not found"}), 404
    duplicates = []
    cards = trello_get(f"/lists/{target_list['id']}/cards", {
        "fields": "id,name,shortUrl,closed", "filter": "open", "limit": 1000,
        "checklists": "all", "checklist_fields": "name",
    })
    for card in cards:
        for checklist in card.get("checklists", []):
            if folded(checklist.get("name")) != "POZNAMKY Z PORADY":
                continue
            for item in checklist.get("checkItems", []):
                text = folded(item.get("name"))
                if "STRAZNIK" in text and "VISACKA" in text:
                    duplicates.append({"card": card, "checklist": checklist, "item": item})
    mode = request.args.get("mode", "dry-run")
    if mode == "dry-run":
        return jsonify({"status": "dry-run", "duplicates": len(duplicates),
                        "cards": len({item['card']['id'] for item in duplicates}),
                        "sample": [{"card": item["card"]["name"],
                                    "url": item["card"]["shortUrl"],
                                    "item": item["item"]["name"]} for item in duplicates[:40]]})
    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400
    limit = min(50, max(1, int(request.args.get("limit", "25"))))
    batch = duplicates[:limit]
    deleted = []; errors = []
    for duplicate in batch:
        try:
            trello_delete(f"/checklists/{duplicate['checklist']['id']}/checkItems/{duplicate['item']['id']}")
            deleted.append({"card": duplicate["card"]["name"], "item": duplicate["item"]["name"]})
        except Exception as exc:
            errors.append({"card": duplicate["card"]["name"], "error": str(exc)})
    return jsonify({"status": "applied", "processed": len(batch), "deleted": deleted,
                    "errors": errors, "remaining": max(0, len(duplicates) - len(batch))})


@app.route("/api/reorder-dok4-scene-checklists", methods=["POST"])
def reorder_dok4_scene_checklists():
    if request.headers.get("X-Reorder-Key") != "dok4-checklist-order-19jul-91bd4e62":
        return jsonify({"error": "forbidden"}), 403

    def folded(text):
        value = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in value if not unicodedata.combining(ch)).strip().upper()

    desired = ["REKVIZITY", "SET", "POZNAMKY Z PORADY", "INFO Z NATACANIA"]
    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "open"
    })
    cards_to_reorder = []; skipped_incomplete = []; already_ordered = 0; scene_cards = 0
    for board_list in lists:
        if "NATOC" in folded(board_list["name"]):
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,shortUrl,closed", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name,pos",
        })
        for card in cards:
            if not scene_id_from_card_name(card.get("name")):
                continue
            scene_cards += 1
            by_name = {}
            for checklist in card.get("checklists", []):
                by_name.setdefault(folded(checklist.get("name")), checklist)
            missing = [name for name in desired if name not in by_name]
            if missing:
                skipped_incomplete.append({"card": card, "list": board_list["name"], "missing": missing})
                continue
            current = [folded(item.get("name")) for item in sorted(
                [by_name[name] for name in desired], key=lambda item: item.get("pos", 0)
            )]
            if current == desired:
                already_ordered += 1
            else:
                cards_to_reorder.append({"card": card, "list": board_list["name"], "checklists": by_name})

    mode = request.args.get("mode", "dry-run")
    if mode == "dry-run":
        return jsonify({"status": "dry-run", "board": board["name"],
                        "active_scene_cards": scene_cards,
                        "cards_to_reorder": len(cards_to_reorder),
                        "already_ordered": already_ordered,
                        "incomplete_skipped": len(skipped_incomplete),
                        "incomplete_sample": [{"card": item["card"]["name"],
                                               "list": item["list"], "missing": item["missing"]}
                                              for item in skipped_incomplete[:40]]})
    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400
    limit = min(40, max(1, int(request.args.get("limit", "20"))))
    batch = cards_to_reorder[:limit]
    updated = []; errors = []
    for item in batch:
        try:
            # Moving in reverse order to top guarantees these four checklists
            # are the first four, while preserving any additional checklists.
            for name in reversed(desired):
                trello_put_body(f"/checklists/{item['checklists'][name]['id']}", {"pos": "top"})
            updated.append(item["card"]["name"])
        except Exception as exc:
            errors.append({"card": item["card"]["name"], "error": str(exc)})
    return jsonify({"status": "applied", "processed": len(batch), "updated": updated,
                    "errors": errors, "remaining": max(0, len(cards_to_reorder) - len(batch))})


@app.route("/api/remove-<project>-meeting-placeholders", methods=["POST"])
def remove_project_meeting_placeholders(project):
    if request.headers.get("X-Placeholder-Key") != "dok4-remove-meeting-placeholders-19jul-a6e81f24":
        return jsonify({"error": "forbidden"}), 403

    def folded(text):
        value = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in value if not unicodedata.combining(ch)).strip().upper()

    boards = {"dunaj": "qCPeWA3e", "dok4": "lzNy4AtY", "riverdale": "CzuD55PR"}
    board_ref = boards.get(project.casefold())
    if not board_ref:
        return jsonify({"error": "unknown project"}), 404
    exact_placeholders = {"[ZMENA]", "[ZRUSENE]", "[PRIDANE]", "[POZIADAVKY]", "[PODLA LOKACIE]"}
    board = trello_get(f"/boards/{board_ref}", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "open"
    })
    matches = []
    for board_list in lists:
        if "NATOC" in folded(board_list["name"]):
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,shortUrl,closed", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })
        for card in cards:
            for checklist in card.get("checklists", []):
                if folded(checklist.get("name")) != "POZNAMKY Z PORADY":
                    continue
                for item in checklist.get("checkItems", []):
                    if folded(item.get("name")) in exact_placeholders:
                        matches.append({"card": card, "checklist": checklist,
                                        "item": item, "list": board_list["name"]})
    mode = request.args.get("mode", "dry-run")
    if mode == "dry-run":
        counts = {}
        for match in matches:
            name = match["item"]["name"]
            counts[name] = counts.get(name, 0) + 1
        return jsonify({"status": "dry-run", "project": project, "board": board["name"],
                        "items_to_delete": len(matches),
                        "cards_affected": len({match['card']['id'] for match in matches}),
                        "counts": counts})
    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400
    limit = min(75, max(1, int(request.args.get("limit", "30"))))
    batch = matches[:limit]
    deleted = []; errors = []
    for match in batch:
        try:
            trello_delete(f"/checklists/{match['checklist']['id']}/checkItems/{match['item']['id']}")
            deleted.append({"card": match["card"]["name"], "item": match["item"]["name"]})
        except Exception as exc:
            errors.append({"card": match["card"]["name"], "item": match["item"]["name"],
                           "error": str(exc)})
    return jsonify({"status": "applied", "processed": len(batch), "deleted": deleted,
                    "errors": errors, "remaining": max(0, len(matches) - len(batch))})


def get_card(card_id):
    return trello_get(f"/cards/{card_id}", {
        "fields": "name,idList,idBoard,shortUrl,desc,due"
    })


def create_card(list_id, name, desc=""):
    return trello_post_body("/cards", {
        "idList": list_id,
        "name": name,
        "desc": desc,
        "pos": "bottom"
    })


def card_exists_in_list(list_id, card_name):
    cards = trello_get(f"/lists/{list_id}/cards", {
        "fields": "name",
        "limit": 1000
    })

    for card in cards:
        if card["name"].strip().lower() == card_name.strip().lower():
            return True

    return False


def find_todo_cards_by_prop(list_id, prop_key):
    cards = trello_get(f"/lists/{list_id}/cards", {
        "fields": "id,name,desc,due,shortUrl,pos", "filter": "open", "limit": 1000
    })
    matches = []
    for card in cards:
        desc = card.get("desc", "")
        source = None
        marker_match = re.search(r"\*\*REKVIZITA:\*\*\s*(.+)", desc, flags=re.I)
        if marker_match:
            source = marker_match.group(1).strip()
        if not source:
            old_match = re.search(r"Pôvodná checklist položka:\s*(.*?)(?:\n\n|$)", desc, flags=re.S | re.I)
            source = old_match.group(1).strip() if old_match else re.split(r"\s+-\s+(?=\d{1,2}/)", card["name"], maxsplit=1)[0]
        key, _ = canonical_prop(source)
        if key == prop_key:
            matches.append(card)
    return sorted(matches, key=lambda card: card.get("pos", 0))


def normalize_item_name(text):
    """
    Z položky odstráni tag [Z], zjednotí malé písmená a medzery.
    Napr.:
    'test [Z]' -> 'test'
    '[Z] test' -> 'test'
    '  TEST   [z] ' -> 'test'
    """
    if not text:
        return ""

    t = text.lower().strip()
    t = t.replace(CHECKLIST_TAG.lower(), "")
    t = " ".join(t.split())
    return t


def tagged_prop_text(item_name):
    """Return the tagged line when a multiline checklist item contains one [z] line."""
    lines = [line.strip() for line in str(item_name or "").splitlines() if CHECKLIST_TAG.lower() in line.lower()]
    return " ".join(lines) if lines else str(item_name or "").strip()


def canonical_prop(item_name):
    """Normalize a sourcing item while keeping action/context outside the matching key."""
    text = normalize_item_name(tagged_prop_text(item_name))
    text = re.split(r"\[(?:h|s)\]", text, maxsplit=1, flags=re.I)[0]
    text = re.split(r"\bnadv\.?\s*", text, maxsplit=1, flags=re.I)[0]
    text = re.split(r"\b\d{1,2}\s*/\s*\d+[A-Z]*\b", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"\s+", " ", text).strip(" -—,.;:")
    folded = unicodedata.normalize("NFKD", text)
    key = "".join(char for char in folded if not unicodedata.combining(char)).lower()
    key = re.sub(r"[^a-z0-9]+", " ", key).strip()
    aliases = (
        (r"^acylpyrin(?: aspirin)?\b", "acylpyrin", "acylpyrin / aspirin"),
        (r"^auto obojzivelnik\b", "auto obojzivelnik", "auto obojživelník"),
        (r"^cigarety(?: pre komparz)?$", "cigarety", "cigarety"),
        (r"^trombon\b", "trombon", "trombón"),
        (r"^cestovne doklady.*astrid|^cestovne doklady vydala americka ambasada", "cestovne doklady pre astrid", "cestovné doklady pre Astrid"),
        (r"^(?:helgine|helgino) auto\b", "helgino auto", "Helgino auto"),
        (r".*(?:walter.*helma|helma.*walter).*", "walterova helma", "Walterova helma"),
        (r".*(?:fotky? richarda a elizy|koptik ma fotky helginych deti).*", "fotky richarda a elizy", "fotky Richarda a Elizy"),
    )
    for pattern, alias_key, alias_display in aliases:
        if re.match(pattern, key):
            return alias_key, alias_display
    return key, text


def scene_id_from_card_name(card_name):
    match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card_name or "", re.I)
    return normalize_scene_id(match.group(1), match.group(2)) if match else None


def build_prop_sync_marker(prop_display, card_info, checklist_item):
    scene_id = scene_id_from_card_name(card_info.get("name")) or "neznámy obraz"
    date_text = (card_info.get("due") or "")[:10] or "bez dátumu"
    return (
        "<!-- DUNAJ-PROP-SYNC:START -->\n"
        "Vytvorené a synchronizované automaticky z obrazových kariet.\n\n"
        f"**REKVIZITA:** {prop_display}\n"
        f"**NAJSKORŠÍ OBRAZ:** {scene_id}\n"
        f"**DUE DATE:** {date_text}\n\n"
        "**OBRAZY, ODKAZY A KONTEXT:**\n\n"
        f"[{scene_id} — {card_info['name']}]({card_info['shortUrl']}) — {date_text}\n\n"
        f"Akcia/kontext: {tagged_prop_text(checklist_item)}\n\n"
        "**NÁJDENÁ KONTINUITA V ĎALŠÍCH OBRAZOCH:**\n"
        f"{scene_id}\n"
        "<!-- DUNAJ-PROP-SYNC:END -->"
    )


def add_scene_to_prop_marker(desc, prop_display, card_info, checklist_item, current_prop_due=None):
    start = "<!-- DUNAJ-PROP-SYNC:START -->"
    end = "<!-- DUNAJ-PROP-SYNC:END -->"
    if start not in desc or end not in desc:
        return build_prop_sync_marker(prop_display, card_info, checklist_item)
    marker = desc[desc.index(start):desc.index(end) + len(end)]
    scene_id = scene_id_from_card_name(card_info.get("name"))
    if not scene_id or card_info["shortUrl"] in marker:
        return marker
    date_text = (card_info.get("due") or "")[:10] or "bez dátumu"
    occurrence = (
        f"[{scene_id} — {card_info['name']}]({card_info['shortUrl']}) — {date_text}\n\n"
        f"Akcia/kontext: {tagged_prop_text(checklist_item)}\n\n"
    )
    marker = marker.replace("**NÁJDENÁ KONTINUITA V ĎALŠÍCH OBRAZOCH:**", occurrence + "**NÁJDENÁ KONTINUITA V ĎALŠÍCH OBRAZOCH:**", 1)
    continuity_match = re.search(r"(\*\*NÁJDENÁ KONTINUITA V ĎALŠÍCH OBRAZOCH:\*\*\n)(.*?)(\n<!-- DUNAJ-PROP-SYNC:END -->)", marker, flags=re.S)
    if continuity_match:
        ids = re.findall(r"\b\d{2}/\d+[A-Z]*\b", continuity_match.group(2), flags=re.I)
        ids.append(scene_id)
        unique_ids = list(dict.fromkeys(value.upper() for value in ids))
        marker = marker[:continuity_match.start(2)] + ", ".join(unique_ids) + marker[continuity_match.end(2):]
    new_due = card_info.get("due")
    if new_due and (not current_prop_due or new_due < current_prop_due):
        marker = re.sub(r"\*\*NAJSKORŠÍ OBRAZ:\*\*.*", f"**NAJSKORŠÍ OBRAZ:** {scene_id}", marker, count=1)
        marker = re.sub(r"\*\*DUE DATE:\*\*.*", f"**DUE DATE:** {new_due[:10]}", marker, count=1)
    return marker


def find_cards_with_exact_item(search_term, board_id, exclude_card_id=None):
    print("SEARCH TERM:", search_term)
    matching_cards = []
    search_norm = normalize_item_name(search_term)

    params = {
        "fields": "name",
        "checklists": "all",
        "checklist_fields": "all",
        "limit": 1000
    }

    try:
        cards = trello_get(f"/boards/{board_id}/cards", params)
        print(f"CARDS LOADED FROM BOARD: {len(cards)}")
    except Exception as e:
        print(f"ERROR loading cards from board: {str(e)}")
        return []

    for card in cards:
        card_id = card["id"]
        card_name = card["name"]

        if exclude_card_id and card_id == exclude_card_id:
            continue

        checklists = card.get("checklists", [])
        found_on_card = False

        for checklist in checklists:
            for item in checklist.get("checkItems", []):
                item_name = item.get("name", "")

                if normalize_item_name(item_name) == search_norm:
                    print(f"MATCH FOUND IN CARD: {card_name}")
                    matching_cards.append(card_name)
                    found_on_card = True
                    break

            if found_on_card:
                break

    print("FINAL MATCHING CARDS:", matching_cards)
    return matching_cards



ROOT = Path(__file__).parent.resolve()
PUBLIC = ROOT / "public"
POWERUP = ROOT / "show_checklist_powerup"
POWERUP_APP_KEY = "8cee1da3131005357e26b21b774ce597"

SCENE_HEADING_RE = re.compile(
    r"^\s*(?:(?:OBRAZ|SC[ÉE]NA|SCENE)\s*)?(\d{1,4})[\).:-]?\s*(.*)$",
    re.IGNORECASE,
)

TV_SCENE_HEADING_RE = re.compile(
    r"^\s*(?P<scene>\d+/\d+)(?P<tag>[A-Z]{0,12})?\.?\s*(?P<title>(?:INT\.?|EXT\.?).*)$",
    re.IGNORECASE,
)


@app.route("/powerup", methods=["GET"])
@app.route("/powerup/", methods=["GET"])
def show_checklist_powerup():
    response = send_from_directory(POWERUP, "index.html")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/powerup/health", methods=["GET"])
def show_checklist_powerup_health():
    return jsonify({"app": "dunaj-show-checklist-powerup", "status": "ok"})


@app.route("/powerup/config.js", methods=["GET"])
def show_checklist_powerup_config():
    response = app.response_class(
        "window.ShowChecklistConfig = Object.freeze({appKey: "
        + json.dumps(POWERUP_APP_KEY)
        + "});\n",
        mimetype="text/javascript",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/powerup/<path:filename>", methods=["GET"])
def show_checklist_powerup_asset(filename):
    response = send_from_directory(POWERUP, filename)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/screener", methods=["GET"])
def screener():
    return send_from_directory(PUBLIC, "index.html")


@app.route("/screener-assets/<path:filename>", methods=["GET"])
def screener_assets(filename):
    return send_from_directory(PUBLIC, filename)

@app.route("/api/parse", methods=["POST"])
def parse_script():
    payload = request.get_json(silent=True) or {}
    cards = split_scenes(payload.get("script", ""))
    return jsonify({"cards": cards})


def split_scenes(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    starts = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()
        if not stripped:
            continue
        if (
            upper.startswith("OBRAZ ")
            or upper.startswith("SCÉNA ")
            or upper.startswith("SCENA ")
            or upper.startswith("SCENE ")
        ):
            starts.append(idx)

    tv_starts = [
        (idx, TV_SCENE_HEADING_RE.match(line.strip()))
        for idx, line in enumerate(lines)
        if TV_SCENE_HEADING_RE.match(line.strip())
    ]
    if tv_starts:
        starts = select_script_body_starts(tv_starts)
        return build_tv_scene_cards(lines, starts)

    if not starts:
        starts = [idx for idx, line in enumerate(lines) if SCENE_HEADING_RE.match(line.strip())]

    if not starts:
        body = "\n".join(lines).strip()
        return [scene_card(1, "Celý scenár", body)]

    cards = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        heading = lines[start].strip()
        match = SCENE_HEADING_RE.match(heading)
        number = int(match.group(1)) if match else pos + 1
        title_tail = match.group(2).strip(" -:") if match else heading
        title = title_tail or heading
        block_lines = block.split("\n")
        body = "\n".join(block_lines[1:]).strip() if len(block_lines) > 1 else block
        cards.append(scene_card(number, title, body))

    return cards



def select_script_body_starts(tv_starts):
    first_scene = tv_starts[0][1].group("scene")
    body_start_pos = 0
    for pos, (_, match) in enumerate(tv_starts[1:], start=1):
        if match.group("scene") == first_scene:
            body_start_pos = pos
    return tv_starts[body_start_pos:]


def build_tv_scene_cards(lines, starts):
    cards = []
    for pos, (start, match) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        scene_id = match.group("scene")
        tag = (match.group("tag") or "").strip()
        title = match.group("title").strip()
        scene_key = format_scene_key(scene_id, tag)
        block_lines = block.split("\n")
        body = "\n".join(block_lines[1:]).strip() if len(block_lines) > 1 else block
        cards.append(scene_card_from_id(scene_key, title, body))
    return cards


def format_scene_key(scene_id, tag):
    episode, scene = scene_id.split("/", 1)
    return f"{int(episode):02d}/{int(scene):02d}{tag}"


def build_trello_scene_title(scene_id, title, characters):
    normalized = normalize_scene_heading(title)
    suffix = f" — {', '.join(name.upper() for name in characters)}" if characters else ""
    return f"{scene_id}. {normalized}{suffix}"


def normalize_scene_heading(title):
    title = re.sub(r"\s+", " ", title.strip())
    title = title.replace(" – ", " - ")
    title = re.sub(r"\s+-\s+(DAY|NIGHT|DEŇ|NOC|RÁNO|RANO|VEČER|VECER)\b", r", \1", title, flags=re.IGNORECASE)
    replacements = {
        "DAY": "DEŇ",
        "NIGHT": "NOC",
        "RANO": "RÁNO",
        "VECER": "VEČER",
    }
    for source, target in replacements.items():
        title = re.sub(rf"\b{source}\b", target, title, flags=re.IGNORECASE)
    return title.upper()


def guess_opening_characters(body):
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    collected = []
    for line in lines[:8]:
        if looks_like_character_line(line):
            collected.extend(split_character_line(line))
            continue
        if collected:
            break
    seen = []
    for name in collected:
        if name and name not in seen:
            seen.append(name)
    return seen[:16]


def looks_like_character_line(line):
    if len(line) > 130:
        return False
    if any(token in line.upper() for token in ["INT.", "EXT.", "OBRAZ", "SCÉNA", "SCENA"]):
        return False
    letters = re.sub(r"[^A-Za-zÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽÄÖÜáčďéíľĺňóôŕšťúýžäöü]", "", line)
    return bool(letters) and line == line.upper()


def split_character_line(line):
    cleaned = re.sub(r"\([^)]*\)", "", line)
    names = re.split(r",|\+| A | S ", cleaned)
    ignored = set()
    return [name.strip().title() for name in names if name.strip().upper() not in ignored]


def format_dok4_style_body(text):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    formatted = []
    dialogue_pattern = re.compile(r"\*\*([^*\n]{1,80}?):\*\*\s*", re.S)
    for paragraph in paragraphs:
        if paragraph.startswith("<!--") or paragraph.startswith("####"):
            formatted.append(paragraph)
            continue
        matches = list(dialogue_pattern.finditer(paragraph))
        if matches and matches[0].start() == 0:
            blocks = []
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(paragraph)
                spoken = paragraph[match.end():end].strip()
                speaker = match.group(1).strip()
                blocks.append(f"> **{speaker}:**")
                if spoken:
                    blocks.append(f"> **{spoken}**")
            formatted.append("\n".join(blocks))
        elif paragraph.startswith(">"):
            formatted.append(paragraph)
        elif paragraph.startswith("*") and paragraph.endswith("*"):
            formatted.append(paragraph)
        else:
            formatted.append(f"*{paragraph}*")
    return "\n\n".join(formatted)


def build_trello_description(characters, body, scene_heading=""):
    cleaned = body.strip()
    lines = cleaned.split("\n")
    while lines and (not lines[0].strip() or looks_like_character_line(lines[0].strip())):
        lines.pop(0)
    scene_text = "\n".join(lines).strip()
    lead, rest = split_lead_sentence(scene_text)
    parts = []
    if scene_heading:
        parts.extend([normalize_scene_heading(scene_heading), ""])
    parts.extend([
        f"POSTAVY: {', '.join(name.upper() for name in characters) if characters else 'DOPLNIŤ'}", "",
        f"#### **{lead}**" if lead else "#### **PREPIS**",
    ])
    if rest:
        parts.extend(["", format_dok4_style_body(format_scene_body(rest))])
    return "\n".join(parts).strip()


def split_lead_sentence(text):
    normalized = text.strip()
    if not normalized:
        return "", ""
    first_line, separator, rest = normalized.partition("\n")
    if separator:
        return first_line.strip(), rest.strip()
    match = re.search(r"(?<=[.!?])\s+", normalized)
    if not match:
        return normalized, ""
    return normalized[: match.start()].strip(), normalized[match.end() :].strip()


def format_scene_body(text):
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line and not re.fullmatch(r"\d{1,3}", line)]
    blocks = []
    buffer = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if looks_like_character_line(line):
            flush_text_block(blocks, buffer)
            speaker = line
            dialogue = []
            i += 1
            while i < len(lines) and not looks_like_character_line(lines[i]):
                if not re.fullmatch(r"\d{1,3}", lines[i]):
                    dialogue.append(lines[i])
                i += 1
            spoken = join_wrapped_lines(dialogue)
            blocks.append(f"**{speaker}:** {spoken}".strip())
            continue

        buffer.append(line)
        i += 1

    flush_text_block(blocks, buffer)
    return "\n\n".join(block for block in blocks if block).strip()


def flush_text_block(blocks, buffer):
    if buffer:
        blocks.append(join_wrapped_lines(buffer))
        buffer.clear()


def join_wrapped_lines(lines):
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()



PROP_RULES = [
    ("Policajné auto", r"\bpolicajne auto\b"),
    ("Policajná páska / opáskované miesto", r"\bopaskoval\w*|\bpask\w*"),
    ("Nosidlá / vak na telo", r"\bnosidl\w*|\bzazipsovan\w*"),
    ("Auto", r"\baut(?:o|a|e|om|u)\b"),
    ("Limuzína / SUV", r"\blimuzin\w*|\bsuv\b"),
    ("Čln", r"\bcln\w*"),
    ("Notebook", r"\bnotebook\w*"),
    ("Mobil", r"\bmobil\w*"),
    ("Fotoalbum", r"\bfotoalbum\w*"),
    ("Fotky", r"\bfotk\w*"),
    ("Šatka", r"\bsatk\w*"),
    ("Batoh", r"\bbatoh\w*"),
    ("Školská taška", r"\bskolsk\w+\s+task\w*"),
    ("Taška s jedlom", r"\btask\w*.{0,40}\bjedl\w*|\bjedl\w*.{0,40}\btask\w*"),
    ("Nákupné tašky", r"\bnakupn\w+\s+task\w*"),
    ("Cestovná taška s monogramom L.S.", r"\bcestovn\w+\s+.*task\w*|\bmonogram\w*"),
    ("Taška", r"\btask\w*"),
    ("Obálka s peniazmi", r"\bobalk\w*|\bpeniaz\w*"),
    ("Blister s liekmi / Ritalin", r"\bblister\w*|\britalin\b|\bliek\w*"),
    ("DJ pult", r"\bdj pult\w*"),
    ("Laptop", r"\blaptop\w*"),
    ("Looper", r"\blooper\w*"),
    ("Klávesy", r"\bklaves\w*"),
    ("Slúchadlá", r"\bsluchadl\w*"),
    ("Automaty na snacky a pitie", r"\bautomat\w*"),
    ("Nástenka", r"\bnastenk\w*"),
    ("JBL reproduktor", r"\bjbl\b"),
    ("Pištoľ / zbraň", r"\bpistol\w*|\bzbran\w*"),
    ("Basketbalová lopta", r"\blopt\w*"),
    ("Uterák", r"\buterak\w*"),
    ("Mikrofón", r"\bmikrofon\w*"),
    ("Gitara", r"\bgitara\b|\bgitare\b|\bgitarou\b|\bna gitare\b"),
    ("Loptička pre psa", r"\bloptick\w*"),
    ("Pivo", r"\bpiv\w*"),
    ("Výzdoba", r"\bvyzdob\w*"),
    ("Jedlo a pitie", r"\bjedlo\b|\bpitie\b"),
    ("Drinky", r"\bdrink\w*"),
    ("Víno", r"\bvin\w*"),
]


def extract_rekvizity(text):
    normalized = normalize_for_lookup(text)
    props = []
    for label, pattern in PROP_RULES:
        if re.search(pattern, normalized, re.IGNORECASE):
            props.append(label)
    return prune_rekvizity(props)


def normalize_for_lookup(text):
    replacements = str.maketrans(
        "áäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ",
        "aacdeillnoorstuyzAACDEILLNOORSTUYZ",
    )
    return text.translate(replacements).lower()


def prune_rekvizity(props):
    if "Školská taška" in props or "Taška s jedlom" in props or "Nákupné tašky" in props or "Cestovná taška s monogramom L.S." in props:
        props = [prop for prop in props if prop != "Taška"]
    if "Loptička pre psa" in props:
        props = [prop for prop in props if prop != "Basketbalová lopta"]
    seen = []
    for prop in props:
        if prop not in seen:
            seen.append(prop)
    return seen


def adjust_rekvizity_for_scene(scene_id, props):
    removals = {
        "01/12FLASH": {"Čln", "Šatka"},
        "01/17": {"Gitara"},
        "01/27FLASH": {"Notebook", "Mikrofón"},
    }
    blocked = removals.get(scene_id, set())
    if blocked:
        props = [prop for prop in props if prop not in blocked]
    return props


SCENE_REKVIZITY_DETAILS = {
    "01/02LP": {
        "Auto": "Auto Jakuba a Sáry - cesta k rieke; nadväzuje na 01/03LP a 01/04LP; aj letecký záber na auto",
    },
    "01/03LP": {
        "Auto": "Auto Jakuba a Sáry - pokračuje lesom k rieke; nadväzuje na 01/02LP a pokračuje v 01/04LP",
    },
    "01/04LP": {
        "Auto": "Auto Jakuba a Sáry - zastaví pri rieke, výstup z auta; nadväzuje na 01/02LP-01/03LP",
        "Čln": "Čln pri rieke - Jakub a Sára sa presúvajú k plavbe; nadväzuje na 01/06LP",
    },
    "01/06LP": {
        "Čln": "Čln na rieke - Jakub vesluje, Sára sedí v člne; nadväzuje na 01/04LP",
    },
    "01/08LP": {
        "Čln": "Policajný čln - policajti z člna koordinujú hľadanie Jakubovho tela",
    },
    "01/09": {
        "Policajné auto": "Policajné auto - blikajúce v pozadí na brehu rieky pri vyšetrovaní Jakuba",
        "Čln": "Policajný čln / riečny zásah - nadväzuje na hľadanie tela v 01/08LP",
        "Auto": None,
    },
    "01/11FLASH": {
        "Šatka": "Sárina šatka - pláva vo vode; súčasť Sárinej verzie nehody, nadväzuje na rozprávanie v 01/12FLASH",
    },
    "01/12FLASH": {
        "Notebook": "Dogyho notebook vo Fefe Beef - Dogy píše román/VO, rámuje flashback so Sárou",
        "Fotoalbum": "Sárin fotoalbum - Sára si v izbe prezerá Jakubove fotky",
        "Fotky": "Jakubove fotky vo fotoalbume - používa Sára pri spomienke na Jakuba",
    },
    "01/13": {
        "Limuzína / SUV": "Čierna limuzína / SUV vyššej triedy - Veronika a Laura prichádzajú pred vilu",
    },
    "01/15": {
        "Auto": "Kikove auto - Kiko a Bety prichádzajú pred dom Bety; Alex sa objaví pred autom",
    },
    "01/16": {
        "Mobil": "Betin mobil - Bety kontroluje displej, Kiko jej ho berie",
    },
    "01/17": {
        "Taška s jedlom": "Zabalená taška s jedlom pre Veroniku - Fefe ju prinesie a položí na pult",
    },
    "01/18": {
        "Batoh": "Alexov batoh do školy - Alex doň hodí posledné veci a zazipsuje ho",
        "Obálka s peniazmi": "Obálka s peniazmi od Lukáša - Lukáš ňou máva, rieši prácu v kancli",
    },
    "01/19": {
        "Batoh": "Betin školský batoh/taška - Bety sa chystá do školy a balí si veci",
        "Taška": "Betina taška do školy - Bety si ju balí pred odchodom",
        "Blister s liekmi / Ritalin": "Blister s Ritalinom - Alica ho podá Bety, Bety si ho berie",
    },
    "01/22": {
        "DJ pult": "DJ pult v hudobnej miestnosti - obsluhuje ho Mery",
        "Laptop": "Laptop pri DJ pulte - súčasť Merynej hudobnej zostavy",
        "Looper": "Looper - súčasť Merynej elektronickej hudobnej zostavy",
        "Klávesy": "Klávesy / malé klávesy - Lea hrá na klávesoch, Mery ich má pri DJ pulte",
        "Slúchadlá": "Slúchadlá Mery - Mery ich má na ušiach pri obsluhe DJ pultu",
    },
    "01/23": {
        "Mobil": "Alexov mobil - Alex ťuká do mobilu pri automate/nástenke",
        "Automaty na snacky a pitie": "Automat na chodbe - Alex si pri ňom vyberá vec alebo sa zastaví pri nástenke",
        "Nástenka": "Školská nástenka - alternatívna akcia Alexa pri chodbe so skrinkami",
    },
    "01/27FLASH": {
        "Auto": "Auto Olasovej - deň pri stavbe a noc na parkovisku; kontinuita s 01/26FLASH a 01/32FLASH",
    },
    "01/30": {
        "Mobil": "Alexov mobil - Alex púšťa Bety a Kikovi svoju pesničku",
        "Školská taška": "Alexova školská taška - Alex ju berie pri odchode",
        "Automaty na snacky a pitie": "Automaty v školskej klubovni - snacky a pitie v pozadí scény",
        "Jedlo a pitie": "Jedlo a pitie v klubovni - decká sedia, kecajú a jedia",
    },
    "01/32FLASH": {
        "Auto": "Auto Olasovej - odstavené pri rieke počas výstrelu; kontinuita 01/26FLASH-01/27FLASH-01/32FLASH",
        "Mobil": "Alexov mobil - Alex púšťa Olasovej demo/pesničku",
        "Pištoľ / zbraň": "Pištoľ / zbraň mimo obrazu - postavy počujú výstrel pri rieke",
    },
    "01/33": {
        "Mobil": "Mobil s hudbou - púšťa sa rovnaká pesnička/demoverzia",
        "JBL reproduktor": "JBL reproduktor - hudba pustená z mobilu cez JBL, Sára chce hudbu vypnúť",
    },
    "01/34": {
        "Basketbalová lopta": "Basketbalová lopta - tréning v telocvični, Alex dribluje a dáva kôš",
        "Uterák": "Alexov uterák - Alex sa utiera po tréningu",
    },
    "01/38": {
        "Nákupné tašky": "Nákupné tašky Laury - Gajdoš ich nesie za Laurou a položí ich",
        "Cestovná taška s monogramom L.S.": "Stratená cestovná príručná taška s monogramom L.S. - priniesol ju taxík, Laura ju otvorí",
    },
    "01/39": {
        "Gitara": "Alexova gitara - Alex na terase hrá/brnká a skladá",
        "Loptička pre psa": "Loptička pre Bona - voliteľná rekvizita pri psovi, ak ju bude Bono nosiť",
        "Pivo": "Lukášovo pivo - Lukáš vyjde na terasu s pivom v ruke",
    },
    "01/40": {
        "Výzdoba": "Výzdoba imatrikulačnej párty v telocvični - školská párty, nadväzuje na 01/42-01/43",
        "Jedlo a pitie": "Jedlo a nealko pitie na imatrikulačnej párty - školská akcia, bez alkoholu",
    },
    "01/44": {
        "Drinky": "Drinky na Sárinej afterke - partia sedí v Sárinej izbe a popíja",
    },
    "01/48": {
        "Víno": "Laurino víno - Laura sedí na gauči v župane a pije víno",
    },
    "01/49": {
        "Notebook": "Dogyho notebook vo Fefe Beef - Dogy sedí a píše svoj román, nadväzuje na 01/52",
    },
    "01/52": {
        "Policajné auto": "Policajné auto - miesto nálezu Jakubovho tela pri rieke; strihák 01/53LP je zatiaľ v karte 01/52",
        "Policajná páska / opáskované miesto": "Policajná páska / opáskované miesto - pri náleze Jakubovho tela",
        "Nosidlá / vak na telo": "Nosidlá / vak na telo - policajti odnášajú Jakubovo telo už zazipsované",
        "Notebook": "Dogyho notebook vo Fefe Beef - Dogy píše o zastrelení Jakuba; nadväzuje na 01/49",
        "Mobil": "Alicin mobil - Alica si robí zábery z miesta činu, Bety na ňu zazerá",
        "Auto": None,
    },
}


def enrich_rekvizity_for_scene(scene_id, props):
    details = SCENE_REKVIZITY_DETAILS.get(scene_id, {})
    enriched = []
    for prop in props:
        if prop in details:
            replacement = details[prop]
            if replacement:
                enriched.append(replacement)
            continue
        enriched.append(prop)
    return enriched

def scene_card_from_id(scene_id, title, body):
    characters = guess_opening_characters(body)
    props = extract_rekvizity(f"{title}\n{body}")
    props = adjust_rekvizity_for_scene(scene_id, props)
    props = enrich_rekvizity_for_scene(scene_id, props)
    card_title = build_trello_scene_title(scene_id, title, characters)
    card = scene_card(0, title, body)
    card["number"] = scene_id
    card["name"] = card_title
    card["description"] = build_trello_description(characters, body, title)
    card["characters"] = characters
    card["labels"] = []
    card["checklistName"] = "Rekvizity"
    card["checklist"] = props
    card["checklists"] = [
        {"name": "Rekvizity", "items": props},
        {"name": "Poznamky z porady", "items": []},
        {"name": "Info z natacania", "items": []},
    ]
    return card


def scene_card(number, title, body):
    clean_body = body.strip()
    location = guess_location(title, clean_body)
    time_of_day = guess_time(title, clean_body)
    characters = guess_characters(clean_body)
    labels = [
        value
        for value in [
            time_of_day,
            "interiér" if "INT" in title.upper() else None,
            "exteriér" if "EXT" in title.upper() else None,
        ]
        if value
    ]

    return {
        "number": number,
        "name": f"Obraz {number:02d} - {title.strip() or 'Bez názvu'}",
        "description": build_description(location, time_of_day, characters, clean_body),
        "location": location,
        "timeOfDay": time_of_day,
        "characters": characters,
        "labels": labels,
        "checklist": [
            "Overiť postavy v obraze",
            "Doplniť lokáciu",
            "Doplniť rekvizity/kostýmy",
            "Potvrdiť produkčné poznámky",
        ],
    }


def guess_location(title, body):
    first = title or body.split("\n", 1)[0]
    normalized = first.replace("INT.", "").replace("EXT.", "").replace("INT", "").replace("EXT", "")
    normalized = re.split(
        r"\s+-\s+|\s+–\s+|\s+/\s*(?:DEŇ|DEN|NOC|RÁNO|RANO|VEČER|VECER)",
        normalized,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return normalized.strip(" .:-")[:80] or "Neurčená lokácia"


def guess_time(title, body):
    sample = f"{title}\n{body[:500]}".upper()
    for key, value in [
        ("NOC", "noc"),
        ("VEČER", "večer"),
        ("VECER", "večer"),
        ("RÁNO", "ráno"),
        ("RANO", "ráno"),
        ("DEŇ", "deň"),
        ("DEN", "deň"),
    ]:
        if key in sample:
            return value
    return ""


def guess_characters(body):
    names = []
    for line in body.split("\n"):
        stripped = line.strip()
        if (
            2 <= len(stripped) <= 32
            and stripped == stripped.upper()
            and re.search(r"[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ]", stripped)
            and not any(token in stripped for token in ["INT", "EXT", "OBRAZ", "SCENA", "SCÉNA"])
        ):
            names.append(stripped.title())

    seen = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen[:12]


def build_description(location, time_of_day, characters, body):
    parts = [
        f"Lokácia: {location}",
        f"Čas: {time_of_day or 'neurčený'}",
        f"Postavy: {', '.join(characters) if characters else 'doplniť'}",
        "",
        "Scenár / poznámky:",
        body,
    ]
    return "\n".join(parts).strip()


@app.route("/", methods=["GET"])
def home():
    return "Trello webhook server is running", 200


@app.route("/trello-webhook", methods=["HEAD"])
def trello_head():
    return "", 200


@app.route("/api/create-riverdale-workflow-test-v2", methods=["POST"])
def create_riverdale_workflow_test_v2():
    return jsonify({"error": "test endpoint disabled"}), 410

    if request.headers.get("X-Test-Key") != "riverdale-workflow-v2-8c31e74a":
        return jsonify({"error": "forbidden"}), 403

    board_id = trello_get("/boards/CzuD55PR", {"fields": "id"})["id"]
    existing_lists = trello_get(f"/boards/{board_id}/lists", {"fields": "name,closed"})
    lists_by_name = {item["name"]: item for item in existing_lists if not item.get("closed")}

    def ensure_list(name):
        if name not in lists_by_name:
            lists_by_name[name] = trello_post_body("/lists", {
                "idBoard": board_id, "name": name, "pos": "bottom"
            })
        return lists_by_name[name]

    inbox = ensure_list("TEST — SPRACOVANÉ OBRAZY")
    sourcing = ensure_list("TEST — TREBA ZOHNAŤ / VYROBIŤ")
    shoot_day = ensure_list("TEST — NATÁČANIE 31. 7. 2026")
    shot = ensure_list("TEST — NATOČENÉ")

    all_test_cards = []
    for target_list in (inbox, sourcing, shoot_day, shot):
        all_test_cards.extend(trello_get(
            f"/lists/{target_list['id']}/cards", {"fields": "name,shortUrl", "limit": 100}
        ))
    if all_test_cards:
        return jsonify({"status": "exists", "cards": [
            {"name": card["name"], "url": card.get("shortUrl")} for card in all_test_cards
        ]})

    board_labels = trello_get(f"/boards/{board_id}/labels", {"fields": "name,color", "limit": 1000})
    labels = {item.get("name", "").casefold(): item for item in board_labels}

    def ensure_label(name, color):
        if name.casefold() not in labels:
            labels[name.casefold()] = trello_post_body("/labels", {
                "idBoard": board_id, "name": name, "color": color
            })
        return labels[name.casefold()]["id"]

    label_test = ensure_label("TEST WORKFLOW", "sky")
    label_source = ensure_label("TREBA ZOHNAŤ", "orange")
    label_ready = ensure_label("PRIPRAVENÉ", "green")
    label_shot = ensure_label("NATOČENÉ", "blue")
    label_continuity = ensure_label("KONTINUITA", "red")

    def add_checklist(card_id, name, items):
        checklist = trello_post_body("/checklists", {"idCard": card_id, "name": name})
        for item in items:
            trello_post_body(f"/checklists/{checklist['id']}/checkItems", {"name": item})

    imported = trello_post_body("/cards", {
        "idList": inbox["id"],
        "name": "[TEST][SPRACOVANÉ] 01/06 — INT. ŠKOLA, CHODBA — DEŇ",
        "desc": (
            "**DIEL:** 1  |  **OBRAZ:** 01/06\n\n"
            "**LOKÁCIA:** Škola — chodba\n"
            "**ČAS:** Deň\n"
            "**POSTAVY:** Bety, Veronika, Sebo\n"
            "**STAV:** čaká na zaradenie do natáčacieho plánu\n\n"
            "### DEJ A AKCIA\n"
            "Bety zastaví Seba na chodbe a ukáže mu vytlačenú fotografiu. Sebo si ju vezme, "
            "prehne ju a vloží do zadného vrecka.\n\n"
            "### REKVIZITY V KONTEXTE\n"
            "- **Vytlačená fotografia Bety a Seba** — Bety ju podá Sebovi; Sebo ju prehne a odloží do vrecka. "
            "Treba pripraviť identické kusy pred prehnutím aj po prehnutí.\n"
            "- **Sebov mobil** — drží ho v pravej ruke pri príchode; rovnaký čierny obal ako v predchádzajúcich obrazoch.\n\n"
            "### KONTINUITA\n"
            "Fotografia prechádza zo stavu NEPREHNUTÁ na PREHNUTÁ. Evidovať variant a miesto uloženia."
        ),
        "idLabels": f"{label_test},{label_continuity}",
        "pos": "bottom",
    })
    add_checklist(imported["id"], "AUTOMATICKÁ KONTROLA", [
        "Dej a postavy vypísané", "Rekvizity vypísané v kontexte", "Nadväznosť označená",
        "Čaká na dátum natáčania",
    ])

    acquisition = trello_post_body("/cards", {
        "idList": sourcing["id"],
        "name": "[TEST][ZOHNAŤ] Fotografia Bety a Seba — 6 identických kusov",
        "desc": (
            "**VZNIKLO AUTOMATICKY Z OBRAZU:** 01/06\n"
            "**SPÔSOB:** vyrobiť / vytlačiť\n"
            "**MNOŽSTVO:** 3× neprehnutá + 3× prehnutá\n"
            "**INTERNÝ DEADLINE:** 29. 7. 2026\n"
            "**PRVÉ NATÁČANIE:** 31. 7. 2026\n\n"
            "Fotografia musí byť rovnakého formátu, orezu a papiera. Jeden čistý kus odložiť ako kontinuitný master."
        ),
        "idLabels": f"{label_test},{label_source},{label_continuity}",
        "due": "2026-07-29T12:00:00.000Z",
        "pos": "bottom",
    })
    add_checklist(acquisition["id"], "ZABEZPEČENIE", [
        "Vybrať a schváliť fotografiu", "Pripraviť tlačové dáta", "Vytlačiť 6 kusov",
        "Pripraviť tri prehnuté varianty", "Označiť kontinuitný master", "Odovzdať na pľac",
    ])

    scheduled = trello_post_body("/cards", {
        "idList": shoot_day["id"],
        "name": "[TEST][PLÁN 04] 01/06 — INT. ŠKOLA, CHODBA — DEŇ",
        "desc": (
            "**NATÁČANIE:** 31. 7. 2026  |  **PORADIE DŇA:** 4\n"
            "**CALL:** 10:40  |  **LOKÁCIA:** Škola — chodba\n\n"
            "Táto karta demonštruje automatické zaradenie spracovaného obrazu podľa natáčacieho plánu.\n\n"
            "### PRÍPRAVA NA DEŇ\n"
            "Fotografia: 1× neprehnutá v ruke Bety, náhradné kusy pri rekvizitárovi. "
            "Sebov mobil: čierny obal, nabitý, bez viditeľných notifikácií."
        ),
        "idLabels": f"{label_test},{label_ready},{label_continuity}",
        "due": "2026-07-31T08:40:00.000Z",
        "pos": "bottom",
    })
    add_checklist(scheduled["id"], "REKVIZITY NA PĽAC", [
        "Fotografia — hero kus neprehnutý", "Fotografia — 5 náhradných variantov",
        "Sebov mobil — čierny obal", "Kontinuitná fotografia pred prvou klapkou",
    ])
    add_checklist(scheduled["id"], "PO OBRAZE", [
        "Označiť použitý variant", "Nahrať fotografiu kontinuity", "Zapísať poškodenie / zmenu",
        "Označiť obraz ako natočený",
    ])

    completed = trello_post_body("/cards", {
        "idList": shot["id"],
        "name": "[TEST][NATOČENÉ] 01/05 — EXT. PRED ŠKOLOU — DEŇ",
        "desc": (
            "**NATOČENÉ:** 30. 7. 2026  |  **POSLEDNÁ KLAPKA:** 16:25\n"
            "**STAV:** natočené — automaticky presunuté po potvrdení rekvizitárom\n\n"
            "### SKUTOČNÝ STAV PO NATÁČANÍ\n"
            "Sebov mobil bez poškodenia, čierny obal zostáva nasadený. Kontinuitná fotografia priložená/doplní sa. "
            "Mobil pokračuje do obrazu 01/06."
        ),
        "idLabels": f"{label_test},{label_shot},{label_continuity}",
        "dueComplete": "true",
        "pos": "bottom",
    })
    add_checklist(completed["id"], "UZAVRETIE OBRAZU", [
        "Rekvizity spočítané", "Stav nadväzných rekvizít zapísaný", "Kontinuita zdokumentovaná",
        "Rekvizity vrátené / presunuté k ďalšiemu obrazu",
    ])

    for source, target, name in (
        (imported, acquisition, "Zabezpečenie — fotografia"),
        (acquisition, imported, "Zdrojový obraz 01/06"),
        (scheduled, acquisition, "Úloha — fotografia"),
        (completed, scheduled, "Nasledujúci obraz 01/06"),
    ):
        trello_post_body(f"/cards/{source['id']}/attachments", {
            "url": target["shortUrl"], "name": name
        })

    cards = (imported, acquisition, scheduled, completed)
    return jsonify({"status": "created", "cards": [
        {"name": card["name"], "url": card["shortUrl"]} for card in cards
    ]})


@app.route("/api/create-riverdale-simple-workflow-test", methods=["POST"])
def create_riverdale_simple_workflow_test():
    return jsonify({"error": "test endpoint disabled"}), 410

    if request.headers.get("X-Test-Key") != "riverdale-simple-v1-72d941ac":
        return jsonify({"error": "forbidden"}), 403

    board_id = trello_get("/boards/CzuD55PR", {"fields": "id"})["id"]
    board_lists = trello_get(f"/boards/{board_id}/lists", {"fields": "name,closed"})
    lists_by_name = {item["name"]: item for item in board_lists if not item.get("closed")}

    def ensure_list(name):
        if name not in lists_by_name:
            lists_by_name[name] = trello_post_body("/lists", {
                "idBoard": board_id, "name": name, "pos": "bottom"
            })
        return lists_by_name[name]

    scenes_list = ensure_list("TEST 2 — OBRAZY")
    todo_list = ensure_list("TEST 2 — ToDo REKVIZITY")
    existing = trello_get(f"/lists/{scenes_list['id']}/cards", {
        "fields": "name,shortUrl", "limit": 100
    }) + trello_get(f"/lists/{todo_list['id']}/cards", {
        "fields": "name,shortUrl", "limit": 100
    })
    if existing:
        return jsonify({"status": "exists", "cards": [
            {"name": card["name"], "url": card.get("shortUrl")} for card in existing
        ]})

    labels = {item.get("name", "").casefold(): item for item in trello_get(
        f"/boards/{board_id}/labels", {"fields": "name,color", "limit": 1000}
    )}

    def ensure_label(name, color):
        if name.casefold() not in labels:
            labels[name.casefold()] = trello_post_body("/labels", {
                "idBoard": board_id, "name": name, "color": color
            })
        return labels[name.casefold()]["id"]

    test_label = ensure_label("TEST 2", "sky")
    continuity_label = ensure_label("NADVÄZNÁ REKVIZITA", "red")
    source_label = ensure_label("ZOHNAŤ / VYROBIŤ", "orange")
    screen_label = ensure_label("SCREEN", "purple")

    def add_checklist(card_id, name, items):
        checklist = trello_post_body("/checklists", {"idCard": card_id, "name": name})
        for item in items:
            trello_post_body(f"/checklists/{checklist['id']}/checkItems", {"name": item})

    scene = trello_post_body("/cards", {
        "idList": scenes_list["id"],
        "name": "[TEST 2] 01/28. INT. ŠKOLA — CHLAPČENSKÁ ŠATŇA, DEŇ",
        "desc": (
            "**DIEL:** 01  |  **OBRAZ:** 28\n"
            "**LOKÁCIA:** Škola — chlapčenská šatňa\n"
            "**ČAS:** DEŇ  |  **INT/EXT:** INT\n"
            "**POSTAVY:** Bety, Veronika, Kiko, Eva, Sára\n"
            "**NATÁČANIE:** zatiaľ nenaplánované\n\n"
            "### DEJ OBRAZU\n"
            "Dievčatá prehľadávajú skrinky basketbalistov. Podľa tímovej fotografie Bety odhalí "
            "Sebov PIN 5656, odomkne jeho mobil a nájde tajný kanál Blackstone&sluts.\n\n"
            "### REKVIZITY V KONTEXTE\n"
            "Podrobný výpis je v checkliste REKVIZITY. Každá položka obsahuje vlastníka, akciu, "
            "požadovaný stav a kontinuitu.\n\n"
            "### KONTINUITA\n"
            "Sebov mobil musí mať vo všetkých nadväzných obrazoch rovnaký čierny obal. "
            "Po odomknutí musí byť pripravený rovnaký obsah kanála a PIN 5656."
        ),
        "idLabels": f"{test_label},{continuity_label},{screen_label}",
        "pos": "bottom",
    })
    add_checklist(scene["id"], "REKVIZITY", [
        "Sebov mobil — Bety ho vyberie zo skrinky, zadá PIN 5656 a otvorí kanál Blackstone&sluts; čierny obal, nabitý, obsah dostupný offline",
        "Tímová fotografia basketbalistov — visí pri skrinkách; Bety podľa čísel hráčov odhalí Sebov PIN; pripraviť tlač a identický náhradný kus",
        "Školské skrinky — dievčatá ich postupne otvárajú a prehľadávajú; určiť presné skrinky a zachovať rozmiestnenie obsahu",
    ])
    add_checklist(scene["id"], "Poznámky z porady", [
        "Doplniť sem zmeny schválené na porade — synchronizácia následne upraví REKVIZITY a ToDo karty",
    ])
    add_checklist(scene["id"], "Info z natáčania", [
        "Po natočení zapísať použitý mobil, stav obalu, použitú fotografiu a priložiť kontinuitné fotky",
    ])

    phone = trello_post_body("/cards", {
        "idList": todo_list["id"],
        "name": "[TEST 2][ToDo] SEBOV MOBIL — pripraviť screen Blackstone&sluts",
        "desc": (
            "**REKVIZITA:** Sebov mobil\n**SPÔSOB:** pripraviť / otestovať\n"
            "**SÚVISIACI OBRAZ:** 01/28\n**TERMÍN:** vypočíta sa po importe natáčacieho plánu\n\n"
            "Bety mobil vyberie zo skrinky, odomkne PIN-om 5656 a otvorí tajný kanál. "
            "Pripraviť čierny obal, konkrétny obsah obrazovky a offline zálohu."
        ),
        "idLabels": f"{test_label},{source_label},{screen_label},{continuity_label}",
        "pos": "bottom",
    })
    add_checklist(phone["id"], "ZABEZPEČENIE", [
        "Vybrať fyzický mobil a čierny obal", "Pripraviť obsah kanála", "Nastaviť PIN 5656",
        "Otestovať offline režim", "Pripraviť záložný mobil alebo video", "Schváliť po porade",
    ])

    photo = trello_post_body("/cards", {
        "idList": todo_list["id"],
        "name": "[TEST 2][ToDo] TÍMOVÁ FOTOGRAFIA BASKETBALISTOV — vyrobiť 2 kusy",
        "desc": (
            "**REKVIZITA:** tímová fotografia\n**SPÔSOB:** grafika + tlač\n"
            "**SÚVISIACI OBRAZ:** 01/28\n**TERMÍN:** vypočíta sa po importe natáčacieho plánu\n\n"
            "Fotografia visí pri skrinkách a pomôže Bety odvodiť Sebov PIN. Musia byť čitateľné "
            "čísla hráčov; pripraviť hero kus a identickú náhradu."
        ),
        "idLabels": f"{test_label},{source_label},{continuity_label}",
        "pos": "bottom",
    })
    add_checklist(photo["id"], "ZABEZPEČENIE", [
        "Vybrať hráčov a čísla dresov", "Schváliť kompozíciu", "Pripraviť grafiku",
        "Vytlačiť hero kus", "Vytlačiť identickú náhradu", "Zdokumentovať umiestnenie pri skrinkách",
    ])

    for source, target, name in (
        (scene, phone, "ToDo — Sebov mobil"), (scene, photo, "ToDo — tímová fotografia"),
        (phone, scene, "Zdrojový obraz 01/28"), (photo, scene, "Zdrojový obraz 01/28"),
    ):
        trello_post_body(f"/cards/{source['id']}/attachments", {
            "url": target["shortUrl"], "name": name
        })

    return jsonify({"status": "created", "cards": [
        {"name": card["name"], "url": card["shortUrl"]} for card in (scene, phone, photo)
    ]})


@app.route("/api/update-riverdale-test-with-original-script", methods=["POST"])
def update_riverdale_test_with_original_script():
    return jsonify({"error": "update endpoint disabled"}), 410

    if request.headers.get("X-Test-Key") != "riverdale-original-03-28-5c8a41d2":
        return jsonify({"error": "forbidden"}), 403

    scene = trello_get("/cards/p1WdZ1MD", {"fields": "name,desc,shortUrl"})
    original_script = """### ORIGINÁLNY SCENÁR — KOMPLETNÝ PREPIS

Bety, Veronika, Eva a Kiko sa potichu pohybujú po chlapčenskej šatni. Kiko stojí pri dverách a dáva pozor. Nazerá smerom do telocvične, aby dal signál, keby sa niekto chcel vrátiť do šatne. Z telocvične počuť piskot tenisiek, výkriky hráčov a trénera.

**KIKO:** Okay, teraz nacvičujú slalom s loptou. Marek si vyhŕňa tričko... pekáč buchiet, nice...

Bety, Veronika a Eva lašujú po skrinkách.

**BETY:** Máte niečo? Akýkoľvek mobil.

Zrazu sa otvoria šatňové dvere a vojde do nich Sára. Bety, Veronika, Eva aj Kiko sú prekvapení, že ju tam vidia. Sára sebavedomo pohodí hlavou.

**SÁRA:** Čo čumíte? Nie ste jediné koho zaujíma pravda a prišla som vám dokázať, že ju nemáte.

Sára podíde ku jednej zo skriniek a znechutene k nej pričuchne.

**SÁRA:** Aj keď sa kvôli tomu budem musieť hrabať v cudzích smradľavých handrách.

**VERONIKA:** Tak si švihni. A buď potichu.

Sára znechutene otvorí prvú skrinku a začne sa v nej hrabať. Medzitým však Eva ohlási úspech a vyberie mobil.

**EVA:** Bingo!

Podá mobil Bety. Tá ho vezme, snaží sa ho zapnúť, ale nedarí sa jej.

**BETY:** Vyzerá byť vybitý.

**VERONIKA:** Nemáme čas, skúsme niekoho iného.

Bety zo Sebovej skrinky vyberie mobil. Tento sa hneď zapne, ale pýta PIN kód. Bety vyťuká štyri nuly, ale neodomkne sa. Potom skúsi štyri deviatky. Nič.

**BETY:** Netušíte, aký môže mať Sebo PIN?

Veronika sa pohŕdavo pozrie na teamovú selfie fotku nalepenú na stene vedľa dverí. Bety sa usmeje, niečo jej napadlo. Zadá dvakrát číslo Sebiho dresu: 5656. Telefón sa odokmne.

**BETY:** /hrdo/ Jednoduchý chlapec.

Baby sa zhŕknu pred Sebiho skrinkou, aj Kiko pribehne a hľadajú v telefóne DC-čko. Bety drží telefón a hľadá, Kiko sa obzerá, stráži popritom dvere do telocvične, všetci sú v napätí.

**BETY:** Dc-čko, aha, má ho tu.

**VERONIKA:** Dúfam, že má zapamätané heslo.

**BETY:** Má. Sme tam, aha. Kanál Blackstone&sluts.

Obrazovka telefónu blikne. Sára zažmurká, akoby neverila vlastným očiam a Bety sa pozrie na Veroniku. V tajnom kanáli (mal by vyzerať ako whatsap, čiže fotky s lajkami a komentármi, vystriedané so správami) medzi fotkami je aj tá s Evou, a samozrejme aj fotka s Veronikou, pri ktorej je komentár „nová baba“ a priradených osem bodov a rôzne emotikony vyjadrujúce obdiv a pobavenie.

**EVA:** Nechuťáci.

Bety ďalej scrolluje. Sú tam aj mená a fotky ďalších dievčat s basketbalistami. Ako sa Bety posúva prstom na staršie záznamy, nájde fotku svojej sestry Sofie s Jakubom a pritom tri body. (O tejto fotke doteraz nikto nevedel.) Sára je v šoku, nechápe to, nechce tomu uveriť.

**SÁRA:** Wtf? To nie. Jakub by toto nikdy neurobil.

Sára od nich ustúpi a kýve hlavou, nechce informáciu prijať. V Bety to vrie, má čo robiť, aby nevybuchla. Čím dlhšie sa na tie záznamy pozerá, tým viac v nej stúpa hnev.

**BETY:** /nahlas/ Hajzli!

Podá telefón Veronike a od nervov zatína zuby.

**BETY:** Ako môže byť niekto takýto nechutný perverzák?

Veronika okamžite vyberie svoj telefón a robí si fotky celého kanálu, aby mali dôkaz.

**VERONIKA:** Teraz máme s čím pracovať."""

    desc = scene.get("desc", "")
    if "### ORIGINÁLNY SCENÁR" not in desc:
        desc = desc.rstrip() + "\n\n" + original_script
    desc = desc.replace("**DIEL:** 01  |  **OBRAZ:** 28", "**DIEL:** 03  |  **OBRAZ:** 28")
    updated_scene = trello_put_body("/cards/p1WdZ1MD", {
        "name": "[TEST 2] 03/28. INT. ŠKOLA — CHLAPČENSKÁ ŠATŇA, DEŇ",
        "desc": desc,
    })

    updated_todos = []
    for card_id in ("7FfRrfYt", "VKhWF92J"):
        card = trello_get(f"/cards/{card_id}", {"fields": "desc,shortUrl,name"})
        todo_desc = card.get("desc", "").replace("**SÚVISIACI OBRAZ:** 01/28", "**SÚVISIACI OBRAZ:** 03/28")
        updated_todos.append(trello_put_body(f"/cards/{card_id}", {"desc": todo_desc}))

    return jsonify({
        "status": "updated",
        "scene": {"name": updated_scene["name"], "url": updated_scene["shortUrl"]},
        "todos_updated": len(updated_todos),
    })


@app.route("/api/test-dok4-schedule-on-riverdale", methods=["POST"])
def test_dok4_schedule_on_riverdale():
    return jsonify({"error": "schedule test endpoint disabled"}), 410

    if request.headers.get("X-Test-Key") != "dok4-schedule-riverdale-93b6d120":
        return jsonify({"error": "forbidden"}), 403

    board_id = trello_get("/boards/CzuD55PR", {"fields": "id,name"})["id"]
    schedule = [
        {
            "scene_id": "02/35", "date": "2026-05-27", "day": 1, "order": 1,
            "location": "NEMOCNICA - KANCELÁRIA RIADITEĽA", "setting": "INT/DEŇ",
            "story": "Júlia má návrh, ako nastaviť prijímanie pacientov lepšie.",
            "characters": "Júlia, Tibor",
        },
        {
            "scene_id": "03/41", "date": "2026-05-27", "day": 1, "order": 2,
            "location": "NEMOCNICA - KANCELÁRIA RIADITEĽA", "setting": "INT/DEŇ",
            "story": "Júlia obhajuje Andreja pred riaditeľom; prestriháva sa s ďalším obrazom.",
            "characters": "Júlia, Tibor",
        },
        {
            "scene_id": "01/55L", "date": "2026-05-27", "day": 1, "order": 3,
            "location": "NEMOCNICA - KANCELÁRIA PRIMÁRA", "setting": "INT/DEŇ",
            "story": "Júlia presviedča Martinu.", "characters": "Júlia",
        },
        {
            "scene_id": "02/12", "date": "2026-05-29", "day": 2, "order": 1,
            "location": "NEMOCNICA - LEKÁRSKA MIESTNOSŤ", "setting": "INT/DEŇ",
            "story": "Martina a Matej prichádzajú postupne k spolupráci.",
            "characters": "Matej, Martina, Oliver",
        },
        {
            "scene_id": "04/20", "date": "2026-05-30", "day": 3, "order": 1,
            "location": "NEMOCNICA - LEKÁRSKA MIESTNOSŤ", "setting": "INT/DEŇ",
            "story": "Linda zisťuje, prečo chce Matej robiť obvodného lekára.",
            "characters": "Matej, Linda",
        },
    ]

    board_lists = trello_get(f"/boards/{board_id}/lists", {"fields": "name,closed"})
    lists_by_name = {item["name"]: item for item in board_lists if not item.get("closed")}

    def ensure_list(name):
        if name not in lists_by_name:
            lists_by_name[name] = trello_post_body("/lists", {
                "idBoard": board_id, "name": name, "pos": "bottom"
            })
        return lists_by_name[name]

    unscheduled = ensure_list("TEST DÁTUMY — NEZARADENÉ")
    target_lists = {
        "2026-05-27": ensure_list("TEST DÁTUMY — DEŇ 01 — 27. 5. 2026"),
        "2026-05-29": ensure_list("TEST DÁTUMY — DEŇ 02 — 29. 5. 2026"),
        "2026-05-30": ensure_list("TEST DÁTUMY — DEŇ 03 — 30. 5. 2026"),
    }

    board_labels = trello_get(f"/boards/{board_id}/labels", {"fields": "name,color", "limit": 1000})
    test_label = next((x for x in board_labels if x.get("name", "").casefold() == "test dátumy".casefold()), None)
    if not test_label:
        test_label = trello_post_body("/labels", {
            "idBoard": board_id, "name": "TEST DÁTUMY", "color": "sky"
        })

    all_existing = []
    for item in (unscheduled, *target_lists.values()):
        all_existing.extend(trello_get(f"/lists/{item['id']}/cards", {
            "fields": "name,desc,shortUrl,idList,due,pos", "limit": 100
        }))
    existing_by_id = {}
    for card in all_existing:
        match = re.search(r"\[TEST DÁTUMY\]\s+([0-9]{2}/[0-9]+[A-Z]*)", card.get("name", ""))
        if match:
            existing_by_id[match.group(1)] = card

    results = []
    for row in schedule:
        scene_id = row["scene_id"]
        name = f"[TEST DÁTUMY] {scene_id} — {row['location']} — {row['setting']}"
        desc = (
            f"**STABILNÉ ID:** {scene_id}\n"
            f"**ZDROJ:** predbežné dispo DOK 4 z 18. 7. 2026\n"
            f"**NATÁČACÍ DEŇ:** {row['day']}\n"
            f"**DÁTUM NATÁČANIA:** {row['date']}\n"
            f"**PORADIE DŇA:** {row['order']}\n"
            f"**UNIT:** 1st unit\n"
            f"**LOKÁCIA:** {row['location']}\n"
            f"**POSTAVY:** {row['characters']}\n\n"
            f"### DEJ\n{row['story']}\n\n"
            "### TEST SYNCHRONIZÁCIE\n"
            "Karta bola najprv vytvorená ako nezaradená a následne spárovaná podľa stabilného ID, "
            "nadátovaná a presunutá do zoznamu natáčacieho dňa. Nástenka DOK 4 nebola zmenená."
        )
        created = False
        card = existing_by_id.get(scene_id)
        if not card:
            card = trello_post_body("/cards", {
                "idList": unscheduled["id"], "name": name, "desc": desc,
                "idLabels": test_label["id"], "pos": "bottom",
            })
            created = True
        due = f"{row['date']}T06:00:00.000Z"
        target = target_lists[row["date"]]
        card = trello_put_body(f"/cards/{card['id']}", {
            "name": name, "desc": desc, "due": due, "idList": target["id"],
            "pos": row["order"] * 16384,
        })
        trello_post_body(f"/cards/{card['id']}/actions/comments", {
            "text": (
                f"[TEST IMPORTU] Spárované podľa ID {scene_id}. Dátum: {row['date']}, "
                f"natáčací deň: {row['day']}, poradie: {row['order']}. DOK 4 bez zásahu."
            )
        })
        results.append({
            "scene_id": scene_id, "created": created, "date": row["date"],
            "day": row["day"], "order": row["order"], "list": target["name"],
            "url": card["shortUrl"],
        })

    return jsonify({
        "status": "tested", "source_board_modified": False,
        "target_board": "RIVERDALE", "matched": len(results), "cards": results,
    })


@app.route("/api/sync-dok4-schedule-metadata", methods=["POST"])
def sync_dok4_schedule_metadata():
    return jsonify({"error": "schedule metadata endpoint disabled"}), 410

    if request.headers.get("X-Sync-Key") != "dok4-metadata-20260718-a7c53e91":
        return jsonify({"error": "forbidden"}), 403

    schedule_path = os.path.join(os.path.dirname(__file__), "dok4_schedule_2026-07-18.json")
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_data = json.load(handle)
    schedule_rows = schedule_data["rows"]

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name,url"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    open_lists = {item["id"]: item["name"] for item in board_lists if not item.get("closed")}
    cards = []
    for list_id in open_lists:
        cards.extend(trello_get(f"/lists/{list_id}/cards", {
            "fields": "id,name,desc,idList,closed,shortUrl", "filter": "open", "limit": 1000
        }))

    cards_by_scene = {}
    for card in cards:
        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
        if match:
            scene_id = normalize_scene_id(match.group(1), match.group(2))
            cards_by_scene.setdefault(scene_id, []).append(card)

    row_by_scene = {row["scene_id"]: row for row in schedule_rows}
    matched = []
    missing = []
    duplicate_scene_ids = []
    for scene_id, row in row_by_scene.items():
        candidates = cards_by_scene.get(scene_id, [])
        if not candidates:
            missing.append(scene_id)
        else:
            if len(candidates) > 1:
                duplicate_scene_ids.append({
                "scene_id": scene_id,
                "cards": [{"name": c["name"], "list": open_lists.get(c["idList"]), "url": c["shortUrl"]} for c in candidates],
            })
            for card in candidates:
                matched.append({"row": row, "card": card})

    mode = request.args.get("mode", "dry-run")
    if mode != "apply":
        list_counts = {}
        metadata_present = 0
        metadata_correct = 0
        for item in matched:
            list_name = open_lists.get(item["card"]["idList"], "UNKNOWN")
            list_counts[list_name] = list_counts.get(list_name, 0) + 1
            desc = item["card"].get("desc", "")
            row = item["row"]
            if "<!-- DOK4-SCHEDULE-METADATA:START -->" in desc and "<!-- DOK4-SCHEDULE-METADATA:END -->" in desc:
                metadata_present += 1
                required = (
                    f"**ČÍSLO OBRAZU:** {row['scene_id']}",
                    "**ZDROJ:** predbežné dispo DOK 4 z 18. 7. 2026",
                    f"**NATÁČACÍ DEŇ:** {row['shooting_day']}",
                    f"**DÁTUM NATÁČANIA:** {row['shooting_date']}",
                    f"**PORADIE DŇA:** {row['order']}",
                    f"**UNIT:** {row['unit']}",
                    f"**LOKÁCIA:** {row['location']}",
                    f"**POSTAVY:** {row['characters']}",
                )
                if all(value in desc for value in required):
                    metadata_correct += 1
        return jsonify({
            "status": "dry-run",
            "board": board["name"],
            "schedule_rows": len(schedule_rows),
            "board_open_cards": len(cards),
            "matched_unique": len(matched),
            "missing_count": len(missing),
            "missing_sample": missing[:40],
            "matched_scene_ids": len(schedule_rows) - len(missing),
            "duplicate_scene_ids_count": len(duplicate_scene_ids),
            "duplicate_scene_ids_sample": duplicate_scene_ids[:15],
            "metadata_present": metadata_present,
            "metadata_correct": metadata_correct,
            "metadata_incorrect_or_missing": len(matched) - metadata_correct,
            "matched_by_list": list_counts,
            "sample": [{
                "scene_id": item["row"]["scene_id"],
                "card": item["card"]["name"],
                "list": open_lists.get(item["card"]["idList"]),
                "date": item["row"]["shooting_date"],
                "day": item["row"]["shooting_day"],
                "order": item["row"]["order"],
            } for item in matched[:20]],
        })

    start_marker = "<!-- DOK4-SCHEDULE-METADATA:START -->"
    end_marker = "<!-- DOK4-SCHEDULE-METADATA:END -->"
    batch_start = max(0, int(request.args.get("start", "0")))
    batch_limit = min(75, max(1, int(request.args.get("limit", "40"))))
    batch = matched[batch_start:batch_start + batch_limit]
    updated = []
    unchanged = 0
    moved = []
    errors = []
    for item in batch:
        row = item["row"]
        card = item["card"]
        metadata = (
            f"{start_marker}\n"
            f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
            f"**ZDROJ:** predbežné dispo DOK 4 z 18. 7. 2026\n"
            f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
            f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
            f"**PORADIE DŇA:** {row['order']}\n"
            f"**UNIT:** {row['unit']}\n"
            f"**LOKÁCIA:** {row['location']}\n"
            f"**POSTAVY:** {row['characters']}\n"
            f"{end_marker}"
        )
        old_desc = card.get("desc", "")
        if start_marker in old_desc and end_marker in old_desc:
            pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
            new_desc = re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
        else:
            new_desc = metadata + ("\n\n" + old_desc if old_desc else "")
        if new_desc == old_desc:
            unchanged += 1
            continue
        try:
            result = trello_put_body(f"/cards/{card['id']}", {"desc": new_desc})
            if result.get("idList") != card.get("idList"):
                moved.append({"scene_id": row["scene_id"], "card": card["shortUrl"]})
            updated.append({
                "scene_id": row["scene_id"], "url": result["shortUrl"],
                "list": open_lists.get(result.get("idList")),
            })
        except Exception as exc:
            errors.append({"scene_id": row["scene_id"], "error": str(exc)})

    return jsonify({
        "status": "applied",
        "board": board["name"],
        "matched_unique": len(matched),
        "batch_start": batch_start,
        "batch_size": len(batch),
        "batch_limit": batch_limit,
        "remaining": max(0, len(matched) - batch_start - len(batch)),
        "updated": len(updated),
        "unchanged": unchanged,
        "missing_count": len(missing),
        "matched_scene_ids": len(schedule_rows) - len(missing),
        "duplicate_scene_ids_count": len(duplicate_scene_ids),
        "moved_count": len(moved),
        "moved": moved[:20],
        "errors_count": len(errors),
        "errors": errors[:30],
        "updated_sample": updated[:20],
    })


@app.route("/api/sync-dok4-due-dates", methods=["POST"])
def sync_dok4_due_dates():
    return jsonify({"error": "due date endpoint disabled"}), 410

    if request.headers.get("X-Sync-Key") != "dok4-due-20260718-43f98b2e":
        return jsonify({"error": "forbidden"}), 403

    schedule_path = os.path.join(os.path.dirname(__file__), "dok4_schedule_2026-07-18.json")
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_rows = json.load(handle)["rows"]
    row_by_scene = {row["scene_id"]: row for row in schedule_rows}

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    open_lists = {item["id"]: item["name"] for item in board_lists if not item.get("closed")}
    cards = []
    for list_id in open_lists:
        cards.extend(trello_get(f"/lists/{list_id}/cards", {
            "fields": "id,name,idList,shortUrl,due,dueComplete", "filter": "open", "limit": 1000
        }))

    matched = []
    for card in cards:
        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
        if not match:
            continue
        scene_id = normalize_scene_id(match.group(1), match.group(2))
        row = row_by_scene.get(scene_id)
        if row:
            matched.append({"scene_id": scene_id, "row": row, "card": card})

    no_due = []
    same_due = []
    different_due = []
    for item in matched:
        current = item["card"].get("due")
        expected = item["row"]["shooting_date"]
        summary = {
            "scene_id": item["scene_id"], "name": item["card"]["name"],
            "list": open_lists.get(item["card"]["idList"]),
            "url": item["card"]["shortUrl"], "current_due": current,
            "expected_date": expected, "due_complete": item["card"].get("dueComplete"),
        }
        if not current:
            no_due.append(summary)
        elif current[:10] == expected:
            same_due.append(summary)
        else:
            different_due.append(summary)

    mode = request.args.get("mode", "dry-run")
    if mode != "apply":
        return jsonify({
            "status": "dry-run", "board": board["name"],
            "matched_cards": len(matched), "without_due": len(no_due),
            "same_due": len(same_due), "different_due": len(different_due),
            "different_due_sample": different_due[:30],
            "without_due_sample": no_due[:20],
        })

    batch_start = max(0, int(request.args.get("start", "0")))
    batch_limit = min(75, max(1, int(request.args.get("limit", "40"))))
    overwrite = request.args.get("overwrite", "0") == "1"
    batch = matched[batch_start:batch_start + batch_limit]
    updated = []
    unchanged = 0
    conflicts_skipped = []
    moved = []
    errors = []
    for item in batch:
        card = item["card"]
        expected_date = item["row"]["shooting_date"]
        current_due = card.get("due")
        if current_due and current_due[:10] == expected_date:
            unchanged += 1
            continue
        if current_due and not overwrite:
            conflicts_skipped.append({
                "scene_id": item["scene_id"], "url": card["shortUrl"],
                "current_due": current_due, "expected_date": expected_date,
            })
            continue
        try:
            result = trello_put_body(f"/cards/{card['id']}", {
                "due": f"{expected_date}T10:00:00.000Z"
            })
            if result.get("idList") != card.get("idList"):
                moved.append({"scene_id": item["scene_id"], "url": card["shortUrl"]})
            updated.append({
                "scene_id": item["scene_id"], "date": expected_date,
                "url": result["shortUrl"], "list": open_lists.get(result.get("idList")),
            })
        except Exception as exc:
            errors.append({"scene_id": item["scene_id"], "error": str(exc)})

    return jsonify({
        "status": "applied", "matched_cards": len(matched),
        "batch_start": batch_start, "batch_size": len(batch),
        "remaining": max(0, len(matched) - batch_start - len(batch)),
        "updated": len(updated), "unchanged": unchanged,
        "conflicts_skipped_count": len(conflicts_skipped),
        "conflicts_skipped": conflicts_skipped[:20],
        "errors_count": len(errors), "errors": errors[:20],
        "moved_count": len(moved), "moved": moved[:20],
        "updated_sample": updated[:20],
    })


@app.route("/api/prepare-dok4-next-7-days", methods=["POST"])
def prepare_dok4_next_7_days():
    return jsonify({"error": "next-seven-days endpoint disabled"}), 410

    if request.headers.get("X-Sync-Key") != "dok4-next7-20260719-25-f5a2c813":
        return jsonify({"error": "forbidden"}), 403

    window_start = "2026-07-19"
    window_end = "2026-07-25"
    schedule_path = os.path.join(os.path.dirname(__file__), "dok4_schedule_2026-07-18.json")
    with open(schedule_path, "r", encoding="utf-8") as handle:
        all_rows = json.load(handle)["rows"]
    rows = [row for row in all_rows if window_start <= row["shooting_date"] <= window_end]
    row_by_scene = {row["scene_id"]: row for row in rows}

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    open_lists = {item["id"]: item for item in board_lists if not item.get("closed")}
    lists_by_name = {item["name"]: item for item in open_lists.values()}

    def target_name(date_text):
        year, month, day = (int(part) for part in date_text.split("-"))
        return f"{day}.{month}."

    shooting_dates = sorted({row["shooting_date"] for row in rows})
    target_names = {date_text: target_name(date_text) for date_text in shooting_dates}
    missing_lists = [name for name in target_names.values() if name not in lists_by_name]

    cards = []
    for list_id in open_lists:
        cards.extend(trello_get(f"/lists/{list_id}/cards", {
            "fields": "id,name,idList,shortUrl,due,dueComplete,pos", "filter": "open", "limit": 1000
        }))
    cards_by_scene = {}
    for card in cards:
        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
        if match:
            scene_id = normalize_scene_id(match.group(1), match.group(2))
            if scene_id in row_by_scene:
                cards_by_scene.setdefault(scene_id, []).append(card)

    missing_cards = []
    planned = []
    protected_shot = []
    duplicates = []
    for row in rows:
        candidates = cards_by_scene.get(row["scene_id"], [])
        if not candidates:
            missing_cards.append(row["scene_id"])
            continue
        if len(candidates) > 1:
            duplicates.append({
                "scene_id": row["scene_id"],
                "cards": [{"url": c["shortUrl"], "list": open_lists.get(c["idList"], {}).get("name")} for c in candidates],
            })
        for card in candidates:
            current_list = open_lists.get(card["idList"], {}).get("name")
            item = {
                "row": row, "card": card, "current_list": current_list,
                "target_list": target_names[row["shooting_date"]],
            }
            if current_list == "NATOČENÉ OBRAZY":
                protected_shot.append({
                    "scene_id": row["scene_id"], "date": row["shooting_date"],
                    "url": card["shortUrl"], "list": current_list,
                })
            else:
                planned.append(item)

    already_correct = [item for item in planned if item["current_list"] == item["target_list"]]
    to_move = [item for item in planned if item["current_list"] != item["target_list"]]
    mode = request.args.get("mode", "dry-run")
    if mode != "apply":
        by_date = {}
        for row in rows:
            info = by_date.setdefault(row["shooting_date"], {
                "target_list": target_names[row["shooting_date"]], "schedule_rows": 0,
                "cards_found": 0, "already_correct": 0, "to_move": 0, "protected_shot": 0,
            })
            info["schedule_rows"] += 1
        for item in planned:
            info = by_date[item["row"]["shooting_date"]]
            info["cards_found"] += 1
            info["already_correct" if item["current_list"] == item["target_list"] else "to_move"] += 1
        for item in protected_shot:
            by_date[item["date"]]["protected_shot"] += 1
        return jsonify({
            "status": "dry-run", "board": board["name"],
            "window_start": window_start, "window_end": window_end,
            "shooting_dates": shooting_dates, "days_without_shooting": 7 - len(shooting_dates),
            "schedule_rows": len(rows), "cards_plannable": len(planned),
            "already_correct": len(already_correct), "to_move": len(to_move),
            "protected_shot_count": len(protected_shot), "protected_shot": protected_shot[:30],
            "missing_cards_count": len(missing_cards), "missing_cards": missing_cards,
            "duplicate_scene_ids_count": len(duplicates), "duplicates": duplicates[:20],
            "missing_lists": missing_lists, "by_date": by_date,
            "move_sample": [{
                "scene_id": item["row"]["scene_id"], "date": item["row"]["shooting_date"],
                "order": item["row"]["order"], "from": item["current_list"],
                "to": item["target_list"], "url": item["card"]["shortUrl"],
            } for item in to_move[:30]],
        })

    for date_text, name in target_names.items():
        if name not in lists_by_name:
            created = trello_post_body("/lists", {"idBoard": board["id"], "name": name, "pos": "bottom"})
            lists_by_name[name] = created

    moved = []
    reordered = []
    errors = []
    for item in sorted(planned, key=lambda value: (value["row"]["shooting_date"], value["row"]["order"])):
        row = item["row"]
        card = item["card"]
        target = lists_by_name[item["target_list"]]
        update = {"pos": row["order"] * 16384}
        if card["idList"] != target["id"]:
            update["idList"] = target["id"]
        try:
            result = trello_put_body(f"/cards/{card['id']}", update)
            entry = {
                "scene_id": row["scene_id"], "date": row["shooting_date"],
                "order": row["order"], "url": result["shortUrl"],
                "list": lists_by_name[item["target_list"]]["name"],
            }
            if "idList" in update:
                moved.append(entry)
            else:
                reordered.append(entry)
        except Exception as exc:
            errors.append({"scene_id": row["scene_id"], "error": str(exc)})

    return jsonify({
        "status": "applied", "window_start": window_start, "window_end": window_end,
        "shooting_dates": shooting_dates, "lists_created": missing_lists,
        "moved_count": len(moved), "reordered_count": len(reordered),
        "protected_shot_count": len(protected_shot), "missing_cards_count": len(missing_cards),
        "errors_count": len(errors), "errors": errors[:30],
        "moved": moved, "reordered": reordered,
    })


@app.route("/api/repair-dok4-zero-padded-scenes", methods=["POST"])
def repair_dok4_zero_padded_scenes():
    return jsonify({"error": "zero-padding repair endpoint disabled"}), 410

    if request.headers.get("X-Sync-Key") != "dok4-zero-padding-7d9a4f21":
        return jsonify({"error": "forbidden"}), 403

    missing_ids = {
        "08/8", "08/5", "08/3", "08/4", "05/1", "05/4", "08/6",
        "08/2", "07/39", "04/43B", "05/5", "09/7", "09/3", "09/16A",
    }
    schedule_path = os.path.join(os.path.dirname(__file__), "dok4_schedule_2026-07-18.json")
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_rows = json.load(handle)["rows"]
    rows = {row["scene_id"]: row for row in schedule_rows if row["scene_id"] in missing_ids}

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    open_lists = {item["id"]: item for item in board_lists if not item.get("closed")}
    lists_by_name = {item["name"]: item for item in open_lists.values()}
    cards = []
    for list_id in open_lists:
        cards.extend(trello_get(f"/lists/{list_id}/cards", {
            "fields": "id,name,desc,idList,shortUrl,due,dueComplete,pos", "filter": "open", "limit": 1000
        }))

    found = []
    for card in cards:
        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
        if not match:
            continue
        scene_id = normalize_scene_id(match.group(1), match.group(2))
        if scene_id in rows:
            found.append({
                "scene_id": scene_id, "raw_id": f"{match.group(1)}/{match.group(2)}",
                "row": rows[scene_id], "card": card,
                "current_list": open_lists.get(card["idList"], {}).get("name"),
            })

    found_ids = {item["scene_id"] for item in found}
    still_missing = sorted(missing_ids - found_ids)
    duplicates = {}
    for item in found:
        duplicates.setdefault(item["scene_id"], []).append(item)
    duplicates = {key: value for key, value in duplicates.items() if len(value) > 1}

    def target_list_name(date_text):
        _, month, day = (int(value) for value in date_text.split("-"))
        return f"{day}.{month}."

    mode = request.args.get("mode", "dry-run")
    if mode != "apply":
        return jsonify({
            "status": "dry-run", "board": board["name"],
            "requested_ids": len(missing_ids), "found_cards": len(found),
            "found_scene_ids": len(found_ids), "still_missing": still_missing,
            "duplicate_scene_ids": sorted(duplicates),
            "matches": [{
                "scene_id": item["scene_id"], "raw_id": item["raw_id"],
                "date": item["row"]["shooting_date"], "order": item["row"]["order"],
                "from": item["current_list"],
                "to": target_list_name(item["row"]["shooting_date"]),
                "current_due": item["card"].get("due"), "url": item["card"]["shortUrl"],
            } for item in sorted(found, key=lambda value: (value["row"]["shooting_date"], value["row"]["order"]))],
        })

    start_marker = "<!-- DOK4-SCHEDULE-METADATA:START -->"
    end_marker = "<!-- DOK4-SCHEDULE-METADATA:END -->"
    updated = []
    protected_shot = []
    errors = []
    for item in sorted(found, key=lambda value: (value["row"]["shooting_date"], value["row"]["order"])):
        row = item["row"]
        card = item["card"]
        if item["current_list"] == "NATOČENÉ OBRAZY":
            protected_shot.append({"scene_id": item["scene_id"], "url": card["shortUrl"]})
            continue
        target_name = target_list_name(row["shooting_date"])
        target = lists_by_name.get(target_name)
        if not target:
            errors.append({"scene_id": item["scene_id"], "error": f"missing target list {target_name}"})
            continue
        metadata = (
            f"{start_marker}\n"
            f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
            f"**ZDROJ:** predbežné dispo DOK 4 z 18. 7. 2026\n"
            f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
            f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
            f"**PORADIE DŇA:** {row['order']}\n"
            f"**UNIT:** {row['unit']}\n"
            f"**LOKÁCIA:** {row['location']}\n"
            f"**POSTAVY:** {row['characters']}\n"
            f"{end_marker}"
        )
        old_desc = card.get("desc", "")
        if start_marker in old_desc and end_marker in old_desc:
            pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
            new_desc = re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
        else:
            new_desc = metadata + ("\n\n" + old_desc if old_desc else "")
        update = {
            "desc": new_desc, "due": f"{row['shooting_date']}T10:00:00.000Z",
            "idList": target["id"], "pos": row["order"] * 16384,
        }
        try:
            result = trello_put_body(f"/cards/{card['id']}", update)
            updated.append({
                "scene_id": item["scene_id"], "raw_id": item["raw_id"],
                "date": row["shooting_date"], "order": row["order"],
                "list": target_name, "url": result["shortUrl"],
            })
        except Exception as exc:
            errors.append({"scene_id": item["scene_id"], "error": str(exc)})

    return jsonify({
        "status": "applied", "found_cards": len(found), "updated_count": len(updated),
        "protected_shot_count": len(protected_shot), "protected_shot": protected_shot,
        "still_missing": still_missing, "errors_count": len(errors), "errors": errors,
        "updated": updated,
    })


@app.route("/api/repair-dok4-retake-base-scenes", methods=["POST"])
def repair_dok4_retake_base_scenes():
    return jsonify({"error": "retake fallback endpoint disabled"}), 410

    if request.headers.get("X-Sync-Key") != "dok4-retakes-43b-16a-61e8c20f":
        return jsonify({"error": "forbidden"}), 403

    fallback_map = {"04/43B": "04/43", "09/16A": "09/16"}
    schedule_path = os.path.join(os.path.dirname(__file__), "dok4_schedule_2026-07-18.json")
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_rows = json.load(handle)["rows"]
    rows = {row["scene_id"]: row for row in schedule_rows if row["scene_id"] in fallback_map}

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    open_lists = {item["id"]: item for item in board_lists if not item.get("closed")}
    lists_by_name = {item["name"]: item for item in open_lists.values()}
    cards_by_id = {}
    for list_id in open_lists:
        cards = trello_get(f"/lists/{list_id}/cards", {
            "fields": "id,name,desc,idList,shortUrl,due,dueComplete,pos", "filter": "open", "limit": 1000
        })
        for card in cards:
            match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
            if match:
                scene_id = normalize_scene_id(match.group(1), match.group(2))
                cards_by_id.setdefault(scene_id, []).append(card)

    matches = []
    missing = []
    for planned_id, base_id in fallback_map.items():
        candidates = cards_by_id.get(base_id, [])
        if not candidates:
            missing.append({"planned_id": planned_id, "base_id": base_id})
            continue
        for card in candidates:
            row = rows[planned_id]
            _, month, day = (int(value) for value in row["shooting_date"].split("-"))
            matches.append({
                "planned_id": planned_id, "base_id": base_id, "row": row, "card": card,
                "current_list": open_lists.get(card["idList"], {}).get("name"),
                "target_list": f"{day}.{month}.",
            })

    mode = request.args.get("mode", "dry-run")
    if mode != "apply":
        return jsonify({
            "status": "dry-run", "board": board["name"], "matches_count": len(matches),
            "missing": missing,
            "matches": [{
                "planned_id": item["planned_id"], "base_id": item["base_id"],
                "name": item["card"]["name"], "from": item["current_list"],
                "to": item["target_list"], "date": item["row"]["shooting_date"],
                "order": item["row"]["order"], "due": item["card"].get("due"),
                "due_complete": item["card"].get("dueComplete"), "url": item["card"]["shortUrl"],
            } for item in matches],
        })

    start_marker = "<!-- DOK4-SCHEDULE-METADATA:START -->"
    end_marker = "<!-- DOK4-SCHEDULE-METADATA:END -->"
    updated = []
    errors = []
    for item in matches:
        row = item["row"]
        card = item["card"]
        target = lists_by_name.get(item["target_list"])
        if not target:
            errors.append({"planned_id": item["planned_id"], "error": f"missing list {item['target_list']}"})
            continue
        metadata = (
            f"{start_marker}\n"
            f"**ČÍSLO OBRAZU:** {item['planned_id']}\n"
            f"**ZDROJ:** predbežné dispo DOK 4 z 18. 7. 2026\n"
            f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
            f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
            f"**PORADIE DŇA:** {row['order']}\n"
            f"**UNIT:** {row['unit']}\n"
            f"**LOKÁCIA:** {row['location']}\n"
            f"**POSTAVY:** {row['characters']}\n"
            f"{end_marker}"
        )
        old_desc = card.get("desc", "")
        if start_marker in old_desc and end_marker in old_desc:
            pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
            new_desc = re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
        else:
            new_desc = metadata + ("\n\n" + old_desc if old_desc else "")
        try:
            result = trello_put_body(f"/cards/{card['id']}", {
                "desc": new_desc, "due": f"{row['shooting_date']}T10:00:00.000Z",
                "dueComplete": "false", "idList": target["id"], "pos": row["order"] * 16384,
            })
            updated.append({
                "planned_id": item["planned_id"], "base_id": item["base_id"],
                "date": row["shooting_date"], "order": row["order"],
                "list": item["target_list"], "due_complete": result.get("dueComplete"),
                "url": result["shortUrl"],
            })
        except Exception as exc:
            errors.append({"planned_id": item["planned_id"], "error": str(exc)})

    return jsonify({
        "status": "applied", "updated_count": len(updated), "updated": updated,
        "errors_count": len(errors), "errors": errors, "missing": missing,
    })


@app.route("/api/find-dok4-scene-07-39", methods=["GET"])
def find_dok4_scene_07_39():
    return jsonify({"error": "scene locator endpoint disabled"}), 410

    if request.headers.get("X-Inspect-Key") != "dok4-find-07-39-31b7e5a4":
        return jsonify({"error": "forbidden"}), 403

    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name"})
    lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed", "filter": "all"})
    list_by_id = {item["id"]: item for item in lists}
    matches = []
    total_cards = 0
    pattern = re.compile(r"(?<![0-9])0?7\s*/\s*0*39(?![A-Z0-9])", re.I)
    for board_list in lists:
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,idList,closed,shortUrl,dateLastActivity", "filter": "all", "limit": 1000
        })
        total_cards += len(cards)
        for card in cards:
            if pattern.search(card.get("name", "")) or pattern.search(card.get("desc", "")):
                matches.append({
                    "id": card["id"], "name": card["name"], "url": card["shortUrl"],
                    "card_closed": card.get("closed"), "list": board_list["name"],
                    "list_closed": board_list.get("closed"),
                    "date_last_activity": card.get("dateLastActivity"),
                    "matched_name": bool(pattern.search(card.get("name", ""))),
                    "matched_desc": bool(pattern.search(card.get("desc", ""))),
                })

    search_result = trello_get("/search", {
        "query": "07/39", "idBoards": board["id"], "modelTypes": "cards",
        "cards_limit": 100, "card_fields": "name,closed,idList,shortUrl,dateLastActivity",
    })
    search_cards = []
    for card in search_result.get("cards", []):
        list_info = list_by_id.get(card.get("idList"), {})
        search_cards.append({
            "name": card.get("name"), "url": card.get("shortUrl"),
            "card_closed": card.get("closed"), "list": list_info.get("name"),
            "list_closed": list_info.get("closed"), "date_last_activity": card.get("dateLastActivity"),
        })

    actions = trello_get(f"/boards/{board['id']}/actions", {
        "filter": "all", "limit": 1000, "fields": "type,date,data"
    })
    matching_actions = []
    for action in actions:
        if pattern.search(json.dumps(action.get("data", {}), ensure_ascii=False)):
            matching_actions.append({
                "type": action.get("type"), "date": action.get("date"), "data": action.get("data"),
            })

    return jsonify({
        "board": board["name"], "lists_checked": len(lists), "cards_checked": total_cards,
        "matches": matches, "search_cards": search_cards,
        "matching_recent_actions": matching_actions[:100],
    })


@app.route("/api/split-dok4-scene-07-39", methods=["POST"])
def split_dok4_scene_07_39():
    return jsonify({"error": "scene split endpoint disabled"}), 410

    if request.headers.get("X-Sync-Key") != "dok4-split-07-39-84c6d2f1":
        return jsonify({"error": "forbidden"}), 403

    source = trello_get("/cards/HVWHmy1U", {
        "fields": "id,name,desc,idList,shortUrl,closed"
    })
    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    lists_by_name = {item["name"]: item for item in board_lists if not item.get("closed")}
    target = lists_by_name.get("23.7.")
    if not target:
        return jsonify({"error": "target list 23.7. missing"}), 409

    boundary = re.search(r"(?mi)^\*0?7/39\.[^\r\n]*\*\s*$", source.get("desc", ""))
    source_desc_after_split = source.get("desc", "")
    scene_text = None
    if boundary:
        source_desc_after_split = source["desc"][:boundary.start()].rstrip()
        scene_text = source["desc"][boundary.start():].strip()

    target_cards = trello_get(f"/lists/{target['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,due,closed", "filter": "all", "limit": 1000
    })
    existing = None
    for card in target_cards:
        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
        if match and normalize_scene_id(match.group(1), match.group(2)) == "07/39":
            existing = card
            break

    mode = request.args.get("mode", "dry-run")
    if mode != "apply":
        existing_details = None
        if existing:
            checklists = trello_get(f"/cards/{existing['id']}/checklists", {"fields": "name"})
            existing_details = {
                "name": existing["name"], "url": existing["shortUrl"],
                "due": existing.get("due"), "description_length": len(existing.get("desc", "")),
                "has_metadata": "<!-- DOK4-SCHEDULE-METADATA:START -->" in existing.get("desc", ""),
                "contains_dialogue_end": "Katarína si vydýchne" in existing.get("desc", ""),
                "checklists": [item["name"] for item in checklists],
            }
        return jsonify({
            "status": "dry-run", "source": {"name": source["name"], "url": source["shortUrl"]},
            "boundary_found": bool(boundary),
            "source_length_before": len(source.get("desc", "")),
            "source_length_after": len(source_desc_after_split),
            "scene_text_length": len(scene_text or ""),
            "scene_text_start": (scene_text or "")[:500],
            "scene_text_end": (scene_text or "")[-500:],
            "existing_target_card": existing_details,
            "target_list": target["name"],
        })

    if not scene_text and not existing:
        return jsonify({"error": "07/39 boundary not found and target card does not exist"}), 409

    metadata = (
        "<!-- DOK4-SCHEDULE-METADATA:START -->\n"
        "**ČÍSLO OBRAZU:** 07/39\n"
        "**ZDROJ:** predbežné dispo DOK 4 z 18. 7. 2026\n"
        "**NATÁČACÍ DEŇ:** 32\n"
        "**DÁTUM NATÁČANIA:** 2026-07-23\n"
        "**PORADIE DŇA:** 1\n"
        "**UNIT:** 1st unit\n"
        "**LOKÁCIA:** NEMOCNICA – KANCELÁRIA RICHARDA\n"
        "**POSTAVY:** Richard, Katarína\n"
        "<!-- DOK4-SCHEDULE-METADATA:END -->"
    )
    new_desc = metadata + "\n\n" + (scene_text or existing.get("desc", ""))
    card_name = "07/39. INT. NEMOCNICA - RECEPCIA, DEŇ 3 — KATARÍNA, RICHARD, KOMPARZ"

    created = False
    if existing:
        new_card = trello_put_body(f"/cards/{existing['id']}", {
            "name": card_name, "desc": new_desc, "due": "2026-07-23T10:00:00.000Z",
            "dueComplete": "false", "idList": target["id"], "pos": 16384,
        })
    else:
        new_card = trello_post_body("/cards", {
            "idList": target["id"], "name": card_name, "desc": new_desc,
            "due": "2026-07-23T10:00:00.000Z", "pos": 16384,
        })
        created = True
        for checklist_name in ("REKVIZITY", "Poznámky z porady", "Info z natáčania"):
            trello_post_body("/checklists", {"idCard": new_card["id"], "name": checklist_name})

    source_updated = False
    if boundary:
        trello_put_body(f"/cards/{source['id']}", {"desc": source_desc_after_split})
        source_updated = True

    return jsonify({
        "status": "applied", "created": created, "source_updated": source_updated,
        "source": {"name": source["name"], "url": source["shortUrl"]},
        "new_card": {"name": new_card["name"], "url": new_card["shortUrl"], "list": target["name"]},
        "scene_text_length": len(scene_text or ""),
    })


@app.route("/api/find-dunaj-board", methods=["GET"])
def find_dunaj_board():
    return jsonify({"error": "endpoint disabled"}), 410
    if request.headers.get("X-Inspect-Key") != "find-dunaj-board-6e20a4f9":
        return jsonify({"error": "forbidden"}), 403
    boards = trello_get("/members/me/boards", {
        "fields": "id,name,url,shortLink,closed", "filter": "open", "limit": 1000
    })
    matches = [board for board in boards if "dunaj" in board.get("name", "").casefold()]
    return jsonify({"matches": matches, "boards_checked": len(boards)})


@app.route("/api/sync-dunaj-schedule", methods=["POST"])
def sync_dunaj_schedule():
    return jsonify({"error": "endpoint disabled"}), 410
    if request.headers.get("X-Sync-Key") != DUNAJ_CURRENT_SCHEDULE_KEY:
        return jsonify({"error": "forbidden"}), 403

    as_of = request.args.get("as_of", DUNAJ_CURRENT_SCHEDULE_AS_OF)
    if as_of != DUNAJ_CURRENT_SCHEDULE_AS_OF:
        return jsonify({
            "error": "this one-off endpoint has a fixed as_of date",
            "expected_as_of": DUNAJ_CURRENT_SCHEDULE_AS_OF,
        }), 400
    schedule_path = os.path.join(
        os.path.dirname(__file__), DUNAJ_CURRENT_SCHEDULE_FILE
    )
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_document = json.load(handle)
    source_schedule_rows = schedule_document["rows"]
    if (
        schedule_document.get("source") != DUNAJ_CURRENT_SOURCE_LABEL
        or len(source_schedule_rows) != DUNAJ_CURRENT_SOURCE_ROWS
        or len({row.get("scene_id") for row in source_schedule_rows})
        != DUNAJ_CURRENT_SOURCE_ROWS
    ):
        return jsonify({"error": "schedule source validation failed"}), 409

    # Persistent user-approved canonicalization rules. The production cards use
    # FLASH in full and one combined 24/08 card for both A/B schedule rows.
    try:
        schedule_rows = canonicalize_dunaj_schedule_rows(source_schedule_rows)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    shooting_dates = sorted({
        row["shooting_date"] for row in schedule_rows
        if row["shooting_date"] >= as_of
    })[:7]
    shooting_date_set = set(shooting_dates)
    window_start = shooting_dates[0] if shooting_dates else None
    window_end = shooting_dates[-1] if shooting_dates else None
    row_by_scene = {row["scene_id"]: row for row in schedule_rows}

    board = trello_get("/boards/qCPeWA3e", {"fields": "id,name,url"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    open_lists = {item["id"]: item for item in board_lists if not item.get("closed")}
    lists_by_name = {item["name"]: item for item in open_lists.values()}
    series_list = lists_by_name.get("SERIA 15,16")
    shot_list = next((item for item in open_lists.values() if "NATOC" in "".join(
        char for char in unicodedata.normalize("NFKD", item["name"])
        if not unicodedata.combining(char)
    ).upper()), None)
    cards = []
    for list_id in open_lists:
        before = None
        seen_page_ends = set()
        while True:
            params = {
                "fields": "id,name,desc,idList,shortUrl,due,dueComplete,pos,closed",
                "filter": "open",
                "limit": 1000,
            }
            if before:
                params["before"] = before
            page = trello_get(f"/lists/{list_id}/cards", params)
            cards.extend(page)
            if len(page) < 1000:
                break
            page_end = page[-1]["id"]
            if page_end in seen_page_ends:
                return jsonify({"error": "Trello card pagination did not advance"}), 502
            seen_page_ends.add(page_end)
            before = page_end
    # Trello's `before` pages can overlap around list-position changes. Keep
    # one current copy of each physical card before matching scene numbers.
    cards = list({card["id"]: card for card in cards}.values())

    cards_by_scene = {}
    for card in cards:
        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
        if match:
            scene_id = normalize_scene_id(match.group(1), match.group(2))
            if scene_id:
                cards_by_scene.setdefault(scene_id, []).append(card)

    matched = []
    missing = []
    duplicate_ids = []
    fallback_matches = []
    for scene_id, row in row_by_scene.items():
        candidates = cards_by_scene.get(scene_id, [])
        matched_scene_id = scene_id
        fallback_match = False
        if not candidates:
            base_scene_id = re.sub(r"[A-Z]+$", "", scene_id, flags=re.I)
            if base_scene_id != scene_id:
                candidates = cards_by_scene.get(base_scene_id, [])
                matched_scene_id = base_scene_id
                fallback_match = bool(candidates)
        if not candidates:
            missing.append(scene_id)
        else:
            if len(candidates) > 1:
                duplicate_ids.append(scene_id)
            if fallback_match:
                fallback_matches.append({
                    "scene_id": scene_id,
                    "matched_scene_id": matched_scene_id,
                    "cards": [{"name": card["name"], "url": card["shortUrl"]} for card in candidates],
                })
            for card in candidates:
                matched.append({
                    "scene_id": scene_id, "row": row, "card": card,
                    "matched_scene_id": matched_scene_id, "fallback_match": fallback_match,
                })

    matched_scenes_by_card = {}
    for item in matched:
        matched_scenes_by_card.setdefault(item["card"]["id"], []).append(item["scene_id"])
    fallback_card_collisions = [
        {"card_id": card_id, "scene_ids": scene_ids}
        for card_id, scene_ids in matched_scenes_by_card.items() if len(scene_ids) > 1
    ]
    collision_card_ids = {
        item["card_id"] for item in fallback_card_collisions
    }
    matched_for_updates = [
        item for item in matched if item["card"]["id"] not in collision_card_ids
    ]

    window_rows = [
        row for row in schedule_rows
        if row["shooting_date"] in shooting_date_set
    ]
    window_missing = []
    window_duplicates = []
    window_cards = []
    for row in window_rows:
        candidates = cards_by_scene.get(row["scene_id"], [])
        matched_scene_id = row["scene_id"]
        fallback_match = False
        if not candidates:
            base_scene_id = re.sub(r"[A-Z]+$", "", row["scene_id"], flags=re.I)
            if base_scene_id != row["scene_id"]:
                candidates = cards_by_scene.get(base_scene_id, [])
                if not candidates:
                    search_result = trello_get("/search", {
                        "query": base_scene_id, "idBoards": board["id"],
                        "modelTypes": "cards", "cards_limit": 100,
                        "card_fields": "id,name,desc,idList,shortUrl,due,dueComplete,pos,closed",
                    })
                    candidates = []
                    for candidate in search_result.get("cards", []):
                        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", candidate.get("name", ""), re.I)
                        if match and normalize_scene_id(match.group(1), match.group(2)) == base_scene_id:
                            candidates.append(candidate)
                matched_scene_id = base_scene_id
                fallback_match = bool(candidates)
        if not candidates:
            window_missing.append(row["scene_id"])
        elif len(candidates) > 1:
            window_duplicates.append({
                "scene_id": row["scene_id"],
                "cards": [{"name": c["name"], "url": c["shortUrl"], "list": open_lists.get(c["idList"], {}).get("name")} for c in candidates],
            })
        else:
            window_cards.append({
                "row": row, "card": candidates[0],
                "matched_scene_id": matched_scene_id, "fallback_match": fallback_match,
            })

    def date_list_name(date_text):
        _, month, day = (int(part) for part in date_text.split("-"))
        return f"{day}.{month}."

    target_names = {date_text: date_list_name(date_text) for date_text in shooting_dates}
    missing_target_lists = [name for name in target_names.values() if name not in lists_by_name]

    nonwindow_groups = {}
    for item in matched:
        bucket = dunaj_schedule_bucket(item["row"]["shooting_date"], as_of, shooting_dates)
        if bucket != "active":
            nonwindow_groups.setdefault(item["card"]["id"], []).append({**item, "bucket": bucket})

    historical_actions = []
    future_actions = []
    history_target_collisions = []
    for card_id, items in nonwindow_groups.items():
        buckets = {item["bucket"] for item in items}
        if len(buckets) != 1:
            history_target_collisions.append({
                "card_id": card_id,
                "scene_ids": [item["row"]["scene_id"] for item in items],
                "buckets": sorted(buckets),
            })
            continue
        # One physical card can intentionally represent letter variants shot
        # on different dates. If every occurrence has the same destination,
        # reconcile the card once using the latest occurrence for reporting.
        item = sorted(items, key=lambda value: (
            value["row"]["shooting_date"], value["row"]["order"]
        ))[-1]
        card = item["card"]
        current_list = open_lists.get(card.get("idList"), {}).get("name")
        scene_ids = [value["row"]["scene_id"] for value in items]
        if item["bucket"] == "shot" and (
            not shot_list or card.get("idList") != shot_list["id"]
            or card.get("due") or card.get("dueComplete")
        ):
            historical_actions.append({**item, "current_list": current_list, "scene_ids": scene_ids})
        elif item["bucket"] == "series" and (
            not series_list or card.get("idList") != series_list["id"]
            or card.get("due") or card.get("dueComplete")
        ):
            future_actions.append({**item, "current_list": current_list, "scene_ids": scene_ids})

    expected_target_by_card_id = {
        item["card"]["id"]: target_names[item["row"]["shooting_date"]]
        for item in window_cards
    }
    matched_nonwindow_card_ids = {
        item["card"]["id"] for item in historical_actions + future_actions
    }
    stale_date_cards = []
    stale_by_list = {}
    for card in cards:
        current_list = open_lists.get(card["idList"], {}).get("name", "")
        if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.", current_list):
            continue
        scene_id = scene_id_from_card_name(card.get("name"))
        if (
            not scene_id
            or card["id"] in expected_target_by_card_id
            or card["id"] in matched_nonwindow_card_ids
        ):
            continue
        stale_date_cards.append({
            "id": card["id"], "scene_id": scene_id, "name": card["name"],
            "from": current_list, "to": "SERIA 15,16", "url": card["shortUrl"],
        })
        stale_by_list[current_list] = stale_by_list.get(current_list, 0) + 1

    window_pending_updates = []
    for item in window_cards:
        row = item["row"]
        card = item["card"]
        expected_list = target_names[row["shooting_date"]]
        expected_fragments = [
            f"**ČÍSLO OBRAZU:** {row['scene_id']}",
            f"**ZDROJ:** {DUNAJ_CURRENT_SOURCE_LABEL}",
            f"**NATÁČACÍ DEŇ:** {row['shooting_day']}",
            f"**DÁTUM NATÁČANIA:** {row['shooting_date']}",
            f"**PORADIE DŇA:** {row.get('order_display', row['order'])}",
            f"**UNIT:** {row['unit']}",
        ]
        fields = []
        if open_lists.get(card.get("idList"), {}).get("name") != expected_list:
            fields.append("list")
        expected_due_date = (
            row["shooting_date"] if row["shooting_date"] in shooting_date_set else ""
        )
        if (card.get("due") or "")[:10] != expected_due_date:
            fields.append("due")
        if any(fragment not in card.get("desc", "") for fragment in expected_fragments):
            fields.append("metadata")
        if card.get("dueComplete"):
            fields.append("dueComplete")
        if fields:
            window_pending_updates.append({
                "scene_id": row["scene_id"], "date": row["shooting_date"],
                "order": row["order"], "fields": fields, "url": card["shortUrl"],
            })

    start_marker = "<!-- DUNAJ-SCHEDULE-METADATA:START -->"
    end_marker = "<!-- DUNAJ-SCHEDULE-METADATA:END -->"

    def expected_schedule_description(card, row):
        metadata = (
            f"{start_marker}\n"
            f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
            f"**ZDROJ:** {DUNAJ_CURRENT_SOURCE_LABEL}\n"
            f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
            f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
            f"**PORADIE DŇA:** {row.get('order_display', row['order'])}\n"
            f"**UNIT:** {row['unit']}\n"
            f"**LOKÁCIA:** {row['location']}\n"
            f"**POSTAVY:** {row['characters']}\n"
            f"{end_marker}"
        )
        old_desc = card.get("desc", "")
        if start_marker in old_desc and end_marker in old_desc:
            pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
            return re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
        return metadata + ("\n\n" + old_desc if old_desc else "")

    metadata_pending_updates = []
    metadata_actionable = []
    for item in window_cards:
        row = item["row"]
        card = item["card"]
        fields = []
        if expected_schedule_description(card, row) != card.get("desc", ""):
            fields.append("metadata")
        if (card.get("due") or "")[:10] != row["shooting_date"]:
            fields.append("due")
        if fields:
            metadata_actionable.append(item)
            metadata_pending_updates.append({
                "scene_id": row["scene_id"], "fields": fields,
                "url": card["shortUrl"],
            })

    mode = request.args.get("mode", "dry-run")
    if mode not in {"dry-run", "apply-window", "cleanup-stale", "metadata", "reconcile-history"}:
        return jsonify({"error": "apply modes disabled pending dry-run approval"}), 409
    if mode == "dry-run":
        matched_by_list = {}
        for item in matched:
            name = open_lists.get(item["card"]["idList"], {}).get("name", "UNKNOWN")
            matched_by_list[name] = matched_by_list.get(name, 0) + 1
        window_by_date = {}
        for row in window_rows:
            window_by_date.setdefault(row["shooting_date"], {
                "target_list": target_names[row["shooting_date"]], "schedule_rows": 0,
                "cards_found_unique": 0, "already_correct": 0, "to_move": 0,
            })["schedule_rows"] += 1
        for item in window_cards:
            row = item["row"]
            current = open_lists.get(item["card"]["idList"], {}).get("name")
            info = window_by_date[row["shooting_date"]]
            info["cards_found_unique"] += 1
            info["already_correct" if current == target_names[row["shooting_date"]] else "to_move"] += 1
        return jsonify({
            "status": "dry-run", "board": board["name"], "board_url": board["url"],
            "schedule_file": DUNAJ_CURRENT_SCHEDULE_FILE,
            "source_schedule_rows": len(source_schedule_rows),
            "canonical_schedule_rows": len(schedule_rows),
            "open_lists": [item["name"] for item in open_lists.values()],
            "board_list_order": [item["name"] for item in open_lists.values()],
            "existing_date_lists": [
                item["name"] for item in open_lists.values()
                if re.fullmatch(r"\d{1,2}\.\d{1,2}\.", item["name"])
            ],
            "open_cards": len(cards), "schedule_rows": len(schedule_rows),
            "matched_scene_ids": len(schedule_rows) - len(missing), "matched_card_copies": len(matched),
            "missing_count": len(missing), "missing_sample": missing[:60],
            "duplicate_scene_ids_count": len(duplicate_ids), "duplicate_scene_ids_sample": duplicate_ids[:30],
            "fallback_matches_count": len(fallback_matches), "fallback_matches": fallback_matches,
            "fallback_card_collisions_count": len(fallback_card_collisions),
            "fallback_card_collisions": fallback_card_collisions,
            "matched_by_list": matched_by_list,
            "window_start": window_start, "window_end": window_end,
            "window_schedule_rows": len(window_rows), "window_unique_cards": len(window_cards),
            "window_missing_count": len(window_missing), "window_missing": window_missing,
            "window_duplicates_count": len(window_duplicates), "window_duplicates": window_duplicates[:20],
            "window_type": "next_shooting_days",
            "window_as_of": as_of,
            "shooting_dates": shooting_dates,
            "shooting_days_selected": len(shooting_dates),
            "missing_target_lists": missing_target_lists, "window_by_date": window_by_date,
            "stale_date_cards_count": len(stale_date_cards),
            "stale_date_cards_by_list": stale_by_list,
            "stale_date_cards": stale_date_cards,
            "window_pending_updates_count": len(window_pending_updates),
            "window_pending_updates": window_pending_updates,
            "metadata_due_pending_count": len(metadata_pending_updates),
            "historical_schedule_rows": sum(
                1 for row in schedule_rows if row["shooting_date"] < as_of
            ),
            "historical_to_shot_count": len(historical_actions),
            "historical_to_shot_sample": [{
                "scene_id": item["row"]["scene_id"],
                "date": item["row"]["shooting_date"],
                "from": item["current_list"], "to": "NATOČENÉ OBRAZY",
                "url": item["card"]["shortUrl"],
            } for item in historical_actions[:50]],
            "future_to_series_count": len(future_actions),
            "future_to_series_sample": [{
                "scene_id": item["row"]["scene_id"],
                "date": item["row"]["shooting_date"],
                "from": item["current_list"], "to": "SERIA 15,16",
                "url": item["card"]["shortUrl"],
            } for item in future_actions[:50]],
            "shot_list_found": bool(shot_list), "series_list_found": bool(series_list),
            "shot_list_name": shot_list["name"] if shot_list else None,
            "history_target_collisions_count": len(history_target_collisions),
            "history_target_collisions": history_target_collisions,
            "window_sample": [{
                "scene_id": item["row"]["scene_id"], "date": item["row"]["shooting_date"],
                "matched_scene_id": item["matched_scene_id"], "fallback_match": item["fallback_match"],
                "order": item["row"]["order"], "unit": item["row"]["unit"],
                "from": open_lists.get(item["card"]["idList"], {}).get("name"),
                "to": target_names[item["row"]["shooting_date"]], "url": item["card"]["shortUrl"],
            } for item in window_cards[:40]],
        })

    if mode == "reconcile-history":
        if history_target_collisions:
            return jsonify({
                "error": "history reconciliation blocked by conflicting destinations",
                "history_target_collisions": history_target_collisions,
            }), 409
        if historical_actions and not shot_list:
            return jsonify({"error": "NATOČENÉ OBRAZY list not found"}), 404
        if future_actions and not series_list:
            return jsonify({"error": "SERIA 15,16 list not found"}), 404
        actions = [
            {**item, "target": shot_list, "target_name": shot_list["name"]}
            for item in historical_actions
        ] + [
            {**item, "target": series_list, "target_name": "SERIA 15,16"}
            for item in future_actions
        ]
        actions.sort(key=lambda item: (
            item["row"]["shooting_date"], item["row"]["order"], item["row"]["scene_id"]
        ))
        start = max(0, int(request.args.get("start", "0")))
        limit = min(50, max(1, int(request.args.get("limit", "25"))))
        batch = actions[start:start + limit]
        updated = []; errors = []
        for item in batch:
            card = item["card"]
            try:
                result = trello_put_body(f"/cards/{card['id']}", {
                    "idList": item["target"]["id"], "pos": "bottom",
                    "due": "", "dueComplete": "false",
                })
                updated.append({
                    "scene_id": item["row"]["scene_id"], "scene_ids": item["scene_ids"],
                    "date": item["row"]["shooting_date"],
                    "from": item["current_list"], "to": item["target_name"],
                    "url": result["shortUrl"],
                })
            except Exception as exc:
                errors.append({"scene_id": item["row"]["scene_id"], "error": str(exc)})
        return jsonify({
            "status": "history-reconciled", "planned": len(actions),
            "batch": len(batch), "updated": len(updated),
            "errors_count": len(errors), "errors": errors,
            "remaining": max(0, len(actions) - start - len(batch)),
        })

    if mode == "apply-window":
        if (
            window_duplicates
            or len(window_cards) + len(window_missing) != len(window_rows)
        ):
            return jsonify({
                "error": "window verification failed",
                "window_rows": len(window_rows), "window_cards": len(window_cards),
                "missing": window_missing, "duplicates": window_duplicates,
            }), 409

        created_lists = []
        for date_text, name in target_names.items():
            if name not in lists_by_name:
                lists_by_name[name] = trello_post_body("/lists", {
                    "idBoard": board["id"], "name": name, "pos": "bottom",
                })
                created_lists.append(name)

        start_marker = "<!-- DUNAJ-SCHEDULE-METADATA:START -->"
        end_marker = "<!-- DUNAJ-SCHEDULE-METADATA:END -->"
        ordered_window_cards = sorted(window_cards, key=lambda value: (
            value["row"]["shooting_date"], value["row"]["order"]
        ))
        batch_start = max(0, int(request.args.get("start", "0")))
        batch_limit = min(15, max(1, int(request.args.get("limit", "12"))))
        batch = ordered_window_cards[batch_start:batch_start + batch_limit]
        remaining = max(0, len(ordered_window_cards) - batch_start - len(batch))
        updated = []
        moved = []
        errors = []
        for item in batch:
            row = item["row"]
            card = item["card"]
            target_name = target_names[row["shooting_date"]]
            target = lists_by_name[target_name]
            metadata = (
                f"{start_marker}\n"
                f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
                f"**ZDROJ:** {DUNAJ_CURRENT_SOURCE_LABEL}\n"
                f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
                f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
                f"**PORADIE DŇA:** {row.get('order_display', row['order'])}\n"
                f"**UNIT:** {row['unit']}\n"
                f"**LOKÁCIA:** {row['location']}\n"
                f"**POSTAVY:** {row['characters']}\n"
                f"{end_marker}"
            )
            old_desc = card.get("desc", "")
            if start_marker in old_desc and end_marker in old_desc:
                pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
                new_desc = re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
            else:
                new_desc = metadata + ("\n\n" + old_desc if old_desc else "")
            update = {
                "desc": new_desc,
                "due": f"{row['shooting_date']}T10:00:00.000Z",
                "idList": target["id"],
                "pos": row["order"] * 16384,
            }
            current_name = open_lists.get(card.get("idList"), {}).get("name", "")
            folded_current = unicodedata.normalize("NFKD", current_name)
            folded_current = "".join(
                char for char in folded_current if not unicodedata.combining(char)
            ).upper()
            if "NATOC" in folded_current or card.get("dueComplete"):
                update["dueComplete"] = "false"
            try:
                result = trello_put_body(f"/cards/{card['id']}", update)
                entry = {
                    "scene_id": row["scene_id"], "date": row["shooting_date"],
                    "order": row["order"], "list": target_name,
                    "url": result["shortUrl"],
                }
                updated.append(entry)
                if card.get("idList") != target["id"]:
                    moved.append(entry)
            except Exception as exc:
                errors.append({"scene_id": row["scene_id"], "error": str(exc)})

        list_reordered = None
        archived_old_lists = []
        retained_old_lists = []
        old_list_cleanup_errors = []
        list_order_updates = []
        list_order_errors = []
        if not errors and remaining == 0:
            ordered_lists = trello_get(f"/boards/{board['id']}/lists", {
                "fields": "id,name,pos,closed", "filter": "open",
            })
            ordered_lists.sort(key=lambda value: value["pos"])
            active_names = set(target_names.values())
            for old_list in ordered_lists:
                if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.", old_list["name"]):
                    continue
                if old_list["name"] in active_names:
                    continue
                try:
                    remaining_cards = trello_get(f"/lists/{old_list['id']}/cards", {
                        "fields": "id,name,shortUrl", "filter": "open", "limit": 1000,
                    })
                    if remaining_cards:
                        retained_old_lists.append({
                            "name": old_list["name"],
                            "remaining_cards": len(remaining_cards),
                            "cards": [{
                                "name": card["name"],
                                "url": card.get("shortUrl"),
                            } for card in remaining_cards],
                        })
                    else:
                        trello_put_body(
                            f"/lists/{old_list['id']}", {"closed": "true"}
                        )
                        archived_old_lists.append(old_list["name"])
                except Exception as exc:
                    old_list_cleanup_errors.append({
                        "name": old_list["name"], "error": str(exc),
                    })

            ordered_lists = trello_get(f"/boards/{board['id']}/lists", {
                "fields": "id,name,pos,closed", "filter": "open",
            })
            ordered_lists.sort(key=lambda value: value["pos"])
            anchor = next(
                (value for value in ordered_lists if value["name"] == "SERIA 15,16"),
                None,
            )
            date_lists = [
                value for value in ordered_lists if value["name"] in active_names
            ]
            date_lists.sort(key=lambda value: shooting_dates[
                list(target_names.values()).index(value["name"])
            ])
            if anchor:
                date_ids = {value["id"] for value in date_lists}
                following = [
                    value for value in ordered_lists
                    if value["id"] not in date_ids and value["pos"] > anchor["pos"]
                ]
                next_pos = following[0]["pos"] if following else anchor["pos"] + 131072
                step = (next_pos - anchor["pos"]) / (len(date_lists) + 1)
                for index, date_list in enumerate(date_lists, start=1):
                    try:
                        result = trello_put_body(
                            f"/lists/{date_list['id']}",
                            {"pos": anchor["pos"] + step * index},
                        )
                        list_order_updates.append({
                            "name": result["name"], "pos": result["pos"],
                        })
                    except Exception as exc:
                        list_order_errors.append({
                            "name": date_list["name"], "error": str(exc),
                        })

        return jsonify({
            "status": "window-applied", "board": board["name"],
            "window_rows": len(window_rows), "updated_count": len(updated),
            "missing_skipped": window_missing,
            "moved_count": len(moved), "created_lists": created_lists,
            "batch_start": batch_start, "batch_size": len(batch), "remaining": remaining,
            "list_reordered": list_reordered,
            "archived_old_lists": archived_old_lists,
            "retained_old_lists": retained_old_lists,
            "old_list_cleanup_errors_count": len(old_list_cleanup_errors),
            "old_list_cleanup_errors": old_list_cleanup_errors,
            "list_order_updates": list_order_updates,
            "list_order_errors_count": len(list_order_errors),
            "list_order_errors": list_order_errors,
            "errors_count": len(errors), "errors": errors,
        })

    if mode == "cleanup-stale":
        series_list = lists_by_name.get("SERIA 15,16")
        if not series_list:
            return jsonify({"error": "SERIA 15,16 list not found"}), 404
        moved = []
        errors = []
        batch_start = max(0, int(request.args.get("start", "0")))
        batch_limit = min(40, max(1, int(request.args.get("limit", "25"))))
        batch = stale_date_cards[batch_start:batch_start + batch_limit]
        for item in batch:
            try:
                result = trello_put_body(f"/cards/{item['id']}", {
                    "idList": series_list["id"], "pos": "bottom",
                    "due": "", "dueComplete": "false",
                })
                moved.append({
                    "scene_id": item["scene_id"], "from": item["from"],
                    "to": "SERIA 15,16", "url": result["shortUrl"],
                    "due_cleared": True,
                })
            except Exception as exc:
                errors.append({"scene_id": item["scene_id"], "error": str(exc)})
        return jsonify({
            "status": "stale-date-cards-cleaned", "board": board["name"],
            "planned_count": len(stale_date_cards), "moved_count": len(moved),
            "batch_start": batch_start, "batch_size": len(batch),
            "remaining": max(0, len(stale_date_cards) - batch_start - len(batch)),
            "errors_count": len(errors), "errors": errors, "moved": moved,
        })

    if mode == "metadata":
        batch_start = max(0, int(request.args.get("start", "0")))
        batch_limit = min(75, max(1, int(request.args.get("limit", "40"))))
        batch = metadata_actionable[batch_start:batch_start + batch_limit]
        start_marker = "<!-- DUNAJ-SCHEDULE-METADATA:START -->"
        end_marker = "<!-- DUNAJ-SCHEDULE-METADATA:END -->"
        updated = []; unchanged = 0; moved = []; errors = []
        for item in batch:
            row = item["row"]; card = item["card"]
            metadata = (
                f"{start_marker}\n"
                f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
                f"**ZDROJ:** {DUNAJ_CURRENT_SOURCE_LABEL}\n"
                f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
                f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
                f"**PORADIE DŇA:** {row.get('order_display', row['order'])}\n"
                f"**UNIT:** {row['unit']}\n"
                f"**LOKÁCIA:** {row['location']}\n"
                f"**POSTAVY:** {row['characters']}\n"
                f"{end_marker}"
            )
            old_desc = card.get("desc", "")
            if start_marker in old_desc and end_marker in old_desc:
                pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
                new_desc = re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
            else:
                new_desc = metadata + ("\n\n" + old_desc if old_desc else "")
            expected_due_date = (
                row["shooting_date"] if row["shooting_date"] in shooting_date_set else ""
            )
            expected_due = (
                f"{expected_due_date}T10:00:00.000Z" if expected_due_date else ""
            )
            if new_desc == old_desc and (card.get("due") or "")[:10] == expected_due_date:
                unchanged += 1; continue
            try:
                result = trello_put_body(f"/cards/{card['id']}", {"desc": new_desc, "due": expected_due})
                if result.get("idList") != card.get("idList"):
                    moved.append(row["scene_id"])
                updated.append(row["scene_id"])
            except Exception as exc:
                errors.append({"scene_id": row["scene_id"], "error": str(exc)})
        return jsonify({
            "status": "metadata-applied",
            "matched_card_copies": len(matched_for_updates),
            "metadata_actionable": len(metadata_actionable),
            "fallback_collisions_skipped": fallback_card_collisions,
            "batch_start": batch_start, "batch_size": len(batch),
            "remaining": max(0, len(metadata_actionable) - batch_start - len(batch)),
            "updated": len(updated), "unchanged": unchanged,
            "moved_count": len(moved), "errors_count": len(errors), "errors": errors[:20],
        })

    if mode == "window":
        for date_text, name in target_names.items():
            if name not in lists_by_name:
                lists_by_name[name] = trello_post_body("/lists", {
                    "idBoard": board["id"], "name": name, "pos": "bottom"
                })
        moved = []; reordered = []; errors = []
        for item in sorted(window_cards, key=lambda value: (value["row"]["shooting_date"], value["row"]["order"])):
            row = item["row"]; card = item["card"]
            target_name = target_names[row["shooting_date"]]; target = lists_by_name[target_name]
            update = {"pos": row["order"] * 16384}
            current_name = open_lists.get(card["idList"], {}).get("name")
            if card["idList"] != target["id"]:
                update["idList"] = target["id"]
            if card.get("closed"):
                update["closed"] = "false"
            if current_name == "NATOČENÉ OBRAZY" or card.get("dueComplete"):
                update["dueComplete"] = "false"
            if item["fallback_match"]:
                start_marker = "<!-- DUNAJ-SCHEDULE-METADATA:START -->"
                end_marker = "<!-- DUNAJ-SCHEDULE-METADATA:END -->"
                metadata = (
                    f"{start_marker}\n"
                    f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
                    f"**ZDROJ:** predbežná dispo DUNAJ 16 z 21. 7. 2026\n"
                    f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
                    f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
                    f"**PORADIE DŇA:** {row['order']}\n"
                    f"**UNIT:** {row['unit']}\n"
                    f"**LOKÁCIA:** {row['location']}\n"
                    f"**POSTAVY:** {row['characters']}\n"
                    f"{end_marker}"
                )
                old_desc = card.get("desc", "")
                if start_marker in old_desc and end_marker in old_desc:
                    pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
                    update["desc"] = re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
                else:
                    update["desc"] = metadata + ("\n\n" + old_desc if old_desc else "")
                update["due"] = f"{row['shooting_date']}T10:00:00.000Z"
            try:
                result = trello_put_body(f"/cards/{card['id']}", update)
                entry = {"scene_id": row["scene_id"], "date": row["shooting_date"], "order": row["order"], "list": target_name, "url": result["shortUrl"]}
                (moved if "idList" in update else reordered).append(entry)
            except Exception as exc:
                errors.append({"scene_id": row["scene_id"], "error": str(exc)})
        return jsonify({
            "status": "window-applied", "lists_created": missing_target_lists,
            "moved_count": len(moved), "reordered_count": len(reordered),
            "window_missing_count": len(window_missing), "window_duplicates_count": len(window_duplicates),
            "errors_count": len(errors), "errors": errors[:30], "moved": moved,
        })

    if mode == "create-missing-base":
        created = []
        for scene_id in window_missing:
            row = row_by_scene[scene_id]
            base_scene_id = re.sub(r"[A-Z]+$", "", scene_id, flags=re.I)
            if base_scene_id == scene_id or cards_by_scene.get(base_scene_id):
                continue
            target_name = target_names[row["shooting_date"]]
            target = lists_by_name.get(target_name)
            if not target:
                target = trello_post_body("/lists", {
                    "idBoard": board["id"], "name": target_name, "pos": "bottom"
                })
                lists_by_name[target_name] = target
            metadata = (
                "<!-- DUNAJ-SCHEDULE-METADATA:START -->\n"
                f"**ČÍSLO OBRAZU:** {scene_id}\n"
                f"**ZDROJ:** predbežná dispo DUNAJ 16 z 21. 7. 2026\n"
                f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
                f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
                f"**PORADIE DŇA:** {row['order']}\n"
                f"**UNIT:** {row['unit']}\n"
                f"**LOKÁCIA:** {row['location']}\n"
                f"**POSTAVY:** {row['characters']}\n"
                "<!-- DUNAJ-SCHEDULE-METADATA:END -->"
            )
            result = trello_post_body("/cards", {
                "idList": target["id"], "name": base_scene_id,
                "desc": metadata, "due": f"{row['shooting_date']}T10:00:00.000Z",
                "pos": row["order"] * 16384,
            })
            created.append({"scene_id": scene_id, "card_name": base_scene_id, "url": result["shortUrl"]})
        return jsonify({"status": "missing-base-created", "created": created, "created_count": len(created)})

    return jsonify({"error": "invalid mode"}), 400


@app.route("/api/inspect-dunaj-merged-scenes", methods=["POST"])
def inspect_dunaj_merged_scenes():
    return jsonify({"error": "completed one-off endpoint disabled"}), 410
    if request.headers.get("X-Sync-Key") != "dunaj-1516-schedule-21jul-6a4d02c9":
        return jsonify({"error": "forbidden"}), 403

    mode = request.args.get("mode", "dry-run")
    if mode not in {"dry-run", "apply"}:
        return jsonify({"error": "invalid mode"}), 400

    board = trello_get("/boards/qCPeWA3e", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "all",
    })
    lists_by_id = {item["id"]: item for item in lists}
    open_lists_by_name = {
        item["name"]: item for item in lists if not item.get("closed")
    }
    target_23_list = open_lists_by_name.get("6.8.")
    if not target_23_list:
        return jsonify({"error": "target list 6.8. not found"}), 404

    # Persistent exceptional matching rules:
    # - the PDF abbreviates FLASH as F, while the Trello card uses FLASH;
    # - 24/08A and 24/08B are intentionally represented by one 24/08 card.
    rules = {
        "23/34F": {"card_id": "6a34e640305cf71b2dd1b86e", "canonical": "23/34FLASH"},
        "24/8A+24/8B": {"card_id": "6a34e68ac33c7998d2ff70ef", "canonical": "24/08"},
    }
    cards = {}
    for rule_name, rule in rules.items():
        card = trello_get(f"/cards/{rule['card_id']}", {
            "fields": "id,name,desc,idBoard,idList,shortUrl,due,dueComplete,closed,pos",
        })
        if card.get("idBoard") != board["id"]:
            return jsonify({"error": f"{rule_name} card is not on the Dunaj board"}), 409
        cards[rule_name] = card

    start_marker = "<!-- DUNAJ-SCHEDULE-METADATA:START -->"
    end_marker = "<!-- DUNAJ-SCHEDULE-METADATA:END -->"

    def merge_metadata(old_desc, metadata):
        if start_marker in old_desc and end_marker in old_desc:
            pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
            return re.sub(pattern, lambda _: metadata, old_desc, count=1, flags=re.S)
        return metadata + ("\n\n" + old_desc if old_desc else "")

    metadata_23 = (
        f"{start_marker}\n"
        "**ČÍSLO OBRAZU:** 23/34FLASH\n"
        "**ZDROJ:** predbežná dispo DUNAJ 16 z 25. 7. 2026\n"
        "**NATÁČACÍ DEŇ:** 81\n"
        "**DÁTUM NATÁČANIA:** 2026-08-06\n"
        "**PORADIE DŇA:** 2\n"
        "**UNIT:** 1st unit\n"
        "**LOKÁCIA:** KLAUSOVCI - SALÓN\n"
        "**POSTAVY:** Oleg, Astrid, Boris\n"
        f"{end_marker}"
    )
    metadata_24 = (
        f"{start_marker}\n"
        "**ČÍSLO OBRAZU:** 24/08 (24/08A + 24/08B)\n"
        "**ZDROJ:** predbežná dispo DUNAJ 16 z 25. 7. 2026\n"
        "**NATÁČACÍ DEŇ:** 87\n"
        "**DÁTUM NATÁČANIA:** 2026-08-16\n"
        "**PORADIE DŇA:** 8-9\n"
        "**UNIT:** 1st unit\n"
        "**LOKÁCIA:** KABARET - ZÁZEMIE / KABARET\n"
        "**POSTAVY:** René, Lena, Gita\n"
        f"{end_marker}"
    )
    desired = {
        "23/34F": {
            "name_prefix": "23/34FLASH",
            "desc": merge_metadata(cards["23/34F"].get("desc", ""), metadata_23),
            "due": "2026-08-06T10:00:00.000Z",
            "idList": target_23_list["id"],
            "pos": 32768,
        },
        "24/8A+24/8B": {
            "name_prefix": "24/08",
            "desc": merge_metadata(cards["24/8A+24/8B"].get("desc", ""), metadata_24),
            "due": "2026-08-16T10:00:00.000Z",
            # 16. 8. is outside the current seven-shooting-day window.
            "idList": cards["24/8A+24/8B"]["idList"],
            "pos": cards["24/8A+24/8B"].get("pos"),
        },
    }

    planned = []
    missing = []
    for rule_name, card in cards.items():
        wanted = desired[rule_name]
        changes = {}
        if card.get("closed"):
            changes["closed"] = False
        if not card.get("name", "").upper().startswith(wanted["name_prefix"]):
            changes["name_prefix"] = wanted["name_prefix"]
        if card.get("desc", "") != wanted["desc"]:
            changes["desc"] = "replace schedule metadata block"
        if (card.get("due") or "")[:10] != wanted["due"][:10]:
            changes["due"] = wanted["due"]
        if card.get("dueComplete"):
            changes["dueComplete"] = False
        if card.get("idList") != wanted["idList"]:
            changes["list"] = {
                "from": lists_by_id.get(card.get("idList"), {}).get("name"),
                "to": lists_by_id.get(wanted["idList"], {}).get("name"),
            }
        if rule_name == "23/34F" and float(card.get("pos", 0)) != float(wanted["pos"]):
            changes["pos"] = wanted["pos"]
        planned.append({
            "rule": rule_name, "canonical": rules[rule_name]["canonical"],
            "card": card["name"], "url": card.get("shortUrl"), "changes": changes,
        })
        if not card.get("id"):
            missing.append(rule_name)

    if mode == "dry-run":
        return jsonify({
            "status": "dry-run", "board": board["name"],
            "rules": rules, "planned": planned,
            "missing_count": len(missing), "missing": missing,
            "duplicate_count": 0, "fallback_count": 0,
            "collision_count": 0,
            "pending_updates_count": sum(bool(item["changes"]) for item in planned),
        })

    updated = []
    for item in planned:
        if not item["changes"]:
            continue
        rule_name = item["rule"]
        card = cards[rule_name]
        wanted = desired[rule_name]
        payload = {
            "desc": wanted["desc"], "due": wanted["due"],
            "dueComplete": "false", "closed": "false",
        }
        if card.get("idList") != wanted["idList"]:
            payload["idList"] = wanted["idList"]
        if rule_name == "23/34F":
            payload["pos"] = wanted["pos"]
        result = trello_put_body(f"/cards/{card['id']}", payload)
        updated.append({
            "rule": rule_name, "canonical": rules[rule_name]["canonical"],
            "card": result.get("name"), "url": result.get("shortUrl"),
        })

    return jsonify({
        "status": "applied", "board": board["name"],
        "updated_count": len(updated), "updated": updated,
        "missing_count": 0, "duplicate_count": 0,
        "fallback_count": 0, "collision_count": 0,
    })


@app.route("/api/reorder-dunaj-date-lists", methods=["POST"])
def reorder_dunaj_date_lists():
    return jsonify({"error": "endpoint disabled"}), 410
    if request.headers.get("X-Reorder-Key") != "dunaj-date-lists-19jul-8d3f01a7":
        return jsonify({"error": "forbidden"}), 403

    board = trello_get("/boards/qCPeWA3e", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,pos,closed", "filter": "open"})
    lists = sorted(lists, key=lambda item: item["pos"])
    anchor = next((item for item in lists if item["name"] == "SERIA 15,16"), None)
    if not anchor:
        return jsonify({"error": "SERIA 15,16 list not found"}), 404

    target_names = ["20.7.", "22.7.", "23.7.", "24.7.", "25.7."]
    selected = []
    duplicate_info = {}
    for name in target_names:
        candidates = [item for item in lists if item["name"] == name]
        if not candidates:
            return jsonify({"error": f"{name} list not found"}), 404
        counted = []
        for candidate in candidates:
            cards = trello_get(f"/lists/{candidate['id']}/cards", {"fields": "id", "filter": "open"})
            counted.append((len(cards), candidate))
        counted.sort(key=lambda value: (-value[0], value[1]["pos"]))
        selected.append(counted[0][1])
        if len(counted) > 1:
            duplicate_info[name] = [{"id": item["id"], "cards": count, "pos": item["pos"]} for count, item in counted]

    selected_ids = {item["id"] for item in selected}
    following = [item for item in lists if item["id"] not in selected_ids and item["pos"] > anchor["pos"]]
    next_pos = following[0]["pos"] if following else anchor["pos"] + 16384 * (len(selected) + 1)
    step = (next_pos - anchor["pos"]) / (len(selected) + 1)
    planned = [{"id": item["id"], "name": item["name"], "cards": next(
        len(trello_get(f"/lists/{item['id']}/cards", {"fields": "id", "filter": "open"}))
        for candidate in [item]
    ), "pos": anchor["pos"] + step * index} for index, item in enumerate(selected, start=1)]

    if request.args.get("mode", "dry-run") == "apply":
        updated = []
        for item in planned:
            result = trello_put_body(f"/lists/{item['id']}", {"pos": item["pos"]})
            updated.append({"id": result["id"], "name": result["name"], "pos": result["pos"]})
        return jsonify({"status": "applied", "anchor": anchor["name"], "updated": updated, "duplicates": duplicate_info})

    return jsonify({"status": "dry-run", "board": board["name"], "anchor": anchor,
                    "planned": planned, "duplicates": duplicate_info})


@app.route("/api/dunaj-props-inventory", methods=["GET"])
def dunaj_props_inventory():
    return jsonify({"error": "endpoint disabled"}), 410
    if request.headers.get("X-Inventory-Key") != "dunaj-props-inventory-2bc741e9":
        return jsonify({"error": "forbidden"}), 403
    board = trello_get("/boards/qCPeWA3e", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,pos,closed", "filter": "open"})
    summary = []
    todo_samples = []
    scene_samples = []
    for board_list in sorted(lists, key=lambda item: item["pos"]):
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,due,shortUrl,closed", "filter": "open", "limit": 1000
        })
        scene_cards = []
        for card in cards:
            match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
            if match:
                scene_cards.append(card)
        summary.append({
            "id": board_list["id"], "name": board_list["name"], "pos": board_list["pos"],
            "cards": len(cards), "scene_cards": len(scene_cards),
        })
        if board_list["name"].strip().lower() == "todo":
            todo_samples = [{
                "id": card["id"], "name": card["name"], "desc": card.get("desc", ""),
                "due": card.get("due"), "url": card["shortUrl"],
            } for card in cards[:20]]
        if scene_cards and len(scene_samples) < 12:
            for card in scene_cards[:3]:
                scene_samples.append({
                    "list": board_list["name"], "id": card["id"], "name": card["name"],
                    "desc": card.get("desc", "")[:1500], "due": card.get("due"), "url": card["shortUrl"],
                })
                if len(scene_samples) >= 12:
                    break
    return jsonify({"board": board["name"], "lists": summary,
                    "todo_samples": todo_samples, "scene_samples": scene_samples})


@app.route("/api/dunaj-z-items", methods=["GET"])
def dunaj_z_items():
    return jsonify({"error": "endpoint disabled"}), 410
    if request.headers.get("X-Inventory-Key") != "dunaj-props-inventory-2bc741e9":
        return jsonify({"error": "forbidden"}), 403
    list_id = request.args.get("idList", "").strip()
    if not list_id:
        return jsonify({"error": "idList required"}), 400
    board_list = trello_get(f"/lists/{list_id}", {"fields": "id,name,idBoard,closed"})
    board = trello_get("/boards/qCPeWA3e", {"fields": "id"})
    if board_list.get("idBoard") != board["id"]:
        return jsonify({"error": "wrong board"}), 400
    cards = trello_get(f"/lists/{list_id}/cards", {
        "fields": "id,name,desc,due,shortUrl,closed", "filter": "open", "limit": 1000,
        "checklists": "all", "checklist_fields": "name",
    })
    occurrences = []
    scene_cards = 0
    for card in cards:
        match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
        if not match:
            continue
        scene_cards += 1
        scene_id = normalize_scene_id(match.group(1), match.group(2))
        for checklist in card.get("checklists", []):
            for item in checklist.get("checkItems", []):
                item_name = item.get("name", "").strip()
                if CHECKLIST_TAG.lower() not in item_name.lower():
                    continue
                occurrences.append({
                    "item": item_name, "clean": normalize_item_name(item_name),
                    "scene_id": scene_id, "card_name": card["name"], "url": card["shortUrl"],
                    "due": card.get("due"), "list": board_list["name"],
                    "context": card.get("desc", "")[:3000],
                })
    return jsonify({"list": board_list["name"], "cards": len(cards),
                    "scene_cards": scene_cards, "occurrences": occurrences,
                    "occurrences_count": len(occurrences)})


@app.route("/api/sync-<project>-prop-cards", methods=["POST"])
def sync_project_prop_cards(project):
    if request.headers.get("X-Prop-Sync-Key") != "dunaj-props-sync-7f32b861":
        return jsonify({"error": "forbidden"}), 403

    board_refs = {"dunaj": "qCPeWA3e", "riverdale": "CzuD55PR", "dok4": "lzNy4AtY"}
    board_ref = board_refs.get(project.casefold())
    if not board_ref:
        return jsonify({"error": "unknown project"}), 404
    board = trello_get(f"/boards/{board_ref}", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,pos,closed", "filter": "open"})
    todo_list = next((item for item in lists if item["name"].strip().lower() == "todo"), None)
    if not todo_list:
        return jsonify({"error": "ToDo list not found"}), 404

    scene_cards_by_id = {}
    prop_groups = {}
    scanned_scene_cards = 0
    tagged_occurrences = 0
    for board_list in lists:
        folded_list_name = unicodedata.normalize("NFKD", board_list["name"])
        folded_list_name = "".join(char for char in folded_list_name
                                   if not unicodedata.combining(char)).upper()
        if "NATOC" in folded_list_name or board_list["id"] == todo_list["id"]:
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,desc,due,dueComplete,shortUrl,closed,idList", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })
        for card in cards:
            match = re.match(r"^\s*([0-9]{1,2})\s*/\s*([0-9]+[A-Z]*)(?:\.|\s|$)", card.get("name", ""), re.I)
            if not match:
                continue
            scene_id = normalize_scene_id(match.group(1), match.group(2))
            scanned_scene_cards += 1
            current = scene_cards_by_id.get(scene_id)
            if not current or (not current.get("due") and card.get("due")):
                scene_cards_by_id[scene_id] = card
            for checklist in card.get("checklists", []):
                for item in checklist.get("checkItems", []):
                    raw_item = item.get("name", "").strip()
                    if CHECKLIST_TAG.lower() not in raw_item.lower():
                        continue
                    key, display = canonical_prop(raw_item)
                    if not key or key in {"test", "x"}:
                        continue
                    tagged_occurrences += 1
                    group = prop_groups.setdefault(key, {"display": display, "occurrences": [], "refs": set()})
                    if len(display) < len(group["display"]):
                        group["display"] = display
                    group["occurrences"].append({
                        "scene_id": scene_id, "card": card, "item": tagged_prop_text(raw_item),
                    })
                    for episode, scene in re.findall(r"\b(\d{1,2})\s*/\s*(\d+[A-Z]*)\b", raw_item, flags=re.I):
                        ref = normalize_scene_id(episode, scene)
                        if ref:
                            group["refs"].add(ref)

    todo_cards = trello_get(f"/lists/{todo_list['id']}/cards", {
        "fields": "id,name,desc,due,shortUrl,closed,pos", "filter": "open", "limit": 1000
    })
    todo_by_key = {}
    for card in todo_cards:
        desc = card.get("desc", "")
        match = re.search(r"Pôvodná checklist položka:\s*(.*?)(?:\n\n|$)", desc, flags=re.S | re.I)
        source_text = match.group(1).strip() if match else re.split(r"\s+-\s+(?=\d{1,2}/)", card["name"], maxsplit=1)[0]
        key, _ = canonical_prop(source_text)
        if key:
            todo_by_key.setdefault(key, []).append(card)

    plans = []
    for key, group in prop_groups.items():
        linked = {}
        contexts = {}
        for occurrence in group["occurrences"]:
            linked[occurrence["scene_id"]] = occurrence["card"]
            contexts.setdefault(occurrence["scene_id"], set()).add(occurrence["item"])
        for ref in group["refs"]:
            if ref in scene_cards_by_id:
                linked.setdefault(ref, scene_cards_by_id[ref])
        ordered_scenes = sorted(linked.items(), key=lambda pair: (
            pair[1].get("due") or "9999-12-31", pair[0]
        ))
        earliest = next(((scene_id, card) for scene_id, card in ordered_scenes if card.get("due")),
                        ordered_scenes[0] if ordered_scenes else (None, None))
        existing = sorted(todo_by_key.get(key, []), key=lambda card: card.get("pos", 0))
        plans.append({
            "key": key, "display": group["display"], "linked": ordered_scenes,
            "contexts": contexts, "earliest_scene": earliest[0], "earliest_card": earliest[1],
            "existing": existing,
        })
    plans.sort(key=lambda item: item["display"].lower())

    marker_start = "<!-- DUNAJ-PROP-SYNC:START -->"
    marker_end = "<!-- DUNAJ-PROP-SYNC:END -->"
    for plan in plans:
        earliest_scene = plan["earliest_scene"] or "bez dátumu"
        earliest_card = plan["earliest_card"]
        desired_due = earliest_card.get("due") if earliest_card else None
        lines = [
            marker_start,
            "Vytvorené a synchronizované automaticky z obrazových kariet.", "",
            f"**REKVIZITA:** {plan['display']}",
            f"**NAJSKORŠÍ OBRAZ:** {earliest_scene}",
            f"**DUE DATE:** {(desired_due or 'nenastavený')[:10]}", "",
            "**OBRAZY, ODKAZY A KONTEXT:**",
        ]
        for scene_id, scene_card in plan["linked"]:
            date_text = (scene_card.get("due") or "")[:10] or "bez dátumu"
            lines.append(f"- [{scene_id} — {scene_card['name']}]({scene_card['shortUrl']}) — {date_text}")
            for context in sorted(plan["contexts"].get(scene_id, set())):
                lines.append(f"  - Akcia/kontext: {context}")
        lines.extend(["", "**NÁJDENÁ KONTINUITA V ĎALŠÍCH OBRAZOCH:**",
                      ", ".join(scene_id for scene_id, _ in plan["linked"]) or "nenájdená", marker_end])
        synced = "\n".join(lines)
        primary = plan["existing"][0] if plan["existing"] else None
        changes = {}
        desired_desc = synced
        if primary:
            old_desc = primary.get("desc", "")
            if marker_start in old_desc and marker_end in old_desc:
                pattern = re.escape(marker_start) + r".*?" + re.escape(marker_end)
                desired_desc = re.sub(pattern, lambda _: synced, old_desc, count=1, flags=re.S)
            elif old_desc:
                desired_desc = synced + "\n\n---\n\n**PÔVODNÝ ZÁZNAM / RUČNÉ POZNÁMKY:**\n\n" + old_desc
            if desired_desc != old_desc:
                changes["desc"] = desired_desc
            current_due = primary.get("due") or None
            if (current_due or "")[:10] != (desired_due or "")[:10]:
                changes["due"] = desired_due or ""
        plan.update({"desired_desc": desired_desc, "desired_due": desired_due,
                     "changes": changes})

    summary = {
        "board": board["name"], "scene_cards_scanned": scanned_scene_cards,
        "tagged_occurrences": tagged_occurrences, "unique_props": len(plans),
        "todo_cards_before": len(todo_cards),
        "to_create": sum(1 for item in plans if not item["existing"]),
        "to_update": sum(1 for item in plans if item["existing"] and item["changes"]),
        "unchanged": sum(1 for item in plans if item["existing"] and not item["changes"]),
        "duplicates_to_archive": sum(max(0, len(item["existing"]) - 1) for item in plans),
        "without_due": sum(1 for item in plans if not item["earliest_card"] or not item["earliest_card"].get("due")),
    }
    matched_todo_ids = {card["id"] for item in plans for card in item["existing"]}
    unmatched_todo = [card for card in todo_cards if card["id"] not in matched_todo_ids]
    mode = request.args.get("mode", "dry-run")
    if mode == "dry-run":
        return jsonify({"status": "dry-run", **summary,
                        "missing_card_sample": [{"key": item["key"], "prop": item["display"],
                                                 "earliest_scene": item["earliest_scene"]}
                                                for item in plans if not item["existing"]][:30],
                        "unmatched_todo_sample": [{"id": card["id"], "name": card["name"],
                                                   "url": card["shortUrl"], "due": card.get("due")}
                                                  for card in unmatched_todo[:30]],
                        "sample": [{
            "prop": item["display"], "scenes": [scene_id for scene_id, _ in item["linked"]],
            "earliest_scene": item["earliest_scene"],
            "current_due": item["existing"][0].get("due") if item["existing"] else None,
            "desired_due": item["desired_due"],
            "action": "create" if not item["existing"] else ("update" if item["changes"] else "unchanged"),
            "fields": sorted(item["changes"]),
            "existing_cards": [card["name"] for card in item["existing"]],
        } for item in plans[:40]]}), 200

    if mode == "archive-unmatched-auto":
        archived = []
        skipped = []
        for card in unmatched_todo:
            if "Vytvorené automaticky z checklist položky." not in card.get("desc", ""):
                skipped.append({"id": card["id"], "name": card["name"]})
                continue
            trello_put_body(f"/cards/{card['id']}", {"closed": "true"})
            archived.append({"id": card["id"], "name": card["name"]})
        return jsonify({"status": "unmatched-auto-archived", "archived": archived,
                        "archived_count": len(archived), "skipped": skipped})

    if mode != "apply":
        return jsonify({"error": "invalid mode"}), 400
    start = max(0, int(request.args.get("start", "0")))
    limit = min(25, max(1, int(request.args.get("limit", "15"))))
    apply_plans = ([item for item in plans if not item["existing"]]
                   if request.args.get("only_missing") == "1"
                   else [item for item in plans
                         if not item["existing"] or item["changes"] or len(item["existing"]) > 1])
    batch = apply_plans[start:start + limit]
    created = []; updated = []; archived = []; errors = []
    for plan in batch:
        earliest_card = plan["earliest_card"]
        primary = plan["existing"][0] if plan["existing"] else None
        if primary:
            try:
                if plan["changes"]:
                    trello_put_body(f"/cards/{primary['id']}", plan["changes"])
                    updated.append(primary["id"])
            except Exception as exc:
                errors.append({"prop": plan["display"], "error": str(exc)})
                continue
        else:
            if not earliest_card:
                errors.append({"prop": plan["display"], "error": "no linked scene card"})
                continue
            payload = {
                "idList": todo_list["id"],
                "name": f"{plan['display']} - {earliest_card['name']}",
                "desc": plan["desired_desc"], "pos": "bottom",
            }
            if earliest_card.get("due"):
                payload["due"] = earliest_card["due"]
            try:
                result = trello_post_body("/cards", payload)
                created.append(result["id"])
            except Exception as exc:
                errors.append({"prop": plan["display"], "error": str(exc)})
                continue
        for duplicate in plan["existing"][1:]:
            try:
                trello_put_body(f"/cards/{duplicate['id']}", {"closed": "true"})
                archived.append(duplicate["id"])
            except Exception as exc:
                errors.append({"prop": plan["display"], "error": f"archive duplicate: {exc}"})
    return jsonify({"status": "applied", **summary, "start": start, "batch": len(batch),
                    "remaining": max(0, len(apply_plans) - start - len(batch)),
                    "created": len(created), "updated": len(updated), "archived": len(archived),
                    "errors_count": len(errors), "errors": errors[:20]})


@app.route("/api/setup-dunaj-meeting-workflow", methods=["POST"])
def setup_dunaj_meeting_workflow():
    return jsonify({"error": "endpoint disabled"}), 410
    if request.headers.get("X-Meeting-Setup-Key") != "meeting-setup-riverdale-dok4-b618e2c4":
        return jsonify({"error": "forbidden"}), 403
    project = request.args.get("project", "").strip().lower()
    board_refs = {"riverdale": "CzuD55PR", "dok4": "lzNy4AtY"}
    if project not in board_refs:
        return jsonify({"error": "project must be riverdale or dok4"}), 400
    board = trello_get(f"/boards/{board_refs[project]}", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed", "filter": "open"})
    requested_list_id = request.args.get("idList", "").strip()
    scan_lists = lists
    if requested_list_id:
        scan_lists = [item for item in lists if item["id"] == requested_list_id]
        if not scan_lists:
            return jsonify({"error": "idList not found on board"}), 404
    # Meeting notes are intentionally free-form; do not prefill placeholders.
    checklist_items = []
    expected_names = {name.upper() for name in checklist_items}
    old_template_names = {"PRIDAŤ", "UPRAVIŤ", "ZRUŠIŤ", "KONTINUITA", "ZABEZPEČIŤ",
                          "NETREBA ZABEZPEČIŤ", "SCHVÁLENÉ", "OTÁZKA"}
    scene_cards = []
    list_stats = []
    meeting_checklist = None
    for board_list in scan_lists:
        folded_list_name = unicodedata.normalize("NFKD", board_list["name"])
        folded_list_name = "".join(char for char in folded_list_name if not unicodedata.combining(char)).upper()
        if "NATOC" in folded_list_name:
            continue
        cards = trello_get(f"/lists/{board_list['id']}/cards", {
            "fields": "id,name,shortUrl", "filter": "open", "limit": 1000,
            "checklists": "all", "checklist_fields": "name",
        })
        list_scene_count = 0
        list_complete_count = 0
        for card in cards:
            if not scene_id_from_card_name(card.get("name")):
                continue
            list_scene_count += 1
            checklists = card.get("checklists", [])
            existing = next((item for item in checklists if item.get("name", "").strip().upper() == "POZNÁMKY Z PORADY"), None)
            existing_names = {item.get("name", "").strip().upper() for item in (existing or {}).get("checkItems", [])}
            obsolete_items = [item for item in (existing or {}).get("checkItems", [])
                              if item.get("name", "").strip().upper() in old_template_names]
            is_complete = expected_names.issubset(existing_names) and not obsolete_items
            if existing and is_complete and not meeting_checklist:
                meeting_checklist = existing
            scene_cards.append({"card": card, "checklist": existing, "item_names": existing_names,
                                "obsolete_items": obsolete_items,
                                "only_obsolete": bool(existing_names and existing_names.issubset(old_template_names)),
                                "complete": bool(existing and is_complete)})
            if existing and is_complete:
                list_complete_count += 1
        if list_scene_count:
            list_stats.append({"id": board_list["id"], "name": board_list["name"],
                               "scenes": list_scene_count, "complete": list_complete_count,
                               "incomplete": list_scene_count - list_complete_count})

    todo_list = next((item for item in lists if item["name"].strip().lower() == "todo"), None)
    todo_cards = trello_get(f"/lists/{todo_list['id']}/cards", {
        "fields": "id,name,desc,due,shortUrl", "filter": "open", "limit": 1000
    }) if todo_list else []
    marker_start = "<!-- DUNAJ-PROP-SYNC:START -->"
    marker_end = "<!-- DUNAJ-PROP-SYNC:END -->"
    props_to_clean = []
    for card in todo_cards:
        desc = card.get("desc", "")
        if marker_start in desc and marker_end in desc:
            marker = desc[desc.index(marker_start):desc.index(marker_end) + len(marker_end)]
            if desc.strip() != marker.strip():
                props_to_clean.append({"card": card, "marker": marker})

    mode = request.args.get("mode", "dry-run")
    missing_checklists = [item for item in scene_cards if not item["checklist"]]
    incomplete_checklists = [item for item in scene_cards if not item["complete"]]
    empty_checklists = [item for item in scene_cards if item["checklist"] and not item["item_names"]]
    if mode == "dry-run":
        return jsonify({
            "status": "dry-run", "board": board["name"],
            "scene_cards": len(scene_cards), "checklists_present": len(scene_cards) - len(missing_checklists),
            "checklists_complete": len(scene_cards) - len(incomplete_checklists),
            "checklists_incomplete": len(incomplete_checklists), "checklists_empty": len(empty_checklists),
            "checklists_missing": len(missing_checklists), "todo_cards": len(todo_cards),
            "prop_descriptions_to_clean": len(props_to_clean),
            "list_stats": list_stats,
            "meeting_checklist_sample": {
                "name": meeting_checklist.get("name"),
                "items": [item.get("name") for item in meeting_checklist.get("checkItems", [])],
            } if meeting_checklist else None,
        })

    limit = min(50, max(1, int(request.args.get("limit", "25"))))
    if mode == "clean-props":
        batch = props_to_clean[:limit]
        errors = []
        for item in batch:
            try:
                trello_put_body(f"/cards/{item['card']['id']}", {"desc": item["marker"]})
            except Exception as exc:
                errors.append({"card": item["card"]["name"], "error": str(exc)})
        return jsonify({"status": "props-cleaned", "updated": len(batch) - len(errors),
                        "remaining": max(0, len(props_to_clean) - len(batch)),
                        "errors_count": len(errors), "errors": errors})

    if mode == "add-checklists":
        created_template_card = None
        if not meeting_checklist and incomplete_checklists:
            template_item = incomplete_checklists[0]
            created_template_card = template_item["card"]
            meeting_checklist = template_item["checklist"]
            if not meeting_checklist:
                meeting_checklist = trello_post_body("/checklists", {
                    "idCard": created_template_card["id"], "name": "POZNÁMKY Z PORADY", "pos": "bottom"
                })
            for obsolete in template_item["obsolete_items"]:
                trello_delete(f"/checklists/{meeting_checklist['id']}/checkItems/{obsolete['id']}")
            for item_name in checklist_items:
                if item_name.upper() not in template_item["item_names"]:
                    trello_post_body(f"/checklists/{meeting_checklist['id']}/checkItems", {"name": item_name})
        batch = [item for item in incomplete_checklists if not created_template_card or item["card"]["id"] != created_template_card["id"]][:limit]
        created = 1 if created_template_card else 0
        errors = []

        def create_clean_meeting_checklist(card_id):
            clean = trello_post_body("/checklists", {
                "idCard": card_id, "name": "POZNÁMKY Z PORADY", "pos": "bottom"
            })
            for clean_item_name in checklist_items:
                trello_post_body(f"/checklists/{clean['id']}/checkItems", {"name": clean_item_name})

        for item in batch:
            try:
                if item["checklist"] and (not item["item_names"] or item["only_obsolete"]):
                    trello_delete(f"/checklists/{item['checklist']['id']}")
                    create_clean_meeting_checklist(item["card"]["id"])
                elif item["checklist"]:
                    for obsolete in item["obsolete_items"]:
                        trello_delete(f"/checklists/{item['checklist']['id']}/checkItems/{obsolete['id']}")
                    for item_name in checklist_items:
                        if item_name.upper() not in item["item_names"]:
                            trello_post_body(f"/checklists/{item['checklist']['id']}/checkItems", {"name": item_name})
                else:
                    create_clean_meeting_checklist(item["card"]["id"])
                created += 1
            except Exception as exc:
                errors.append({"card": item["card"]["name"], "error": str(exc)})
        return jsonify({"status": "checklists-added", "created": created,
                        "remaining": max(0, len(incomplete_checklists) - created),
                        "errors_count": len(errors), "errors": errors[:20]})

    return jsonify({"error": "invalid mode"}), 400


@app.route("/trello-webhook", methods=["POST"])
def trello_webhook():
    data = request.json
    print("RAW DATA:", data)

    if not data or "action" not in data:
        return jsonify({"status": "ignored", "reason": "no action"}), 200

    action = data["action"]
    action_type = action.get("type", "")
    action_id = action.get("id")

    print("ACTION TYPE:", action_type)
    print("ACTION ID:", action_id)

    if not action_id:
        return jsonify({"status": "ignored", "reason": "missing action id"}), 200

    if action_id in processed_actions:
        print("SKIP duplicate action:", action_id)
        return jsonify({"status": "ignored", "reason": "duplicate action"}), 200

    if action_type not in ["createCheckItem", "updateCheckItem"]:
        return jsonify({"status": "ignored", "reason": f"unsupported action {action_type}"}), 200

    if action_type == "updateCheckItem":
        old = action.get("data", {}).get("old", {})
        if "name" not in old:
            return jsonify({"status": "ignored", "reason": "not a name change"}), 200

    action_data = action.get("data", {})
    card = action_data.get("card")
    checkitem = action_data.get("checkItem")

    if not card or not checkitem:
        return jsonify({"status": "ignored", "reason": "missing card or checkitem"}), 200

    card_id = card["id"]
    checkitem_name = checkitem.get("name", "").strip()

    if not checkitem_name:
        return jsonify({"status": "ignored", "reason": "empty checkitem name"}), 200

    try:
        card_info = get_card(card_id)
    except Exception as e:
        return jsonify({"status": "error", "reason": f"failed to load card: {str(e)}"}), 500

    target_list_id = target_list_id_for_card(card_info)
    if not target_list_id:
        print("IGNORED: unsupported board", card_info.get("idBoard"))
        return jsonify({"status": "ignored", "reason": "card not on supported board"}), 200

    item_lower = checkitem_name.lower()
    tag_lower = CHECKLIST_TAG.lower()

    print("ITEM:", checkitem_name)
    print("CHECKLIST TAG:", CHECKLIST_TAG)

    if tag_lower not in item_lower:
        return jsonify({"status": "ignored", "reason": "no matching tag"}), 200

    clean_name = normalize_item_name(checkitem_name)
    print("CLEAN NAME:", clean_name)

    if not clean_name:
        return jsonify({"status": "ignored", "reason": "empty clean name"}), 200

    try:
        prop_key, prop_display = canonical_prop(checkitem_name)
        new_card_name = f"{prop_display} - {card_info['name']}"

        matching_cards = find_cards_with_exact_item(
            clean_name,
            card_info["idBoard"],
            exclude_card_id=card_id
        )

        if matching_cards:
            found_text = ", ".join(matching_cards)
        else:
            found_text = "nenájdené"

        new_card_desc = build_prop_sync_marker(prop_display, card_info, checkitem_name)

        existing_props = find_todo_cards_by_prop(target_list_id, prop_key)
        if existing_props:
            primary = existing_props[0]
            old_desc = primary.get("desc", "")
            payload = {"desc": add_scene_to_prop_marker(
                old_desc, prop_display, card_info, checkitem_name, primary.get("due")
            )}
            current_due = card_info.get("due")
            if current_due and (not primary.get("due") or current_due < primary["due"]):
                payload["due"] = current_due
            if payload:
                trello_put_body(f"/cards/{primary['id']}", payload)
            for duplicate in existing_props[1:]:
                trello_put_body(f"/cards/{duplicate['id']}", {"closed": "true"})
            print("UPDATED existing prop card:", primary["name"])
        else:
            create_payload = {"idList": target_list_id, "name": new_card_name,
                              "desc": new_card_desc, "pos": "bottom"}
            if card_info.get("due"):
                create_payload["due"] = card_info["due"]
            created_card = trello_post_body("/cards", create_payload)
            print("CARD CREATED:", created_card)

    except Exception as e:
        print("CARD ERROR:", repr(e))
        return jsonify({"status": "error", "reason": f"card failed: {str(e)}"}), 500

    todo_status = "skipped"
    try:
        todo_task = create_todo_task(
            clean_name,
            checkitem_name,
            card_info,
            matching_cards
        )
        if todo_task:
            todo_status = "created"
        elif microsoft_enabled():
            todo_status = "already_exists_or_skipped"
        else:
            todo_status = "not_configured"

    except Exception as e:
        todo_status = "error"
        print("TODO ERROR:", repr(e))

    processed_actions.add(action_id)
    return jsonify({"status": "ok", "mode": "card_and_todo", "todo": todo_status}), 200


@app.route("/api/repair-dok4-returned-card-date", methods=["POST"])
def repair_dok4_returned_card_date():
    return jsonify({"error": "completed one-off endpoint disabled"}), 410
    if request.headers.get("X-Repair-Key") != "dok4-returned-date-08aug-61c2a7f9":
        return jsonify({"error": "forbidden"}), 403
    board = trello_get("/boards/lzNy4AtY", {"fields": "id,name,url"})
    card = trello_get("/cards/ZISdOP56", {
        "fields": "id,name,idBoard,idList,due,dueComplete,shortUrl,closed",
    })
    board_list = trello_get(f"/lists/{card['idList']}", {"fields": "id,name,closed"})
    if (
        card.get("idBoard") != board["id"]
        or not card.get("name", "").startswith("07/15")
        or board_list.get("name") != "VŠETKY EPIZÓDY"
        or card.get("closed")
    ):
        return jsonify({"error": "repair target validation failed"}), 409
    mode = request.args.get("mode", "dry-run")
    result = {
        "status": "dry-run", "board": board["name"], "list": board_list["name"],
        "card": card["name"], "url": card["shortUrl"],
        "current_due": card.get("due"), "current_due_complete": card.get("dueComplete"),
        "desired_due": None, "desired_due_complete": False,
    }
    if mode == "dry-run":
        return jsonify(result)
    if mode != "apply":
        return jsonify({"error": "mode must be dry-run or apply"}), 400
    updated = trello_put_body(f"/cards/{card['id']}", {
        "due": "", "dueComplete": "false",
    })
    result.update({
        "status": "applied", "current_due": updated.get("due"),
        "current_due_complete": updated.get("dueComplete"),
    })
    return jsonify(result)


@app.route("/api/repair-main-list-due-dates", methods=["POST"])
def repair_main_list_due_dates():
    return jsonify({"error": "completed one-off endpoint disabled"}), 410
    if request.headers.get("X-Repair-Key") != "main-list-due-audit-09aug-3db186f4":
        return jsonify({"error": "forbidden"}), 403
    project = request.args.get("project", "").strip().casefold()
    configs = {
        "dok4": {"board": "lzNy4AtY", "main_list": "VŠETKY EPIZÓDY"},
        "dunaj": {"board": "qCPeWA3e", "main_list": "SERIA 15,16"},
        "riverdale": {"board": RIVERDALE_BOARD_REF, "main_list": "SCENÁRE"},
    }
    config = configs.get(project)
    if not config:
        return jsonify({"error": "project must be dok4, dunaj, or riverdale"}), 400
    board = trello_get(f"/boards/{config['board']}", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,closed", "filter": "open",
    })
    main_list = next((item for item in lists if item["name"] == config["main_list"]), None)
    if not main_list:
        return jsonify({"error": "main series list not found"}), 404
    cards = trello_get(f"/lists/{main_list['id']}/cards", {
        "fields": "id,name,due,dueComplete,shortUrl,closed", "filter": "open", "limit": 1000,
    })
    stale = [card for card in cards if card.get("due") or card.get("dueComplete")]
    mode = request.args.get("mode", "dry-run")
    summary = {
        "board": board["name"], "main_list": main_list["name"],
        "cards_scanned": len(cards), "stale_due_count": len(stale),
        "sample": [{
            "name": card["name"], "due": card.get("due"),
            "due_complete": card.get("dueComplete"), "url": card["shortUrl"],
        } for card in stale[:50]],
    }
    if mode == "dry-run":
        return jsonify({"status": "dry-run", **summary})
    if mode != "apply":
        return jsonify({"error": "mode must be dry-run or apply"}), 400
    start = max(0, int(request.args.get("start", "0")))
    limit = min(50, max(1, int(request.args.get("limit", "25"))))
    batch = stale[start:start + limit]
    updated = []; errors = []
    for card in batch:
        try:
            result = trello_put_body(f"/cards/{card['id']}", {
                "due": "", "dueComplete": "false",
            })
            updated.append({"name": result["name"], "url": result["shortUrl"]})
        except Exception as exc:
            errors.append({"name": card["name"], "error": str(exc)})
    return jsonify({
        "status": "applied", **summary, "start": start, "batch": len(batch),
        "updated": len(updated), "errors_count": len(errors), "errors": errors,
        "remaining": max(0, len(stale) - start - len(batch)),
    })


@app.route("/api/sync-dok4-current-schedule", methods=["POST"])
def sync_dok4_current_schedule():
    """Synchronize DOK 4 from the latest supplied plan.

    The active window is the next seven shooting dates on or after ``as_of``.
    Calendar days without shooting never consume a slot.
    """
    return jsonify({"error": "completed one-off endpoint disabled"}), 410
    if request.headers.get("X-Sync-Key") != DOK4_CURRENT_SCHEDULE_KEY:
        return jsonify({"error": "forbidden"}), 403

    mode = request.args.get("mode", "dry-run")
    if mode not in {"dry-run", "apply", "metadata", "window"}:
        return jsonify({
            "error": "mode must be dry-run, apply, metadata, or window"
        }), 400

    as_of = request.args.get("as_of", DOK4_CURRENT_SCHEDULE_AS_OF)
    if as_of != DOK4_CURRENT_SCHEDULE_AS_OF:
        return jsonify({
            "error": "this one-off endpoint has a fixed as_of date",
            "expected_as_of": DOK4_CURRENT_SCHEDULE_AS_OF,
        }), 400
    schedule_path = os.path.join(
        os.path.dirname(__file__), DOK4_CURRENT_SCHEDULE_FILE
    )
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_document = json.load(handle)

    source_date = schedule_document.get("source", {}).get("dated", as_of)
    schedule = schedule_document["rows"]
    unique_scene_ids = {row.get("scene_id") for row in schedule}
    if (
        source_date != DOK4_CURRENT_SCHEDULE_AS_OF
        or len(schedule) != DOK4_CURRENT_SCHEDULE_ROWS
        or len(unique_scene_ids) != DOK4_CURRENT_SCHEDULE_ROWS
        or None in unique_scene_ids
    ):
        return jsonify({
            "error": "schedule source validation failed",
            "source_date": source_date,
            "rows": len(schedule),
            "unique_scene_ids": len(unique_scene_ids),
        }), 409
    trello = Dok4ScheduleTrello(API_KEY, TOKEN)
    state = build_dok4_schedule_state(
        trello, schedule, source_date=source_date, as_of=as_of
    )
    if mode == "dry-run":
        return jsonify(summarize_dok4_schedule(state, schedule))

    if mode == "metadata":
        result = apply_dok4_schedule(
            trello, state, metadata_only=True,
            metadata_limit=min(40, max(1, int(request.args.get("limit", "35")))),
        )
    elif mode == "window":
        result = apply_dok4_schedule(trello, state, skip_metadata=True)
    else:
        result = apply_dok4_schedule(trello, state)
    result.update({
        "schedule_file": DOK4_CURRENT_SCHEDULE_FILE,
        "schedule_rows": len(schedule),
        "window_type": "next_shooting_days",
        "window_as_of": as_of,
        "shooting_dates": state["shooting_dates"],
    })
    return jsonify(result)


@app.route("/api/sync-riverdale-current-schedule", methods=["POST"])
def sync_riverdale_current_schedule():
    """Synchronize Riverdale from the latest supplied plan."""
    if request.headers.get("X-Sync-Key") != RIVERDALE_CURRENT_SCHEDULE_KEY:
        return jsonify({"error": "forbidden"}), 403
    mode = request.args.get("mode", "dry-run")
    if mode not in {"dry-run", "apply", "metadata", "window"}:
        return jsonify({
            "error": "mode must be dry-run, apply, metadata, or window"
        }), 400
    as_of = request.args.get("as_of", RIVERDALE_CURRENT_SCHEDULE_AS_OF)
    if as_of != RIVERDALE_CURRENT_SCHEDULE_AS_OF:
        return jsonify({
            "error": "this one-off endpoint has a fixed as_of date",
            "expected_as_of": RIVERDALE_CURRENT_SCHEDULE_AS_OF,
        }), 400
    schedule_path = os.path.join(
        os.path.dirname(__file__), RIVERDALE_CURRENT_SCHEDULE_FILE
    )
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_document = json.load(handle)
    source_date = schedule_document.get("source", {}).get("dated", as_of)
    schedule = schedule_document["rows"]
    unique_scene_ids = {row.get("scene_id") for row in schedule}
    if (
        source_date != RIVERDALE_CURRENT_SCHEDULE_AS_OF
        or len(schedule) != RIVERDALE_CURRENT_SCHEDULE_ROWS
        or len(unique_scene_ids) != RIVERDALE_CURRENT_SCHEDULE_ROWS
        or None in unique_scene_ids
    ):
        return jsonify({
            "error": "schedule source validation failed",
            "source_date": source_date,
            "rows": len(schedule),
            "unique_scene_ids": len(unique_scene_ids),
        }), 409
    trello = Dok4ScheduleTrello(API_KEY, TOKEN)
    state = build_dok4_schedule_state(
        trello, schedule, source_date=source_date, as_of=as_of,
        board_ref=RIVERDALE_BOARD_REF,
        start_marker=RIVERDALE_START_MARKER,
        end_marker=RIVERDALE_END_MARKER,
        source_label=RIVERDALE_SOURCE_LABEL,
    )
    if mode == "dry-run":
        return jsonify(summarize_dok4_schedule(state, schedule))
    if mode == "metadata":
        result = apply_dok4_schedule(
            trello, state, metadata_only=True,
            metadata_limit=min(40, max(1, int(request.args.get("limit", "35")))),
        )
    elif mode == "window":
        result = apply_dok4_schedule(trello, state, skip_metadata=True)
    else:
        result = apply_dok4_schedule(trello, state)
    result.update({
        "schedule_file": RIVERDALE_CURRENT_SCHEDULE_FILE,
        "schedule_rows": len(schedule),
        "window_type": "next_shooting_days",
        "window_as_of": as_of,
        "shooting_dates": state["shooting_dates"],
    })
    return jsonify(result)


@app.route("/api/handoff-automation-deployment", methods=["POST"])
def handoff_automation_deployment():
    return jsonify({"error": "completed one-off endpoint disabled"}), 410
    if request.headers.get("X-Sync-Key") != DOK4_CURRENT_SCHEDULE_KEY:
        return jsonify({"error": "forbidden"}), 403

    search_query = request.args.get("query", "nasadenie")
    search_result = trello_get("/search", {
        "query": search_query,
        "modelTypes": "cards",
        "cards_limit": 100,
        "card_fields": "id,name,shortUrl,idBoard,idList,closed",
    })

    def folded(value):
        value = unicodedata.normalize("NFKD", value or "")
        return "".join(char for char in value if not unicodedata.combining(char)).casefold()

    candidates = []
    for card in search_result.get("cards", []):
        name = folded(card.get("name"))
        if "nasaden" in name:
            candidates.append(card)

    mode = request.args.get("mode", "dry-run")
    compact = [{
        "id": card["id"], "name": card["name"],
        "url": card.get("shortUrl"), "closed": card.get("closed"),
    } for card in candidates]
    if mode == "dry-run":
        raw_compact = [{
            "id": card["id"], "name": card["name"],
            "url": card.get("shortUrl"), "closed": card.get("closed"),
        } for card in search_result.get("cards", [])]
        return jsonify({
            "status": "dry-run", "candidates": compact,
            "search_results": raw_compact,
        })
    if mode != "apply":
        return jsonify({"error": "mode must be dry-run or apply"}), 400
    if len(candidates) != 1:
        return jsonify({
            "error": "expected exactly one deployment card",
            "candidates": compact,
        }), 409

    note = (
        "Dunaj - doplnenie chýbajúcich obrazov z plánu 25. 7. 2026\n\n"
        "Nasadené produkčné commity: 66eb42d, c93dd5c.\n"
        "Trvalé párovanie: 23/34F -> existujúca karta 23/34FLASH; "
        "24/08A + 24/08B -> jedna existujúca karta 24/08.\n"
        "23/34FLASH: natáčací deň 81, 6. 8. 2026, poradie 2, "
        "1st unit, KLAUSOVCI - SALÓN, Oleg/Astrid/Boris; karta presunutá na 6.8.\n"
        "24/08: spoločné poradie 8-9, natáčací deň 87, 16. 8. 2026, "
        "lokácie KABARET - ZÁZEMIE / KABARET, postavy René/Lena/Gita.\n"
        "Finálny dry-run: čakajúce zmeny 0, chýbajúce 0, duplicity 0, "
        "fallback 0, kolízie 0. Jednorazový opravný endpoint vypnutý."
    )
    action = trello_post_body(
        f"/cards/{candidates[0]['id']}/actions/comments", {"text": note}
    )
    return jsonify({
        "status": "applied",
        "card": compact[0],
        "comment_id": action.get("id"),
    })


RIVERDALE_TEST_0228_KEY = "riverdale-test-0228-27jul-4e9c13b7"
RIVERDALE_TEST_0228_NAME = (
    "[TEST] 02/28. INT. ŠKOLA - KLUBOVŇA, DEŇ 5 — "
    "BETY, KIKO, ALEX, VERONIKA, KOMPARZ ŠTUDENTI"
)
RIVERDALE_TEST_0228_LIST = "TEST 2 — OBRAZY"
RIVERDALE_TEST_0228_DESC = """<!-- RIVERDALE-SCHEDULE-METADATA:START -->
**ČÍSLO OBRAZU:** 02/28
**ZDROJ:** Riverdale – scenár epizódy 02
**NATÁČACÍ DEŇ:** nenaplánované
**DÁTUM NATÁČANIA:** nenaplánované
**PORADIE DŇA:** nenaplánované
**UNIT:** nenaplánované
**LOKÁCIA:** ŠKOLA – KLUBOVŇA
**POSTAVY:** BETY, KIKO, ALEX, VERONIKA, KOMPARZ ŠTUDENTI
<!-- RIVERDALE-SCHEDULE-METADATA:END -->

#### **Kiko hovorí babám o Patrikovi a Alex hrá na gitare**

### REKVIZITY V KONTEXTE

- **Alexova gitara** — Alex sedí na gauči, brnká na nej a následne hrá a spieva pred Bety, Kikom a Veronikou. Overiť, či ide o rovnaký konkrétny kus ako v obraze 01/39, vrátane farby, popruhu a stavu.

### KONTINUITA

- Alexova gitara môže nadväzovať na obraz 01/39; konkrétny kus treba potvrdiť.
- Automat na jedlo je v obraze 02/28 nepoškodený, pred rozbitím v obraze 02/41.
- Obraz obsahuje spomienkové návraty na obrazy 01/42 a 01/49.

### ODKAZY

Zatiaľ bez pridaných odkazov.

### RUČNÉ DOPLNENIA

### AKCIA A DIALÓGY

*Kiko kráča medzi Bety a Veronikou. Prichádzajú do klubovne. Ešte nejakí študenti sa trúsia von, iní tam ostávajú, čiže si hneď nevšimnú Alexa. Postavia sa k automatu a vyberajú si z neho niečo na jedenie. Bety stláča gombíky ako prvá. Veronika naposledy Bety priznala, že sa správala ako mrcha, nemá chuť sa s ňou veľmi baviť. Veronika to vníma, snaží sa komunikovať aspoň s Kikom, otočí sa naňho.*

> **VERONIKA:**
> **Čo od teba chcel Patrik?**

> **KIKO:**
> **To ani on sám nevie. Ďalší nevyautovaný gay. Mňa už tieto games nebavia.**

> **VERONIKA:**
> **Podľa mňa ťa práve takéto hry vzrušujú. Veronika Kika nachytala a Bety sa na tom pobaví.**

> **BETY:**
> **To je pravda.**

> **KIKO:**
> **Dont judge me. Nejakí študenti odchádzajú, odkryjú im výhľad a tak si všimnú Alexa, ktorý sedí na gauči a brnká si na gitare. (Kikovi sa Alex páči, aj keď je hetero a tiež ho štve že odmietol Bety), tak sa hneď naňho vyškerí a ide k nemu a podpichne ho.**

> **KIKO:**
> **Ou, ou! Tu je náš spievajúci basketbalový heartbreaker. Všetci traja - Bety, Veronika aj Alex urobia grimasu. Bety len zašomre (už s Alexom nekomunikuje ako predtým).**

> **BETY:**
> **Nevšímaj si ho. Prisadnú si k nemu aj Veronika a Bety.**

> **KIKO:**
> **Naopak, všímaj si ma! Stojím za to. Nový song? Alex je v rozpakoch (ešte sa trochu ostýcha hrať a spievať pred ľuďmi a zároveň je to preňho ťažšia situácia, keď je tam zároveň Bety aj Veronika.)**

> **ALEX:**
> **Neviem, len som si tak brnkal....**

> **KIKO:**
> **C’mon! Pozrie na Alexa a ukáže pohľadom na Bety, že je nutné ju rozveseliť.**

> **VERONIKA:**
> **Nenechaj sa prosiť. Alex začne brnkať peknú melódiu, potom potichu spievať, Kiko ho povzbudzuje palcami hore, Alex spieva viac nahlas, znie to veľmi dobre. No Bety sa rozľútostní, prebehnú jej spomienky na otváraciu párty a na Alexovo odmietnutie.**

> **FB 1/42. BETY A ALEX TANCUJÚ NA PLESE:**

> **FB 1/49. PRED DOMOM KEĎ BETTY DOSTALA OD ALEXA ODMIETNUTIE:**

> **A SMUTNO VCHÁDZA DNU:**
> **Bety má slzy v očiach. Alex si to všimne, prestáva hrať a spievať. Citlivo sa spýta.**

> **ALEX:**
> **Si v pohode? Bety sa pousmeje. No je to silený úsmev.**

> **BETY:**
> **Áno, som úplne v pohode. Bety uteká preč.**"""
RIVERDALE_TEST_0228_CHECKLISTS = [
    ("REKVIZITY", [
        "Alexova gitara — Alex na nej hrá a spieva pred Bety, Kikom a Veronikou; overiť možnú kontinuitu rovnakého konkrétneho kusu, farby, popruhu a stavu s obrazom 01/39.",
    ]),
    ("SET", [
        "Škola – klubovňa — zachovať rozmiestnenie priestoru a zariadenia.",
        "Automat na jedlo — Bety stláča gombíky a vyberá si jedlo; v 02/28 musí byť nepoškodený, pred rozbitím v 02/41.",
        "Gauč — Alex na ňom sedí a hrá na gitare.",
        "Komparzová akcia — časť študentov odchádza a odkryje výhľad na Alexa, ďalší zostávajú v klubovni.",
    ]),
    ("INFO Z PORADY", []),
    ("INFO Z NATÁČANIA", []),
]


def riverdale_test_0228_audit(card, target_list):
    checklists = sorted(
        trello_get(f"/cards/{card['id']}/checklists", {
            "fields": "id,name,pos", "checkItems": "all",
        }),
        key=lambda item: item.get("pos", 0),
    )
    checklist_summary = [
        {
            "name": checklist["name"],
            "items": [
                item["name"] for item in sorted(
                    checklist.get("checkItems", []),
                    key=lambda entry: entry.get("pos", 0),
                )
            ],
        }
        for checklist in checklists
    ]
    expected_names = [name for name, _ in RIVERDALE_TEST_0228_CHECKLISTS]
    expected_counts = [len(items) for _, items in RIVERDALE_TEST_0228_CHECKLISTS]
    actual_names = [item["name"] for item in checklist_summary]
    actual_counts = [len(item["items"]) for item in checklist_summary]
    return {
        "card": {
            "id": card["id"],
            "name": card.get("name"),
            "url": card.get("shortUrl"),
            "list_id": card.get("idList"),
            "description_length": len(card.get("desc", "")),
        },
        "target_list": {"id": target_list["id"], "name": target_list["name"]},
        "name_matches": card.get("name") == RIVERDALE_TEST_0228_NAME,
        "description_matches": card.get("desc") == RIVERDALE_TEST_0228_DESC,
        "list_matches": card.get("idList") == target_list["id"],
        "checklists": checklist_summary,
        "checklist_names_match": actual_names == expected_names,
        "checklist_item_counts": actual_counts,
        "checklist_item_counts_match": actual_counts == expected_counts,
        "valid": (
            card.get("name") == RIVERDALE_TEST_0228_NAME
            and card.get("desc") == RIVERDALE_TEST_0228_DESC
            and card.get("idList") == target_list["id"]
            and actual_names == expected_names
            and actual_counts == expected_counts
        ),
    }


@app.route("/api/create-riverdale-test-02-28", methods=["POST"])
def create_riverdale_test_02_28():
    return jsonify({"error": "completed one-off endpoint disabled"}), 410

    if request.headers.get("X-Test-Key") != RIVERDALE_TEST_0228_KEY:
        return jsonify({"error": "forbidden"}), 403

    mode = request.args.get("mode", "dry-run")
    if mode not in {"dry-run", "apply", "audit"}:
        return jsonify({"error": "mode must be dry-run, apply, or audit"}), 400

    board = trello_get("/boards/CzuD55PR", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "open",
    })
    target_lists = [
        item for item in lists if item["name"] == RIVERDALE_TEST_0228_LIST
    ]
    safe_test_lists = [
        {"id": item["id"], "name": item["name"]}
        for item in lists if "TEST" in item["name"].upper()
    ]

    cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,closed",
        "filter": "open",
        "limit": 1000,
    })
    production_cards = [
        card for card in cards
        if re.match(r"^\s*0?2\s*/\s*0?28(?:\D|$)", card.get("name", ""), re.I)
        and not card.get("name", "").lstrip().upper().startswith("[TEST]")
    ]
    test_cards = [
        card for card in cards
        if re.match(
            r"^\s*\[TEST\]\s*0?2\s*/\s*0?28(?:\D|$)",
            card.get("name", ""),
            re.I,
        )
    ]
    exact_test_cards = [
        card for card in test_cards
        if card.get("name") == RIVERDALE_TEST_0228_NAME
    ]
    overview = {
        "status": mode,
        "board": {"id": board["id"], "name": board["name"], "url": board.get("url")},
        "production_02_28": [
            {
                "id": card["id"],
                "name": card["name"],
                "url": card.get("shortUrl"),
                "list_id": card.get("idList"),
            }
            for card in production_cards
        ],
        "production_02_28_count": len(production_cards),
        "safe_test_lists": safe_test_lists,
        "target_list_count": len(target_lists),
        "target_list": (
            {"id": target_lists[0]["id"], "name": target_lists[0]["name"]}
            if len(target_lists) == 1 else None
        ),
        "will_create_target_list": (
            len(target_lists) == 0 and len(safe_test_lists) == 0
        ),
        "test_02_28_count": len(test_cards),
        "exact_test_02_28_count": len(exact_test_cards),
        "duplicate_test_02_28_count": max(0, len(test_cards) - 1),
        "test_02_28": [
            {"id": card["id"], "name": card["name"], "url": card.get("shortUrl")}
            for card in test_cards
        ],
        "intended": {
            "name": RIVERDALE_TEST_0228_NAME,
            "list": RIVERDALE_TEST_0228_LIST,
            "description_length": len(RIVERDALE_TEST_0228_DESC),
            "checklists": [
                {"name": name, "item_count": len(items)}
                for name, items in RIVERDALE_TEST_0228_CHECKLISTS
            ],
        },
    }

    if mode == "dry-run":
        overview["collision_free"] = len(test_cards) <= 1
        overview["ready_to_apply"] = (
            len(production_cards) == 1
            and (
                len(target_lists) == 1
                or (len(target_lists) == 0 and len(safe_test_lists) == 0)
            )
            and len(test_cards) <= 1
        )
        return jsonify(overview)

    if len(production_cards) != 1:
        return jsonify({
            **overview,
            "error": "expected exactly one untouched production 02/28 card",
        }), 409
    if (
        len(target_lists) == 0
        and len(safe_test_lists) == 0
        and mode == "apply"
    ):
        target_lists = [trello_post_body("/lists", {
            "idBoard": board["id"],
            "name": RIVERDALE_TEST_0228_LIST,
            "pos": "bottom",
        })]
    if len(target_lists) != 1:
        return jsonify({
            **overview,
            "error": (
                "expected exactly one TEST 2 — OBRAZY list, or no safe test "
                "list so apply can create it"
            ),
        }), 409
    if len(test_cards) > 1:
        return jsonify({
            **overview,
            "error": "ambiguous or duplicate [TEST] 02/28 cards",
        }), 409

    target_list = target_lists[0]
    if mode == "apply":
        if test_cards:
            card = test_cards[0]
            card = trello_put_body(f"/cards/{card['id']}", {
                "name": RIVERDALE_TEST_0228_NAME,
                "desc": RIVERDALE_TEST_0228_DESC,
                "idList": target_list["id"],
            })
        else:
            card = trello_post_body("/cards", {
                "idList": target_list["id"],
                "name": RIVERDALE_TEST_0228_NAME,
                "desc": RIVERDALE_TEST_0228_DESC,
                "pos": "bottom",
            })

        existing_checklists = trello_get(f"/cards/{card['id']}/checklists", {
            "fields": "id,name,pos", "checkItems": "all",
        })
        for checklist_name, desired_items in RIVERDALE_TEST_0228_CHECKLISTS:
            matching = [
                item for item in existing_checklists
                if item.get("name") == checklist_name
            ]
            if len(matching) > 1:
                return jsonify({
                    **overview,
                    "error": f"duplicate checklist: {checklist_name}",
                    "card_url": card.get("shortUrl"),
                }), 409
            if matching:
                checklist = matching[0]
            else:
                checklist = trello_post_body("/checklists", {
                    "idCard": card["id"],
                    "name": checklist_name,
                    "pos": "bottom",
                })
                checklist["checkItems"] = []
                existing_checklists.append(checklist)
            existing_names = {
                item.get("name") for item in checklist.get("checkItems", [])
            }
            for item_name in desired_items:
                if item_name not in existing_names:
                    trello_post_body(
                        f"/checklists/{checklist['id']}/checkItems",
                        {"name": item_name, "pos": "bottom"},
                    )

    current_cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,closed",
        "filter": "open",
        "limit": 1000,
    })
    current_test_cards = [
        card for card in current_cards
        if re.match(
            r"^\s*\[TEST\]\s*0?2\s*/\s*0?28(?:\D|$)",
            card.get("name", ""),
            re.I,
        )
    ]
    if len(current_test_cards) != 1:
        return jsonify({
            **overview,
            "error": "audit expected exactly one [TEST] 02/28 card",
            "audit_test_card_count": len(current_test_cards),
        }), 409

    current_card = trello_get(f"/cards/{current_test_cards[0]['id']}", {
        "fields": "id,name,desc,idList,shortUrl,closed",
    })
    audit = riverdale_test_0228_audit(current_card, target_list)
    status_code = 200 if audit["valid"] else 409
    return jsonify({
        "status": "applied-and-audited" if mode == "apply" else "audit",
        "board": overview["board"],
        "production_02_28_untouched": production_cards[0]["id"] != current_card["id"],
        "test_02_28_count": len(current_test_cards),
        "duplicate_test_02_28_count": max(0, len(current_test_cards) - 1),
        "audit": audit,
    }), status_code


RIVERDALE_GUITAR_LINK_KEY = "riverdale-guitar-link-27jul-8f2c5d41"
RIVERDALE_GUITAR_TEST_LIST = "TEST 2 — REGISTER KONTINUITY"
RIVERDALE_GUITAR_TEST_NAME = "[TEST] Alexova gitara"


def normalize_riverdale_prop_identity(value):
    folded_value = unicodedata.normalize("NFKD", value or "")
    folded_value = "".join(
        character for character in folded_value
        if not unicodedata.combining(character)
    ).casefold()
    folded_value = re.sub(r"\[[^\]]+\]", " ", folded_value)
    folded_value = re.sub(r"[^a-z0-9]+", " ", folded_value)
    return re.sub(r"\s+", " ", folded_value).strip()


def riverdale_guitar_candidates(cards, lists_by_id):
    aliases = ("alexova gitara", "gitara alexa", "alex guitar")
    candidates = []
    for card in cards:
        name_identity = normalize_riverdale_prop_identity(card.get("name", ""))
        description_identity = normalize_riverdale_prop_identity(card.get("desc", ""))
        name_match = any(
            name_identity == alias
            or name_identity.startswith(f"{alias} ")
            or f" {alias} " in f" {name_identity} "
            for alias in aliases
        )
        explicit_identity = any(
            f"identita {alias}" in description_identity for alias in aliases
        )
        if not name_match and not explicit_identity:
            continue
        candidates.append({
            **card,
            "list_name": lists_by_id.get(card.get("idList"), {}).get("name"),
            "matched_by": (
                "name-and-identity" if name_match and explicit_identity
                else "name" if name_match else "identity"
            ),
        })
    return candidates


def riverdale_guitar_check_item(card_url):
    return (
        "<…> Alexova gitara — Alex na nej sedí na gauči, hrá a spieva "
        "pred Bety, Kikom a Veronikou | ← 01/39: Alex na nej hrá na terase "
        "| TU: gitara je funkčná a nepoškodená; overiť rovnaký konkrétny "
        "kus, farbu a popruh | → ďalší potvrdený obraz neurčený | KARTA: "
        f"{card_url}"
    )


def trello_card_has_attachment(card_id, target_url):
    attachments = trello_get(f"/cards/{card_id}/attachments", {
        "fields": "id,name,url", "limit": 1000,
    })
    normalized_target = (target_url or "").rstrip("/")
    return any(
        (attachment.get("url") or "").rstrip("/") == normalized_target
        for attachment in attachments
    )


@app.route("/api/link-riverdale-test-02-28-guitar", methods=["POST"])
def link_riverdale_test_02_28_guitar():
    return jsonify({"error": "completed one-off endpoint disabled"}), 410

    if request.headers.get("X-Test-Key") != RIVERDALE_GUITAR_LINK_KEY:
        return jsonify({"error": "forbidden"}), 403
    mode = request.args.get("mode", "dry-run")
    if mode not in {"dry-run", "apply", "audit"}:
        return jsonify({"error": "mode must be dry-run, apply, or audit"}), 400

    board = trello_get("/boards/CzuD55PR", {"fields": "id,name,url"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "open",
    })
    lists_by_id = {item["id"]: item for item in lists}
    cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,closed",
        "filter": "open", "limit": 1000,
    })
    production_cards = [
        card for card in cards
        if re.match(r"^\s*0?2\s*/\s*0?28(?:\D|$)", card.get("name", ""), re.I)
        and not card.get("name", "").lstrip().upper().startswith("[TEST]")
    ]
    test_scenes = [
        card for card in cards
        if re.match(
            r"^\s*\[TEST\]\s*0?2\s*/\s*0?28(?:\D|$)",
            card.get("name", ""),
            re.I,
        )
    ]
    scene_ids = {card["id"] for card in production_cards + test_scenes}
    prop_candidates = riverdale_guitar_candidates(
        [card for card in cards if card["id"] not in scene_ids],
        lists_by_id,
    )
    safe_registry_lists = [
        item for item in lists
        if "TEST" in item["name"].upper()
        and any(
            marker in normalize_riverdale_prop_identity(item["name"])
            for marker in ("rekviz", "register", "kontin", "nadv")
        )
    ]
    exact_registry_lists = [
        item for item in lists if item["name"] == RIVERDALE_GUITAR_TEST_LIST
    ]
    overview = {
        "status": mode,
        "board": {"id": board["id"], "name": board["name"], "url": board.get("url")},
        "production_02_28_count": len(production_cards),
        "production_02_28": [
            {"id": card["id"], "name": card["name"], "url": card.get("shortUrl")}
            for card in production_cards
        ],
        "test_scene_02_28_count": len(test_scenes),
        "test_scene_02_28": [
            {"id": card["id"], "name": card["name"], "url": card.get("shortUrl")}
            for card in test_scenes
        ],
        "guitar_candidate_count": len(prop_candidates),
        "guitar_duplicate_count": max(0, len(prop_candidates) - 1),
        "guitar_candidates": [
            {
                "id": card["id"], "name": card["name"],
                "url": card.get("shortUrl"), "list": card.get("list_name"),
                "matched_by": card.get("matched_by"),
            }
            for card in prop_candidates
        ],
        "safe_registry_lists": [
            {"id": item["id"], "name": item["name"]}
            for item in safe_registry_lists
        ],
        "exact_test_registry_list_count": len(exact_registry_lists),
        "will_create_test_prop_card": len(prop_candidates) == 0,
        "will_create_test_registry_list": (
            len(prop_candidates) == 0
            and len(safe_registry_lists) == 0
        ),
        "intended_item_template": (
            riverdale_guitar_check_item(prop_candidates[0].get("shortUrl"))
            if len(prop_candidates) == 1
            else riverdale_guitar_check_item("<skutočný Trello shortUrl po vytvorení>")
        ),
    }
    overview["ready_to_apply"] = (
        len(production_cards) == 1
        and len(test_scenes) == 1
        and len(prop_candidates) <= 1
        and (
            len(prop_candidates) == 1
            or len(exact_registry_lists) == 1
            or len(safe_registry_lists) == 1
            or len(safe_registry_lists) == 0
        )
    )
    if mode == "dry-run":
        return jsonify(overview)

    if len(production_cards) != 1 or len(test_scenes) != 1:
        return jsonify({
            **overview,
            "error": "expected exactly one production and one test 02/28 scene",
        }), 409
    if len(prop_candidates) > 1:
        return jsonify({
            **overview,
            "error": "ambiguous Alexova gitara identity; duplicates must be resolved first",
        }), 409

    production_before = {
        field: production_cards[0].get(field)
        for field in ("id", "name", "desc", "idList", "shortUrl", "closed")
    }
    scene = test_scenes[0]
    created_prop_card = False
    created_registry_list = False

    if prop_candidates:
        prop_card = prop_candidates[0]
    elif mode == "audit":
        return jsonify({
            **overview,
            "error": "audit cannot find an Alexova gitara identity card",
        }), 409
    else:
        if len(exact_registry_lists) == 1:
            registry_list = exact_registry_lists[0]
        elif len(safe_registry_lists) == 1:
            registry_list = safe_registry_lists[0]
        elif len(safe_registry_lists) == 0:
            registry_list = trello_post_body("/lists", {
                "idBoard": board["id"],
                "name": RIVERDALE_GUITAR_TEST_LIST,
                "pos": "bottom",
            })
            created_registry_list = True
        else:
            return jsonify({
                **overview,
                "error": "multiple safe test registry lists; target is ambiguous",
            }), 409
        prop_card = trello_post_body("/cards", {
            "idList": registry_list["id"],
            "name": RIVERDALE_GUITAR_TEST_NAME,
            "desc": (
                "**IDENTITA:** `Alexova gitara`\n"
                "**STAV:** TESTOVACIA hlavná kontinuitná karta\n\n"
                "### SÚVISIACE OBRAZY\n\n"
                "- 01/39 — Alex na gitare hrá na terase.\n"
                f"- [TEST] 02/28 — {scene['shortUrl']}\n\n"
                "### KONTINUITA\n\n"
                "V 02/28 je gitara funkčná a nepoškodená. Overiť rovnaký "
                "konkrétny kus, farbu a popruh ako v 01/39."
            ),
            "pos": "bottom",
        })
        created_prop_card = True

    expected_item = riverdale_guitar_check_item(prop_card["shortUrl"])
    if mode == "apply":
        checklists = trello_get(f"/cards/{scene['id']}/checklists", {
            "fields": "id,name,pos", "checkItems": "all",
        })
        prop_checklists = [
            checklist for checklist in checklists
            if checklist.get("name") == "REKVIZITY"
        ]
        if len(prop_checklists) != 1:
            return jsonify({
                **overview,
                "error": "expected exactly one REKVIZITY checklist",
                "prop_card_url": prop_card.get("shortUrl"),
            }), 409
        checklist = prop_checklists[0]
        guitar_items = [
            item for item in checklist.get("checkItems", [])
            if "alexova gitara" in normalize_riverdale_prop_identity(item.get("name"))
        ]
        if len(guitar_items) > 1:
            return jsonify({
                **overview,
                "error": "duplicate Alexova gitara checklist items",
                "prop_card_url": prop_card.get("shortUrl"),
            }), 409
        if guitar_items:
            if guitar_items[0].get("name") != expected_item:
                trello_put_body(
                    f"/cards/{scene['id']}/checkItem/{guitar_items[0]['id']}",
                    {"name": expected_item},
                )
        else:
            trello_post_body(
                f"/checklists/{checklist['id']}/checkItems",
                {"name": expected_item, "pos": "bottom"},
            )

        if not trello_card_has_attachment(scene["id"], prop_card["shortUrl"]):
            trello_post_body(f"/cards/{scene['id']}/attachments", {
                "url": prop_card["shortUrl"], "name": "Hlavná karta — Alexova gitara",
            })
        if not trello_card_has_attachment(prop_card["id"], scene["shortUrl"]):
            trello_post_body(f"/cards/{prop_card['id']}/attachments", {
                "url": scene["shortUrl"], "name": "Testovací obraz 02/28",
            })

    current_production = trello_get(f"/cards/{production_cards[0]['id']}", {
        "fields": "id,name,desc,idList,shortUrl,closed",
    })
    production_after = {
        field: current_production.get(field)
        for field in ("id", "name", "desc", "idList", "shortUrl", "closed")
    }
    current_scene = trello_get(f"/cards/{scene['id']}", {
        "fields": "id,name,desc,idList,shortUrl,closed",
    })
    current_checklists = trello_get(f"/cards/{scene['id']}/checklists", {
        "fields": "id,name,pos", "checkItems": "all",
    })
    current_prop_checklists = [
        checklist for checklist in current_checklists
        if checklist.get("name") == "REKVIZITY"
    ]
    current_guitar_items = [
        item for checklist in current_prop_checklists
        for item in checklist.get("checkItems", [])
        if "alexova gitara" in normalize_riverdale_prop_identity(item.get("name"))
    ]
    refreshed_cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,closed",
        "filter": "open", "limit": 1000,
    })
    refreshed_candidates = riverdale_guitar_candidates(
        [
            card for card in refreshed_cards
            if card["id"] not in {production_cards[0]["id"], scene["id"]}
        ],
        {
            item["id"]: item
            for item in trello_get(f"/boards/{board['id']}/lists", {
                "fields": "id,name,pos,closed", "filter": "open",
            })
        },
    )
    scene_links_prop = trello_card_has_attachment(
        current_scene["id"], prop_card["shortUrl"]
    )
    prop_links_scene = trello_card_has_attachment(
        prop_card["id"], current_scene["shortUrl"]
    )
    item_matches = (
        len(current_guitar_items) == 1
        and current_guitar_items[0].get("name") == expected_item
    )
    valid = (
        production_after == production_before
        and len(refreshed_candidates) == 1
        and refreshed_candidates[0]["id"] == prop_card["id"]
        and item_matches
        and scene_links_prop
        and prop_links_scene
    )
    return jsonify({
        "status": "applied-and-audited" if mode == "apply" else "audit",
        "board": overview["board"],
        "created_test_prop_card": created_prop_card,
        "created_test_registry_list": created_registry_list,
        "production_02_28_untouched": production_after == production_before,
        "guitar_candidate_count": len(refreshed_candidates),
        "guitar_duplicate_count": max(0, len(refreshed_candidates) - 1),
        "prop_card": {
            "id": prop_card["id"],
            "name": prop_card.get("name"),
            "url": prop_card.get("shortUrl"),
            "list": next(
                (
                    item["name"] for item in lists
                    if item["id"] == prop_card.get("idList")
                ),
                RIVERDALE_GUITAR_TEST_LIST if created_registry_list else None,
            ),
        },
        "scene_card": {
            "id": current_scene["id"],
            "name": current_scene.get("name"),
            "url": current_scene.get("shortUrl"),
        },
        "checklist_item": (
            current_guitar_items[0].get("name")
            if len(current_guitar_items) == 1 else None
        ),
        "checklist_item_matches": item_matches,
        "scene_links_prop": scene_links_prop,
        "prop_links_scene": prop_links_scene,
        "valid": valid,
    }), 200 if valid else 409


CIERNY_KAMEN_AUDIT_KEY = "cierny-kamen-audit-27jul-31e7c4a9"


def cierny_kamen_audit_folded(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    ).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def cierny_kamen_scene_name_info(name):
    test_match = re.match(
        r"^\s*(?P<tags>(?:\[[^\]]*test[^\]]*\]\s*)+)"
        r"(?P<episode>\d+)\s*/\s*(?P<scene>\d+)\s*(?P<tag>[A-Za-z]*)\b",
        name or "",
        flags=re.I,
    )
    production_match = re.match(
        r"^\s*(?P<episode>\d+)\s*/\s*(?P<scene>\d+)\s*(?P<tag>[A-Za-z]*)\b",
        name or "",
        flags=re.I,
    )
    match = test_match or production_match
    if not match:
        return None
    return {
        "scene_id": (
            f"{int(match.group('episode')):02d}/"
            f"{int(match.group('scene')):02d}"
            f"{(match.group('tag') or '').upper()}"
        ),
        "test": bool(test_match),
    }


@app.route("/api/audit-cierny-kamen-import", methods=["GET"])
def audit_cierny_kamen_import():
    return jsonify({"error": "completed read-only endpoint disabled"}), 410

    if request.headers.get("X-Audit-Key") != CIERNY_KAMEN_AUDIT_KEY:
        return jsonify({"error": "forbidden"}), 403

    board = trello_get("/boards/CzuD55PR", {"fields": "id,name,url,closed"})
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "all",
    })
    labels = trello_get(f"/boards/{board['id']}/labels", {
        "fields": "id,name,color", "limit": 1000,
    })
    cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,closed",
        "filter": "all", "limit": 1000,
    })
    lists_by_id = {item["id"]: item for item in lists}

    list_counts = {
        item["id"]: {"open": 0, "closed": 0, "total": 0}
        for item in lists
    }
    for card in cards:
        counts = list_counts.setdefault(
            card.get("idList"), {"open": 0, "closed": 0, "total": 0}
        )
        counts["closed" if card.get("closed") else "open"] += 1
        counts["total"] += 1

    scene_cards = []
    for card in cards:
        info = cierny_kamen_scene_name_info(card.get("name", ""))
        if not info:
            continue
        scene_cards.append({
            **card,
            **info,
            "list_name": lists_by_id.get(card.get("idList"), {}).get("name"),
            "list_closed": bool(
                lists_by_id.get(card.get("idList"), {}).get("closed")
            ),
            "active": (
                not card.get("closed")
                and not lists_by_id.get(card.get("idList"), {}).get("closed")
            ),
        })
    production_scenes = [card for card in scene_cards if not card["test"]]
    test_scenes = [card for card in scene_cards if card["test"]]

    def duplicate_scene_ids(items):
        by_id = {}
        for card in items:
            by_id.setdefault(card["scene_id"], []).append(card)
        return [
            {
                "scene_id": scene_id,
                "count": len(group),
                "cards": [
                    {
                        "name": card["name"], "url": card.get("shortUrl"),
                        "list": card.get("list_name"),
                        "card_closed": card.get("closed"),
                        "list_closed": card.get("list_closed"),
                        "active": card.get("active"),
                    }
                    for card in group
                ],
            }
            for scene_id, group in sorted(by_id.items())
            if len(group) > 1
        ]

    def list_name_has(item, markers):
        folded_name = cierny_kamen_audit_folded(item.get("name", ""))
        return any(marker in folded_name for marker in markers)

    open_lists = [item for item in lists if not item.get("closed")]
    scene_target_candidates = [
        item for item in open_lists
        if list_name_has(item, ("scenare", "obrazy", "vsetky epizody"))
        and "test" not in cierny_kamen_audit_folded(item["name"])
        and not list_name_has(item, ("natocene", "todo", "register", "rekviz"))
    ]
    prop_registry_candidates = [
        item for item in open_lists
        if list_name_has(item, ("register rekviz", "nadvazne rekviz", "rekvizity"))
        and "test" not in cierny_kamen_audit_folded(item["name"])
    ]
    set_registry_candidates = [
        item for item in open_lists
        if list_name_has(item, (
            "register set", "nadvazny set", "nadvazne set",
            "set register", "scenograf",
        ))
        and "test" not in cierny_kamen_audit_folded(item["name"])
    ]
    test_lists = [
        item for item in lists
        if "test" in cierny_kamen_audit_folded(item["name"])
    ]

    desired_labels = {}
    for desired_name in ("Nadväzná rekvizita", "Nadväzný set", "Auto"):
        desired_folded = cierny_kamen_audit_folded(desired_name)
        matches = [
            label for label in labels
            if cierny_kamen_audit_folded(label.get("name")) == desired_folded
        ]
        desired_labels[desired_name] = {
            "count": len(matches),
            "matches": [
                {"id": label["id"], "name": label.get("name"),
                 "color": label.get("color")}
                for label in matches
            ],
        }

    registry_list_ids = {
        item["id"] for item in prop_registry_candidates + set_registry_candidates
    }
    registry_cards = [
        card for card in cards
        if card.get("idList") in registry_list_ids
    ]
    active_registry_cards = [
        card for card in registry_cards
        if not card.get("closed")
        and not lists_by_id.get(card.get("idList"), {}).get("closed")
    ]
    archived_registry_cards = [
        card for card in registry_cards if card not in active_registry_cards
    ]
    registry_identities = {}
    for card in registry_cards:
        identity_match = re.search(
            r"\*\*IDENTITA:\*\*\s*`?([^`\n]+)",
            card.get("desc", ""),
            flags=re.I,
        )
        identity = (
            identity_match.group(1).strip()
            if identity_match else re.sub(
                r"^\s*(?:\[[^\]]+\]\s*)+", "", card.get("name", "")
            ).strip()
        )
        identity_key = cierny_kamen_audit_folded(identity)
        registry_identities.setdefault(identity_key, []).append({
            "id": card["id"], "name": card["name"], "url": card.get("shortUrl"),
            "list": lists_by_id.get(card.get("idList"), {}).get("name"),
            "identity": identity,
        })
    registry_duplicates = [
        {"identity": identity, "count": len(group), "cards": group}
        for identity, group in sorted(registry_identities.items())
        if identity and len(group) > 1
    ]

    return jsonify({
        "status": "read-only-audit",
        "board": {
            "id": board["id"], "name": board["name"], "url": board.get("url"),
            "closed": board.get("closed"),
        },
        "cards_total": len(cards),
        "cards_open": sum(not card.get("closed") for card in cards),
        "cards_closed": sum(bool(card.get("closed")) for card in cards),
        "lists": [
            {
                "id": item["id"], "name": item["name"],
                "list_closed": item.get("closed"), "pos": item.get("pos"),
                "cards_open": list_counts.get(item["id"], {}).get("open", 0),
                "cards_closed": list_counts.get(item["id"], {}).get("closed", 0),
                "cards_total": list_counts.get(item["id"], {}).get("total", 0),
            }
            for item in sorted(lists, key=lambda entry: entry.get("pos", 0))
        ],
        "labels": [
            {"id": label["id"], "name": label.get("name"),
             "color": label.get("color")}
            for label in labels
        ],
        "desired_labels": desired_labels,
        "scene_cards": {
            "production_total": len(production_scenes),
            "production_active": sum(bool(card.get("active")) for card in production_scenes),
            "production_card_archived": sum(
                bool(card.get("closed")) for card in production_scenes
            ),
            "production_in_archived_list": sum(
                bool(card.get("list_closed")) and not card.get("closed")
                for card in production_scenes
            ),
            "test_total": len(test_scenes),
            "test_active": sum(bool(card.get("active")) for card in test_scenes),
            "test_card_archived": sum(
                bool(card.get("closed")) for card in test_scenes
            ),
            "test_in_archived_list": sum(
                bool(card.get("list_closed")) and not card.get("closed")
                for card in test_scenes
            ),
            "production_sample": [
                {
                    "scene_id": card["scene_id"], "name": card["name"],
                    "url": card.get("shortUrl"), "list": card.get("list_name"),
                    "card_closed": card.get("closed"),
                    "list_closed": card.get("list_closed"),
                    "active": card.get("active"),
                }
                for card in production_scenes[:30]
            ],
            "test_cards": [
                {
                    "scene_id": card["scene_id"], "name": card["name"],
                    "url": card.get("shortUrl"), "list": card.get("list_name"),
                    "card_closed": card.get("closed"),
                    "list_closed": card.get("list_closed"),
                    "active": card.get("active"),
                }
                for card in test_scenes
            ],
            "production_duplicate_ids": duplicate_scene_ids(production_scenes),
            "all_duplicate_ids": duplicate_scene_ids(scene_cards),
        },
        "targets": {
            "scene_candidates": [
                {"id": item["id"], "name": item["name"]}
                for item in scene_target_candidates
            ],
            "prop_registry_candidates": [
                {"id": item["id"], "name": item["name"]}
                for item in prop_registry_candidates
            ],
            "set_registry_candidates": [
                {"id": item["id"], "name": item["name"]}
                for item in set_registry_candidates
            ],
            "test_lists": [
                {"id": item["id"], "name": item["name"],
                "list_closed": item.get("closed"),
                "cards_open": list_counts.get(item["id"], {}).get("open", 0),
                "cards_closed": list_counts.get(item["id"], {}).get("closed", 0),
                "cards_total": list_counts.get(item["id"], {}).get("total", 0)}
                for item in test_lists
            ],
        },
        "registries": {
            "total_cards": len(registry_cards),
            "active_cards": len(active_registry_cards),
            "archived_cards": len(archived_registry_cards),
            "unique_identities": len(registry_identities),
            "duplicate_identities": registry_duplicates,
            "cards_sample": [
                {
                    "name": card["name"], "url": card.get("shortUrl"),
                    "list": lists_by_id.get(card.get("idList"), {}).get("name"),
                    "card_closed": card.get("closed"),
                    "list_closed": lists_by_id.get(
                        card.get("idList"), {}
                    ).get("closed"),
                }
                for card in registry_cards[:100]
            ],
        },
    })


CIERNY_KAMEN_CLEANUP_KEY = "cierny-kamen-cleanup-27jul-4bd36e81"
CIERNY_KAMEN_BOARD_REF = "CzuD55PR"
CIERNY_KAMEN_PROP_REGISTRY_LIST_ID = "6a5cbe13db1f160d97ae6474"
CIERNY_KAMEN_EXPECTED_OLD_SCENE_CARDS = 373
CIERNY_KAMEN_EXPECTED_OLD_PROP_CARDS = 93
CIERNY_KAMEN_TEST_LIST_NAME = "TEST 2 — OBRAZY"


def cierny_kamen_cleanup_snapshot():
    board = trello_get(
        f"/boards/{CIERNY_KAMEN_BOARD_REF}",
        {"fields": "id,name,url,closed,shortLink"},
    )
    if board.get("shortLink") != CIERNY_KAMEN_BOARD_REF:
        raise RuntimeError("Cierny Kamen cleanup resolved an unexpected board")

    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "all",
    })
    cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,idList,shortUrl,closed",
        "filter": "all", "limit": 1000,
    })
    lists_by_id = {item["id"]: item for item in lists}

    scene_cards = []
    active_production_cards = []
    for card in cards:
        scene_info = cierny_kamen_scene_name_info(card.get("name", ""))
        if not scene_info:
            continue
        enriched = {
            **card,
            **scene_info,
            "list_name": lists_by_id.get(card.get("idList"), {}).get("name"),
            "list_closed": bool(
                lists_by_id.get(card.get("idList"), {}).get("closed")
            ),
        }
        enriched["active"] = (
            not card.get("closed") and not enriched["list_closed"]
        )
        scene_cards.append(enriched)
        if enriched["active"] and not enriched["test"]:
            active_production_cards.append(enriched)

    prop_cards = [
        card for card in cards
        if card.get("idList") == CIERNY_KAMEN_PROP_REGISTRY_LIST_ID
    ]
    prop_list = lists_by_id.get(CIERNY_KAMEN_PROP_REGISTRY_LIST_ID)
    active_prop_cards = [
        card for card in prop_cards
        if not card.get("closed")
        and prop_list
        and not prop_list.get("closed")
    ]
    test_lists = [
        item for item in lists
        if cierny_kamen_audit_folded(item.get("name"))
        == cierny_kamen_audit_folded(CIERNY_KAMEN_TEST_LIST_NAME)
    ]
    card_counts_by_list = {}
    for card in cards:
        card_counts_by_list[card.get("idList")] = (
            card_counts_by_list.get(card.get("idList"), 0) + 1
        )

    return {
        "board": board,
        "lists": lists,
        "cards": cards,
        "scene_cards": sorted(scene_cards, key=lambda card: card["id"]),
        "active_production_cards": active_production_cards,
        "prop_cards": sorted(prop_cards, key=lambda card: card["id"]),
        "active_prop_cards": active_prop_cards,
        "test_lists": test_lists,
        "card_counts_by_list": card_counts_by_list,
    }


def cierny_kamen_cleanup_summary(snapshot):
    scene_cards = snapshot["scene_cards"]
    prop_cards = snapshot["prop_cards"]
    return {
        "board": {
            "id": snapshot["board"]["id"],
            "name": snapshot["board"].get("name"),
            "url": snapshot["board"].get("url"),
        },
        "scene_cards_remaining": len(scene_cards),
        "production_scenes_remaining": sum(
            not card["test"] for card in scene_cards
        ),
        "test_scenes_remaining": sum(card["test"] for card in scene_cards),
        "active_production_scenes": len(
            snapshot["active_production_cards"]
        ),
        "prop_registry_cards_remaining": len(prop_cards),
        "active_prop_registry_cards": len(snapshot["active_prop_cards"]),
        "test_lists": [
            {
                "id": item["id"],
                "name": item.get("name"),
                "closed": bool(item.get("closed")),
                "cards": snapshot["card_counts_by_list"].get(item["id"], 0),
            }
            for item in snapshot["test_lists"]
        ],
        "scene_sample": [
            {
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
                "list": card.get("list_name"),
                "card_closed": bool(card.get("closed")),
                "list_closed": card.get("list_closed"),
            }
            for card in scene_cards[:10]
        ],
        "prop_sample": [
            {
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
                "card_closed": bool(card.get("closed")),
            }
            for card in prop_cards[:10]
        ],
    }


def cierny_kamen_cleanup_guard(snapshot):
    if snapshot["board"].get("closed"):
        return "board is archived"
    if snapshot["active_production_cards"]:
        return "active production scene cards exist; refusing cleanup"
    if snapshot["active_prop_cards"]:
        return "active prop registry cards exist; refusing cleanup"
    if len(snapshot["scene_cards"]) > CIERNY_KAMEN_EXPECTED_OLD_SCENE_CARDS:
        return "scene target count exceeds audited maximum"
    if len(snapshot["prop_cards"]) > CIERNY_KAMEN_EXPECTED_OLD_PROP_CARDS:
        return "prop target count exceeds audited maximum"
    return None


@app.route("/api/cleanup-cierny-kamen-old-data", methods=["POST"])
def cleanup_cierny_kamen_old_data():
    return jsonify({"error": "completed cleanup endpoint disabled"}), 410

    if request.headers.get("X-Cleanup-Key") != CIERNY_KAMEN_CLEANUP_KEY:
        return jsonify({"error": "forbidden"}), 403

    mode = request.args.get("mode", "dry-run").strip().casefold()
    scope = request.args.get("scope", "all").strip().casefold()
    try:
        limit = int(request.args.get("limit", "25"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    if mode not in {"dry-run", "apply", "audit"}:
        return jsonify({"error": "mode must be dry-run, apply, or audit"}), 400
    if scope not in {"all", "scenes", "registry", "finalize"}:
        return jsonify({
            "error": "scope must be all, scenes, registry, or finalize"
        }), 400
    if limit < 1 or limit > 25:
        return jsonify({"error": "limit must be between 1 and 25"}), 400

    before = cierny_kamen_cleanup_snapshot()
    guard_error = cierny_kamen_cleanup_guard(before)
    before_summary = cierny_kamen_cleanup_summary(before)
    if guard_error:
        return jsonify({
            "status": "blocked",
            "error": guard_error,
            "before": before_summary,
        }), 409

    if mode in {"dry-run", "audit"}:
        clean = (
            not before["scene_cards"]
            and not before["prop_cards"]
            and not any(
                not item.get("closed") for item in before["test_lists"]
            )
        )
        return jsonify({
            "status": mode,
            "clean": clean,
            "writes": 0,
            "before": before_summary,
        }), 200

    deleted = []
    archived_lists = []
    if scope in {"all", "scenes"}:
        for card in before["scene_cards"][:limit]:
            trello_delete(f"/cards/{card['id']}")
            deleted.append({
                "kind": "scene",
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
            })
    elif scope == "registry":
        for card in before["prop_cards"][:limit]:
            trello_delete(f"/cards/{card['id']}")
            deleted.append({
                "kind": "prop",
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
            })
    elif scope == "finalize":
        if before["scene_cards"] or before["prop_cards"]:
            return jsonify({
                "status": "blocked",
                "error": "cards remain; finalize is not allowed yet",
                "before": before_summary,
            }), 409
        for item in before["test_lists"]:
            if item.get("closed"):
                continue
            if before["card_counts_by_list"].get(item["id"], 0):
                return jsonify({
                    "status": "blocked",
                    "error": "test list is not empty",
                    "list_id": item["id"],
                    "before": before_summary,
                }), 409
            trello_put_body(f"/lists/{item['id']}", {"closed": "true"})
            archived_lists.append({
                "id": item["id"], "name": item.get("name"),
            })

    after = cierny_kamen_cleanup_snapshot()
    return jsonify({
        "status": "applied",
        "scope": scope,
        "deleted": deleted,
        "deleted_count": len(deleted),
        "archived_lists": archived_lists,
        "before": before_summary,
        "after": cierny_kamen_cleanup_summary(after),
    }), 200


CIERNY_KAMEN_IMPORT_KEY = "cierny-kamen-full-import-27jul-8e31f7c2"
CIERNY_KAMEN_IMPORT_CHECKLISTS = [
    "REKVIZITY",
    "SET",
    "INFO Z PORADY",
    "INFO Z NATÁČANIA",
    "OTÁZKY NA PORADU",
]


def cierny_kamen_import_payload():
    from cierny_kamen_prop_identities import apply_identity_map
    from cierny_kamen_split_0440 import augment_payload
    from cierny_kamen_split_0535flash import augment_payload as augment_payload_0535flash
    from cierny_kamen_ep07_10_import import authoritative_payload
    from cierny_kamen_ep11_13_import import authoritative_payload as authoritative_payload_11_13

    path = Path(__file__).with_name("cierny_kamen_pdf_payload.json")
    return authoritative_payload_11_13(authoritative_payload(augment_payload_0535flash(augment_payload(apply_identity_map(
        json.loads(path.read_text(encoding="utf-8"))
    )))))


def cierny_kamen_import_state(payload):
    board = trello_get(
        f"/boards/{payload['board_ref']}",
        {"fields": "id,name,url,closed,shortLink"},
    )
    lists = trello_get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "all",
    })
    labels = trello_get(f"/boards/{board['id']}/labels", {
        "fields": "id,name,color", "limit": 1000,
    })
    cards = trello_get(f"/boards/{board['id']}/cards", {
        "fields": "id,name,desc,idList,shortUrl,closed,idLabels",
        "filter": "all", "limit": 1000,
    })
    return {
        "board": board,
        "lists": lists,
        "labels": labels,
        "cards": cards,
        "lists_by_id": {item["id"]: item for item in lists},
    }


def cierny_kamen_exact_named(items, name, include_closed=False):
    expected = cierny_kamen_audit_folded(name)
    return [
        item for item in items
        if cierny_kamen_audit_folded(item.get("name")) == expected
        and (include_closed or not item.get("closed"))
    ]


def cierny_kamen_registry_marker(kind, key):
    return f"<!-- CIERNY-KAMEN-REGISTRY:{kind}:{key} -->"


def cierny_kamen_registry_cards(state, kind, payload):
    registry = (
        payload["prop_registry"]
        if kind == "PROP" else payload["set_registry"]
    )
    result = {}
    duplicates = {}
    for key in registry:
        marker = cierny_kamen_registry_marker(kind, key)
        matches = [
            card for card in state["cards"]
            if marker in (card.get("desc") or "")
        ]
        if len(matches) == 1:
            result[key] = matches[0]
        elif len(matches) > 1:
            duplicates[key] = matches
    return result, duplicates


def cierny_kamen_scene_cards_by_id(state):
    by_id = {}
    for card in state["cards"]:
        info = cierny_kamen_scene_name_info(card.get("name", ""))
        if not info or info["test"]:
            continue
        by_id.setdefault(info["scene_id"], []).append(card)
    return by_id


def cierny_kamen_target_audit(payload, state):
    scene_lists = cierny_kamen_exact_named(
        state["lists"], payload["scene_list_name"]
    )
    prop_lists = cierny_kamen_exact_named(
        state["lists"], payload["prop_registry_list_name"]
    )
    set_lists = cierny_kamen_exact_named(
        state["lists"], payload["set_registry_list_name"]
    )
    desired_labels = {}
    for label_name in ("Nadväzná rekvizita", "Nadväzný set", "Auto"):
        matches = cierny_kamen_exact_named(state["labels"], label_name, True)
        desired_labels[label_name] = matches
    scene_cards = cierny_kamen_scene_cards_by_id(state)
    source_ids = {scene["scene_id"] for scene in payload["scenes"]}
    collisions = {
        scene_id: [
            {
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
                "list": state["lists_by_id"].get(
                    card.get("idList"), {}
                ).get("name"),
            }
            for card in matches
        ]
        for scene_id, matches in scene_cards.items()
        if scene_id in source_ids and (
            len(matches) > 1
            or not all(
                "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->"
                in (card.get("desc") or "")
                for card in matches
            )
        )
    }
    blockers = []
    if len(scene_lists) != 1:
        blockers.append(
            f"expected one open {payload['scene_list_name']} list"
        )
    if len(prop_lists) != 1:
        blockers.append(
            f"expected one open {payload['prop_registry_list_name']} list"
        )
    if len(set_lists) > 1:
        blockers.append(
            f"found multiple open {payload['set_registry_list_name']} lists"
        )
    for label_name, matches in desired_labels.items():
        if len(matches) != 1:
            blockers.append(f"expected one existing label: {label_name}")
    if collisions:
        blockers.append("scene ID collisions exist")
    return {
        "scene_lists": scene_lists,
        "prop_lists": prop_lists,
        "set_lists": set_lists,
        "desired_labels": desired_labels,
        "scene_cards": scene_cards,
        "collisions": collisions,
        "blockers": blockers,
    }


def cierny_kamen_continuity_text(item, registry_url):
    previous = item.get("previous")
    following = item.get("next")
    previous_text = (
        f"{previous['scene_id']}: {previous['state']}"
        if previous else "prvý výskyt"
    )
    next_text = (
        f"{following['scene_id']}: {following['state']}"
        if following else "ďalší potvrdený obraz neurčený"
    )
    return (
        f"<n> {item['stable_name']} — {item['action']} | "
        f"← {previous_text} | TU: {item['current_state']} | "
        f"→ {next_text} | KARTA: {registry_url}"
    )


def cierny_kamen_plain_item(item):
    return item.get("source_text") or (
        f"{item['stable_name']} — {item['action']}"
    )


def cierny_kamen_scene_description(scene, prop_urls, set_urls):
    prop_context = [
        f"- **{item['stable_name']}** — {item['action']}"
        for item in scene["props"]
    ] or ["- Bez samostatnej rekvizity určenej v zdroji."]
    continuity = []
    links = []
    for item in scene["props"]:
        links.append(
            f"- {item['stable_name']}: {prop_urls[item['registry_key']]}"
        )
        if item.get("continuity"):
            continuity.append(
                f"- {item['stable_name']}: kontinuálna rekvizita."
            )
    for item in scene["set_items"]:
        if item.get("continuity"):
            continuity.append(
                f"- {item['stable_name']}: kontinuálny set."
            )
            links.append(
                f"- {item['stable_name']}: {set_urls[item['registry_key']]}"
            )
    if not continuity:
        continuity = ["- Bez potvrdenej nadväznosti."]
    if not links:
        links = ["- Bez samostatného odkazu."]
    characters = ", ".join(scene["characters"]) or "neuvedené"
    source = scene.get("source_pdf") or (
        f"Čierny Kameň – scenár epizódy {scene['episode']:02d}"
    )
    return (
        "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:START -->\n"
        f"ČÍSLO OBRAZU: {scene['scene_id']}\n"
        f"ZDROJ: {source}\n"
        "NATÁČACÍ DEŇ: nenaplánované\n"
        "DÁTUM: nenaplánované\n"
        "PORADIE: nenaplánované\n"
        "UNIT: nenaplánované\n"
        f"LOKÁCIA: {scene['location']}\n"
        f"POSTAVY: {characters}\n"
        "<!-- CIERNY-KAMEN-SCHEDULE-METADATA:END -->\n\n"
        f"## {scene['prepis']}\n\n"
        "### REKVIZITY V KONTEXTE\n"
        f"{chr(10).join(prop_context)}\n\n"
        "### KONTINUITA\n"
        f"{chr(10).join(continuity)}\n\n"
        "### ODKAZY\n"
        f"{chr(10).join(links)}\n\n"
        "### RUČNÉ DOPLNENIA\n\n"
        "### AKCIA A DIALÓGY\n"
        f"{scene['action_markdown']}"
    )


def cierny_kamen_scene_checklists(scene, prop_urls, set_urls):
    prop_items = [
        (
            cierny_kamen_continuity_text(
                item, prop_urls[item["registry_key"]]
            )
            if item.get("continuity")
            else (
                f"{cierny_kamen_plain_item(item)} | "
                f"KARTA: {prop_urls[item['registry_key']]}"
            )
        )
        for item in scene["props"]
    ]
    set_items = [
        (
            cierny_kamen_continuity_text(
                item, set_urls[item["registry_key"]]
            )
            if item.get("continuity")
            else cierny_kamen_plain_item(item)
        )
        for item in scene["set_items"]
    ]
    return {
        "REKVIZITY": prop_items,
        "SET": set_items,
        "INFO Z PORADY": [],
        "INFO Z NATÁČANIA": [],
        "OTÁZKY NA PORADU": list(scene.get("questions", [])),
    }


def cierny_kamen_registry_description(kind, key, entry, scene_urls):
    marker = cierny_kamen_registry_marker(kind, key)
    title = (
        (
            "HLAVNÁ KARTA NADVÄZNEJ REKVIZITY"
            if entry.get("continuity") else "HLAVNÁ KARTA REKVIZITY"
        )
        if kind == "PROP" else "HLAVNÁ KARTA KONTINUÁLNEHO SETU"
    )
    aliases = ", ".join(entry.get("aliases") or [entry["identity"]])
    timeline = []
    for occurrence in entry["occurrences"]:
        url = scene_urls.get(occurrence["scene_id"])
        if url:
            timeline.append(
                f"- [{occurrence['scene_id']}]({url}) — "
                f"{occurrence['action']}"
            )
        else:
            timeline.append(
                f"- {occurrence['scene_id']} — karta obrazu zatiaľ "
                f"nie je importovaná — {occurrence['action']}"
            )
    fixed = (
        "Jedna stabilná identita naprieč všetkými obrazmi; konkrétny "
        "kus a jeho stav sa potvrdzujú podľa časovej osi."
        if kind == "PROP"
        else "Zachovať identitu priestoru, rozmiestnenie a pevné "
        "scénografické prvky podľa časovej osi."
    )
    reason = (
        f"\n\n**DÔVOD PRIAMEJ NADVÄZNOSTI:** {entry['reason']}"
        if entry.get("reason") else ""
    )
    categories = ", ".join(entry.get("categories") or []) or "—"
    return (
        f"{marker}\n"
        f"# {title}\n\n"
        f"**IDENTITA:** `{entry['identity']}`\n\n"
        f"**ALIASY:** {aliases}\n\n"
        f"**KATEGÓRIE:** {categories}\n\n"
        f"**FIXNÉ VLASTNOSTI:** {fixed}{reason}\n\n"
        "## ČASOVÁ OS A ODKAZY NA OBRAZY\n"
        f"{chr(10).join(timeline)}\n\n"
        "## RUČNÉ POZNÁMKY\n"
    )


def cierny_kamen_create_card(list_id, name, desc, label_ids=None):
    data = {"idList": list_id, "name": name, "desc": desc, "pos": "bottom"}
    if label_ids:
        data["idLabels"] = ",".join(label_ids)
    return trello_post_body("/cards", data)


def cierny_kamen_create_checklists(card_id, checklists):
    created = []
    for checklist_name in CIERNY_KAMEN_IMPORT_CHECKLISTS:
        checklist = trello_post_body(
            f"/cards/{card_id}/checklists",
            {"name": checklist_name, "pos": "bottom"},
        )
        for item in checklists[checklist_name]:
            trello_post_body(
                f"/checklists/{checklist['id']}/checkItems",
                {"name": item, "pos": "bottom"},
            )
        created.append({
            "id": checklist["id"],
            "name": checklist_name,
            "items": len(checklists[checklist_name]),
        })
    return created


def cierny_kamen_repair_scene_card(
    card, scene, prop_urls, set_urls, label_ids
):
    expected_desc = cierny_kamen_scene_description(
        scene, prop_urls, set_urls
    )
    expected_checklists = cierny_kamen_scene_checklists(
        scene, prop_urls, set_urls
    )
    if card.get("name") != scene["name"]:
        raise RuntimeError(f"{scene['scene_id']} existing name mismatch")
    if card.get("desc") != expected_desc:
        raise RuntimeError(
            f"{scene['scene_id']} existing description mismatch"
        )
    expected_labels = sorted(label_ids[name] for name in scene["labels"])
    if sorted(card.get("idLabels", [])) != expected_labels:
        raise RuntimeError(f"{scene['scene_id']} existing labels mismatch")

    checklists = trello_get(
        f"/cards/{card['id']}/checklists",
        {"checkItems": "all", "fields": "id,name,pos"},
    )
    checklists = sorted(checklists, key=lambda item: item.get("pos", 0))
    if len(checklists) > len(CIERNY_KAMEN_IMPORT_CHECKLISTS):
        raise RuntimeError(f"{scene['scene_id']} has extra checklists")
    repaired = []
    for index, checklist in enumerate(checklists):
        expected_name = CIERNY_KAMEN_IMPORT_CHECKLISTS[index]
        if checklist.get("name") != expected_name:
            raise RuntimeError(
                f"{scene['scene_id']} checklist prefix mismatch"
            )
        expected_items = expected_checklists[expected_name]
        actual_items = [
            item.get("name")
            for item in sorted(
                checklist.get("checkItems", []),
                key=lambda entry: entry.get("pos", 0),
            )
        ]
        if actual_items != expected_items[:len(actual_items)]:
            raise RuntimeError(
                f"{scene['scene_id']} {expected_name} item prefix mismatch"
            )
        for item in expected_items[len(actual_items):]:
            trello_post_body(
                f"/checklists/{checklist['id']}/checkItems",
                {"name": item, "pos": "bottom"},
            )
            repaired.append(f"{expected_name}:item")

    for checklist_name in CIERNY_KAMEN_IMPORT_CHECKLISTS[len(checklists):]:
        checklist = trello_post_body(
            f"/cards/{card['id']}/checklists",
            {"name": checklist_name, "pos": "bottom"},
        )
        for item in expected_checklists[checklist_name]:
            trello_post_body(
                f"/checklists/{checklist['id']}/checkItems",
                {"name": item, "pos": "bottom"},
            )
        repaired.append(f"{checklist_name}:checklist")
    return repaired


def cierny_kamen_import_registry_batch(
    payload, state, target, start, limit, scene_urls
):
    kind = target["kind"]
    entries = (
        payload["prop_registry"]
        if kind == "PROP" else payload["set_registry"]
    )
    list_id = target["list_id"]
    existing, duplicates = cierny_kamen_registry_cards(
        state, kind, payload
    )
    if duplicates:
        raise RuntimeError(f"duplicate {kind} registry identities")
    keys = sorted(entries)[start:start + limit]
    created = []
    unchanged = []
    for key in keys:
        if key in existing:
            unchanged.append(key)
            continue
        entry = entries[key]
        card = cierny_kamen_create_card(
            list_id,
            entry["identity"],
            cierny_kamen_registry_description(
                kind, key, entry, scene_urls
            ),
        )
        created.append({
            "key": key, "id": card["id"], "url": card.get("shortUrl"),
        })
    return {
        "kind": kind,
        "start": start,
        "selected": len(keys),
        "created": created,
        "unchanged": unchanged,
        "remaining": max(0, len(entries) - start - len(keys)),
    }


def cierny_kamen_registry_urls(payload, state):
    prop_cards, prop_duplicates = cierny_kamen_registry_cards(
        state, "PROP", payload
    )
    set_cards, set_duplicates = cierny_kamen_registry_cards(
        state, "SET", payload
    )
    if prop_duplicates or set_duplicates:
        raise RuntimeError("duplicate registry marker")
    return (
        {key: card.get("shortUrl") for key, card in prop_cards.items()},
        {key: card.get("shortUrl") for key, card in set_cards.items()},
    )


@app.route("/api/import-cierny-kamen", methods=["POST"])
def import_cierny_kamen():
    return jsonify({"error": "completed import endpoint disabled"}), 410

    if request.headers.get("X-Import-Key") != CIERNY_KAMEN_IMPORT_KEY:
        return jsonify({"error": "forbidden"}), 403
    payload = cierny_kamen_import_payload()
    phase = request.args.get("phase", "dry-run").strip().casefold()
    try:
        start = int(request.args.get("start", "0"))
        limit = int(request.args.get("limit", "5"))
    except ValueError:
        return jsonify({"error": "start and limit must be integers"}), 400
    if start < 0 or limit < 1 or limit > 10:
        return jsonify({"error": "invalid start/limit"}), 400

    state = cierny_kamen_import_state(payload)
    audit = cierny_kamen_target_audit(payload, state)
    if audit["blockers"]:
        return jsonify({
            "status": "blocked",
            "blockers": audit["blockers"],
            "collisions": audit["collisions"],
        }), 409

    scene_urls = {
        scene_id: matches[0].get("shortUrl")
        for scene_id, matches in audit["scene_cards"].items()
        if len(matches) == 1
    }
    if phase == "dry-run":
        return jsonify({
            "status": "dry-run",
            "writes": 0,
            "board": {
                "id": state["board"]["id"],
                "name": state["board"].get("name"),
                "url": state["board"].get("url"),
            },
            "source": payload["stats"],
            "episode_counts": payload["episode_counts"],
            "targets": {
                "scene_list": [
                    {"id": item["id"], "name": item["name"]}
                    for item in audit["scene_lists"]
                ],
                "prop_registry_list": [
                    {"id": item["id"], "name": item["name"]}
                    for item in audit["prop_lists"]
                ],
                "set_registry_list": [
                    {"id": item["id"], "name": item["name"]}
                    for item in audit["set_lists"]
                ],
                "set_registry_will_be_created": not audit["set_lists"],
                "labels": {
                    name: [
                        {"id": item["id"], "name": item["name"]}
                        for item in matches
                    ]
                    for name, matches in audit["desired_labels"].items()
                },
            },
            "existing_imported_scenes": len(scene_urls),
            "scene_collisions": audit["collisions"],
            "missing_prepis": payload["stats"]["missing_prepis"],
            "missing_action": payload["stats"]["missing_action"],
        }), 200

    if phase == "init":
        if audit["set_lists"]:
            return jsonify({
                "status": "unchanged",
                "set_registry_list": audit["set_lists"][0],
            }), 200
        created = trello_post_body("/lists", {
            "idBoard": state["board"]["id"],
            "name": payload["set_registry_list_name"],
            "pos": "bottom",
        })
        return jsonify({
            "status": "created",
            "set_registry_list": {
                "id": created["id"], "name": created.get("name"),
            },
        }), 200

    if not audit["set_lists"]:
        return jsonify({
            "status": "blocked",
            "error": "REGISTER SETOV must be initialized first",
        }), 409

    sample_scene = next(
        scene for scene in payload["scenes"]
        if scene["scene_id"] == "02/28"
    )
    sample_prop_keys = sorted({
        item["registry_key"] for item in sample_scene["props"]
    })
    sample_set_keys = sorted({
        item["registry_key"] for item in sample_scene["set_items"]
        if item.get("continuity")
    })
    if phase == "sample-registries":
        created = []
        unchanged = []
        for kind, keys, entries, list_id in (
            (
                "PROP", sample_prop_keys, payload["prop_registry"],
                audit["prop_lists"][0]["id"],
            ),
            (
                "SET", sample_set_keys, payload["set_registry"],
                audit["set_lists"][0]["id"],
            ),
        ):
            existing, duplicates = cierny_kamen_registry_cards(
                state, kind, payload
            )
            if duplicates:
                return jsonify({
                    "status": "blocked",
                    "error": f"duplicate {kind} registry identities",
                }), 409
            for key in keys:
                if key in existing:
                    unchanged.append({"kind": kind, "key": key})
                    continue
                entry = entries[key]
                card = cierny_kamen_create_card(
                    list_id,
                    entry["identity"],
                    cierny_kamen_registry_description(
                        kind, key, entry, scene_urls
                    ),
                )
                created.append({
                    "kind": kind, "key": key,
                    "id": card["id"], "url": card.get("shortUrl"),
                })
        return jsonify({
            "status": "applied",
            "created": created,
            "unchanged": unchanged,
        }), 200

    if phase in {"prop-registries", "set-registries"}:
        target = {
            "kind": "PROP" if phase == "prop-registries" else "SET",
            "list_id": (
                audit["prop_lists"][0]["id"]
                if phase == "prop-registries"
                else audit["set_lists"][0]["id"]
            ),
        }
        result = cierny_kamen_import_registry_batch(
            payload, state, target, start, limit, scene_urls
        )
        return jsonify({"status": "applied", **result}), 200

    prop_urls, set_urls = cierny_kamen_registry_urls(payload, state)
    required_prop_keys = set(payload["prop_registry"])
    required_set_keys = set(payload["set_registry"])

    if phase == "sample-scene":
        missing_props = set(sample_prop_keys) - set(prop_urls)
        missing_sets = set(sample_set_keys) - set(set_urls)
        if missing_props or missing_sets:
            return jsonify({
                "status": "blocked",
                "error": "sample registry cards must exist first",
                "missing_prop_registry": sorted(missing_props),
                "missing_set_registry": sorted(missing_sets),
            }), 409
        existing = audit["scene_cards"].get("02/28", [])
        if existing:
            return jsonify({
                "status": "unchanged",
                "scene_id": "02/28",
                "url": existing[0].get("shortUrl"),
            }), 200
        label_ids = {
            name: matches[0]["id"]
            for name, matches in audit["desired_labels"].items()
        }
        card = cierny_kamen_create_card(
            audit["scene_lists"][0]["id"],
            sample_scene["name"],
            cierny_kamen_scene_description(
                sample_scene, prop_urls, set_urls
            ),
            [label_ids[name] for name in sample_scene["labels"]],
        )
        checklists = cierny_kamen_create_checklists(
            card["id"],
            cierny_kamen_scene_checklists(
                sample_scene, prop_urls, set_urls
            ),
        )
        return jsonify({
            "status": "created",
            "scene_id": "02/28",
            "id": card["id"],
            "url": card.get("shortUrl"),
            "checklists": checklists,
        }), 200

    if phase == "sample-links":
        missing_props = set(sample_prop_keys) - set(prop_urls)
        missing_sets = set(sample_set_keys) - set(set_urls)
        if missing_props or missing_sets or "02/28" not in scene_urls:
            return jsonify({
                "status": "blocked",
                "error": "sample cards are incomplete",
            }), 409
        updated = []
        for kind, keys, entries in (
            ("PROP", sample_prop_keys, payload["prop_registry"]),
            ("SET", sample_set_keys, payload["set_registry"]),
        ):
            registry_cards, duplicates = cierny_kamen_registry_cards(
                state, kind, payload
            )
            if duplicates:
                return jsonify({
                    "status": "blocked", "error": "duplicate registry cards"
                }), 409
            for key in keys:
                desired = cierny_kamen_registry_description(
                    kind, key, entries[key], scene_urls
                )
                card = registry_cards[key]
                if card.get("desc") != desired:
                    trello_put_body(
                        f"/cards/{card['id']}", {"desc": desired}
                    )
                    updated.append({"kind": kind, "key": key})
        return jsonify({"status": "applied", "updated": updated}), 200

    if phase == "audit-sample":
        missing_props = set(sample_prop_keys) - set(prop_urls)
        missing_sets = set(sample_set_keys) - set(set_urls)
        matches = audit["scene_cards"].get("02/28", [])
        errors = []
        if missing_props or missing_sets:
            errors.append("sample registry card missing")
        if len(matches) != 1:
            errors.append(f"sample scene card count is {len(matches)}")
        if errors:
            return jsonify({
                "status": "audit", "valid": False, "errors": errors,
            }), 409
        card = matches[0]
        expected_desc = cierny_kamen_scene_description(
            sample_scene, prop_urls, set_urls
        )
        expected_checklists = cierny_kamen_scene_checklists(
            sample_scene, prop_urls, set_urls
        )
        checklists = trello_get(
            f"/cards/{card['id']}/checklists",
            {"checkItems": "all", "fields": "id,name,pos"},
        )
        checklists = sorted(
            checklists, key=lambda item: item.get("pos", 0)
        )
        actual_names = [item.get("name") for item in checklists]
        if card.get("name") != sample_scene["name"]:
            errors.append("name mismatch")
        if card.get("desc") != expected_desc:
            errors.append("description mismatch")
        if actual_names != CIERNY_KAMEN_IMPORT_CHECKLISTS:
            errors.append("checklist order/name mismatch")
        else:
            for checklist in checklists:
                actual_items = [
                    item.get("name")
                    for item in sorted(
                        checklist.get("checkItems", []),
                        key=lambda entry: entry.get("pos", 0),
                    )
                ]
                if actual_items != expected_checklists[checklist["name"]]:
                    errors.append(
                        f"{checklist['name']} items mismatch"
                    )
        prop_text = "\n".join(expected_checklists["REKVIZITY"])
        if "<n> Alexova gitara" not in prop_text:
            errors.append("Alexova gitara continuity item missing")
        if "KARTA: https://trello.com/c/" not in prop_text:
            errors.append("real registry URL missing")
        if len(expected_checklists["SET"]) != 4:
            errors.append("sample SET item count mismatch")
        return jsonify({
            "status": "audit",
            "valid": not errors,
            "errors": errors,
            "scene_id": "02/28",
            "url": card.get("shortUrl"),
            "description_length": len(card.get("desc") or ""),
            "checklists": [
                {
                    "name": checklist["name"],
                    "items": len(checklist.get("checkItems", [])),
                }
                for checklist in checklists
            ],
            "prop_item": expected_checklists["REKVIZITY"][0],
        }), 200 if not errors else 409

    if set(prop_urls) != required_prop_keys or set(set_urls) != required_set_keys:
        return jsonify({
            "status": "blocked",
            "error": "all registry cards must exist before scene import",
            "missing_prop_registry": sorted(required_prop_keys - set(prop_urls)),
            "missing_set_registry": sorted(required_set_keys - set(set_urls)),
        }), 409

    if phase == "scenes":
        selected = payload["scenes"][start:start + limit]
        created = []
        unchanged = []
        repaired = []
        label_ids = {
            name: matches[0]["id"]
            for name, matches in audit["desired_labels"].items()
        }
        for scene in selected:
            existing = audit["scene_cards"].get(scene["scene_id"], [])
            if existing:
                changes = cierny_kamen_repair_scene_card(
                    existing[0], scene, prop_urls, set_urls, label_ids
                )
                if changes:
                    repaired.append({
                        "scene_id": scene["scene_id"],
                        "changes": changes,
                    })
                else:
                    unchanged.append(scene["scene_id"])
                continue
            description = cierny_kamen_scene_description(
                scene, prop_urls, set_urls
            )
            card = cierny_kamen_create_card(
                audit["scene_lists"][0]["id"],
                scene["name"],
                description,
                [label_ids[name] for name in scene["labels"]],
            )
            checklists = cierny_kamen_create_checklists(
                card["id"],
                cierny_kamen_scene_checklists(scene, prop_urls, set_urls),
            )
            created.append({
                "scene_id": scene["scene_id"],
                "id": card["id"],
                "url": card.get("shortUrl"),
                "checklists": checklists,
            })
        return jsonify({
            "status": "applied",
            "start": start,
            "selected": len(selected),
            "created": created,
            "repaired": repaired,
            "unchanged": unchanged,
            "remaining": max(
                0, len(payload["scenes"]) - start - len(selected)
            ),
        }), 200

    if phase in {"prop-links", "set-links"}:
        kind = "PROP" if phase == "prop-links" else "SET"
        entries = (
            payload["prop_registry"]
            if kind == "PROP" else payload["set_registry"]
        )
        registry_cards, duplicates = cierny_kamen_registry_cards(
            state, kind, payload
        )
        if duplicates:
            return jsonify({
                "status": "blocked", "error": "duplicate registry cards"
            }), 409
        keys = sorted(entries)[start:start + limit]
        updated = []
        unchanged = []
        for key in keys:
            card = registry_cards[key]
            desired = cierny_kamen_registry_description(
                kind, key, entries[key], scene_urls
            )
            if card.get("desc") == desired:
                unchanged.append(key)
                continue
            trello_put_body(f"/cards/{card['id']}", {"desc": desired})
            updated.append(key)
        return jsonify({
            "status": "applied",
            "kind": kind,
            "start": start,
            "selected": len(keys),
            "updated": updated,
            "unchanged": unchanged,
            "remaining": max(0, len(entries) - start - len(keys)),
        }), 200

    if phase == "audit-scenes":
        selected = payload["scenes"][start:start + limit]
        errors = []
        verified = []
        label_ids = {
            name: matches[0]["id"]
            for name, matches in audit["desired_labels"].items()
        }
        for scene in selected:
            matches = audit["scene_cards"].get(scene["scene_id"], [])
            if len(matches) != 1:
                errors.append({
                    "scene_id": scene["scene_id"],
                    "error": f"card count is {len(matches)}",
                })
                continue
            card = matches[0]
            expected_desc = cierny_kamen_scene_description(
                scene, prop_urls, set_urls
            )
            expected_labels = sorted(
                label_ids[name] for name in scene["labels"]
            )
            checklists = trello_get(
                f"/cards/{card['id']}/checklists",
                {"checkItems": "all", "fields": "id,name,pos"},
            )
            checklists = sorted(
                checklists, key=lambda item: item.get("pos", 0)
            )
            expected_checklists = cierny_kamen_scene_checklists(
                scene, prop_urls, set_urls
            )
            actual_names = [item.get("name") for item in checklists]
            item_errors = []
            if actual_names != CIERNY_KAMEN_IMPORT_CHECKLISTS:
                item_errors.append("checklist order/name mismatch")
            else:
                for checklist in checklists:
                    actual_items = [
                        item.get("name")
                        for item in sorted(
                            checklist.get("checkItems", []),
                            key=lambda entry: entry.get("pos", 0),
                        )
                    ]
                    if actual_items != expected_checklists[checklist["name"]]:
                        item_errors.append(
                            f"{checklist['name']} items mismatch"
                        )
            if card.get("name") != scene["name"]:
                item_errors.append("name mismatch")
            if card.get("desc") != expected_desc:
                item_errors.append("description mismatch")
            if sorted(card.get("idLabels", [])) != expected_labels:
                item_errors.append("label mismatch")
            if "ORIGINÁLNY SCENÁR" in (card.get("desc") or ""):
                item_errors.append("duplicate original-script section")
            if "KARTA: <" in (card.get("desc") or ""):
                item_errors.append("placeholder URL")
            if item_errors:
                errors.append({
                    "scene_id": scene["scene_id"],
                    "errors": item_errors,
                })
            else:
                verified.append({
                    "scene_id": scene["scene_id"],
                    "url": card.get("shortUrl"),
                    "description_length": len(card.get("desc") or ""),
                    "checklist_item_counts": {
                        checklist["name"]: len(
                            checklist.get("checkItems", [])
                        )
                        for checklist in checklists
                    },
                })
        return jsonify({
            "status": "audit",
            "start": start,
            "selected": len(selected),
            "verified": verified,
            "errors": errors,
            "remaining": max(
                0, len(payload["scenes"]) - start - len(selected)
            ),
            "unique_scene_cards": sum(
                len(matches) == 1
                for scene_id, matches in audit["scene_cards"].items()
                if scene_id in {
                    scene["scene_id"] for scene in payload["scenes"]
                }
            ),
        }), 200 if not errors else 409

    if phase in {"audit-props", "audit-sets"}:
        kind = "PROP" if phase == "audit-props" else "SET"
        entries = (
            payload["prop_registry"]
            if kind == "PROP" else payload["set_registry"]
        )
        registry_cards, duplicates = cierny_kamen_registry_cards(
            state, kind, payload
        )
        keys = sorted(entries)[start:start + limit]
        errors = []
        verified = []
        for key in keys:
            card = registry_cards.get(key)
            if not card:
                errors.append({"key": key, "error": "missing"})
                continue
            expected = cierny_kamen_registry_description(
                kind, key, entries[key], scene_urls
            )
            if card.get("desc") != expected:
                errors.append({"key": key, "error": "description mismatch"})
            else:
                verified.append({
                    "key": key, "url": card.get("shortUrl"),
                })
        return jsonify({
            "status": "audit",
            "kind": kind,
            "start": start,
            "selected": len(keys),
            "verified": verified,
            "errors": errors,
            "duplicates": sorted(duplicates),
            "remaining": max(0, len(entries) - start - len(keys)),
        }), 200 if not errors and not duplicates else 409

    return jsonify({"error": "unknown phase"}), 400


CIERNY_KAMEN_SET_FIX_KEY = "cierny-kamen-strict-sets-27jul-2f60ac91"


def cierny_kamen_set_marker_key(card):
    match = re.search(
        r"<!-- CIERNY-KAMEN-REGISTRY:SET:(.*?) -->",
        card.get("desc") or "",
    )
    return match.group(1) if match else None


def cierny_kamen_preserve_manual_description(actual, desired):
    pattern = re.compile(
        r"(### RUČNÉ DOPLNENIA\n)(.*?)(\n### AKCIA A DIALÓGY\n)",
        flags=re.S,
    )
    actual_match = pattern.search(actual or "")
    desired_match = pattern.search(desired)
    if not actual_match or not desired_match:
        raise RuntimeError("manual description section boundary missing")
    manual = actual_match.group(2)
    return (
        desired[:desired_match.start(2)]
        + manual
        + desired[desired_match.end(2):]
    )


def cierny_kamen_strict_set_overview(payload, state, audit):
    set_label_id = audit["desired_labels"]["Nadväzný set"][0]["id"]
    strict_keys = set(payload["set_registry"])
    active_set_registry = [
        card for card in state["cards"]
        if cierny_kamen_set_marker_key(card)
        and not card.get("closed")
        and not state["lists_by_id"].get(
            card.get("idList"), {}
        ).get("closed")
    ]
    legacy_cards = [
        card for card in active_set_registry
        if cierny_kamen_set_marker_key(card) not in strict_keys
    ]
    strict_cards = [
        card for card in active_set_registry
        if cierny_kamen_set_marker_key(card) in strict_keys
    ]
    labeled_scenes = [
        card for matches in audit["scene_cards"].values()
        for card in matches
        if set_label_id in card.get("idLabels", [])
    ]
    legacy_manual_notes = []
    for card in legacy_cards:
        notes = (card.get("desc") or "").split(
            "## RUČNÉ POZNÁMKY", 1
        )
        if len(notes) == 2 and notes[1].strip():
            legacy_manual_notes.append({
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
            })
    return {
        "set_items_total": payload["stats"]["set_items_total"],
        "strict_set_chains": payload["stats"]["strict_set_chains"],
        "desired_set_labeled_scenes": payload["stats"][
            "continuity_set_scenes"
        ],
        "current_set_labeled_scenes": len(labeled_scenes),
        "active_legacy_set_registry_cards": len(legacy_cards),
        "active_strict_set_registry_cards": len(strict_cards),
        "legacy_registry_manual_notes": legacy_manual_notes,
        "questions_to_add": sum(
            len(scene.get("questions", [])) for scene in payload["scenes"]
        ),
        "reasons": payload["stats"]["strict_set_chain_reasons"],
    }


def cierny_kamen_fix_scene_sets(
    card, scene, prop_urls, set_urls, set_label_id
):
    desired_desc = cierny_kamen_scene_description(
        scene, prop_urls, set_urls
    )
    desired_desc = cierny_kamen_preserve_manual_description(
        card.get("desc") or "", desired_desc
    )
    updates = []
    desired_has_label = "Nadväzný set" in scene["labels"]
    current_labels = list(card.get("idLabels", []))
    next_labels = [
        label_id for label_id in current_labels
        if label_id != set_label_id
    ]
    if desired_has_label:
        next_labels.append(set_label_id)
    next_labels = sorted(set(next_labels))
    if sorted(current_labels) != next_labels:
        updates.append("label")
    if card.get("desc") != desired_desc:
        updates.append("description")

    checklists = trello_get(
        f"/cards/{card['id']}/checklists",
        {"checkItems": "all", "fields": "id,name,pos"},
    )
    checklists = sorted(checklists, key=lambda item: item.get("pos", 0))
    if [item.get("name") for item in checklists] != (
        CIERNY_KAMEN_IMPORT_CHECKLISTS
    ):
        raise RuntimeError(
            f"{scene['scene_id']} checklist order/name mismatch"
        )
    by_name = {item["name"]: item for item in checklists}
    set_checklist = by_name["SET"]
    set_items = sorted(
        set_checklist.get("checkItems", []),
        key=lambda item: item.get("pos", 0),
    )
    generated_candidates = [
        item for item in set_items
        if (
            item.get("name", "").startswith("<> ")
            and " | KARTA: https://trello.com/c/" in item.get("name", "")
        ) or item.get("name") == (
            f"{scene['location']} — prostredie obrazu {scene['scene_id']}"
        )
    ]
    if len(generated_candidates) != 1:
        raise RuntimeError(
            f"{scene['scene_id']} generated SET item count is "
            f"{len(generated_candidates)}"
        )
    expected_set_items = cierny_kamen_scene_checklists(
        scene, prop_urls, set_urls
    )["SET"]
    generated_item = generated_candidates[0]
    if generated_item.get("name") != expected_set_items[0]:
        updates.append("set_item")

    question_checklist = by_name["OTÁZKY NA PORADU"]
    existing_questions = {
        item.get("name")
        for item in question_checklist.get("checkItems", [])
    }
    missing_questions = [
        item for item in scene.get("questions", [])
        if item not in existing_questions
    ]
    if missing_questions:
        updates.append("questions")

    if "description" in updates or "label" in updates:
        data = {}
        if "description" in updates:
            data["desc"] = desired_desc
        if "label" in updates:
            data["idLabels"] = ",".join(next_labels)
        trello_put_body(f"/cards/{card['id']}", data)
    if "set_item" in updates:
        trello_put_body(
            f"/cards/{card['id']}/checkItem/{generated_item['id']}",
            {"name": expected_set_items[0]},
        )
    for question in missing_questions:
        trello_post_body(
            f"/checklists/{question_checklist['id']}/checkItems",
            {"name": question, "pos": "bottom"},
        )
    return updates


@app.route("/api/fix-cierny-kamen-set-continuity", methods=["POST"])
def fix_cierny_kamen_set_continuity():
    return jsonify({"error": "completed SET fix endpoint disabled"}), 410

    if request.headers.get("X-Fix-Key") != CIERNY_KAMEN_SET_FIX_KEY:
        return jsonify({"error": "forbidden"}), 403
    payload = cierny_kamen_import_payload()
    phase = request.args.get("phase", "dry-run").strip().casefold()
    try:
        start = int(request.args.get("start", "0"))
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        return jsonify({"error": "start and limit must be integers"}), 400
    if start < 0 or limit < 1 or limit > 10:
        return jsonify({"error": "invalid start/limit"}), 400

    state = cierny_kamen_import_state(payload)
    audit = cierny_kamen_target_audit(payload, state)
    if audit["blockers"]:
        return jsonify({
            "status": "blocked",
            "blockers": audit["blockers"],
            "collisions": audit["collisions"],
        }), 409
    if len(audit["scene_cards"]) != 261:
        return jsonify({
            "status": "blocked",
            "error": "expected 261 imported scene IDs",
            "found": len(audit["scene_cards"]),
        }), 409
    overview = cierny_kamen_strict_set_overview(payload, state, audit)
    if phase == "dry-run":
        return jsonify({
            "status": "dry-run",
            "writes": 0,
            "board": {
                "id": state["board"]["id"],
                "name": state["board"].get("name"),
                "url": state["board"].get("url"),
            },
            "overview": overview,
            "sample_02_28": {
                "desired_set_label": False,
                "set_items": [
                    cierny_kamen_plain_item(item)
                    for item in next(
                        scene for scene in payload["scenes"]
                        if scene["scene_id"] == "02/28"
                    )["set_items"]
                ],
            },
        }), 200

    if overview["legacy_registry_manual_notes"]:
        return jsonify({
            "status": "blocked",
            "error": "legacy registry cards contain manual notes",
            "cards": overview["legacy_registry_manual_notes"],
        }), 409

    set_list_id = audit["set_lists"][0]["id"]
    scene_urls = {
        scene_id: matches[0].get("shortUrl")
        for scene_id, matches in audit["scene_cards"].items()
        if len(matches) == 1
    }
    if phase == "create-registries":
        existing, duplicates = cierny_kamen_registry_cards(
            state, "SET", payload
        )
        if duplicates:
            return jsonify({
                "status": "blocked", "error": "strict registry duplicates"
            }), 409
        keys = sorted(payload["set_registry"])[start:start + limit]
        created = []
        unchanged = []
        for key in keys:
            if key in existing:
                unchanged.append(key)
                continue
            entry = payload["set_registry"][key]
            card = cierny_kamen_create_card(
                set_list_id,
                entry["identity"],
                cierny_kamen_registry_description(
                    "SET", key, entry, scene_urls
                ),
            )
            created.append({
                "key": key, "id": card["id"], "url": card.get("shortUrl"),
            })
        return jsonify({
            "status": "applied",
            "created": created,
            "unchanged": unchanged,
            "remaining": max(
                0, len(payload["set_registry"]) - start - len(keys)
            ),
        }), 200

    prop_urls, set_urls = cierny_kamen_registry_urls(payload, state)
    if set(set_urls) != set(payload["set_registry"]):
        return jsonify({
            "status": "blocked",
            "error": "all strict SET registry cards must exist first",
            "missing": sorted(set(payload["set_registry"]) - set(set_urls)),
        }), 409
    set_label_id = audit["desired_labels"]["Nadväzný set"][0]["id"]

    if phase == "scenes":
        selected = payload["scenes"][start:start + limit]
        changed = []
        unchanged = []
        for scene in selected:
            card = audit["scene_cards"][scene["scene_id"]][0]
            updates = cierny_kamen_fix_scene_sets(
                card, scene, prop_urls, set_urls, set_label_id
            )
            if updates:
                changed.append({
                    "scene_id": scene["scene_id"],
                    "updates": updates,
                })
            else:
                unchanged.append(scene["scene_id"])
        return jsonify({
            "status": "applied",
            "start": start,
            "selected": len(selected),
            "changed": changed,
            "unchanged": unchanged,
            "remaining": max(
                0, len(payload["scenes"]) - start - len(selected)
            ),
        }), 200

    if phase == "registry-links":
        entries = payload["set_registry"]
        cards, duplicates = cierny_kamen_registry_cards(
            state, "SET", payload
        )
        if duplicates:
            return jsonify({
                "status": "blocked", "error": "strict registry duplicates"
            }), 409
        keys = sorted(entries)[start:start + limit]
        updated = []
        unchanged = []
        for key in keys:
            desired = cierny_kamen_registry_description(
                "SET", key, entries[key], scene_urls
            )
            card = cards[key]
            if card.get("desc") == desired:
                unchanged.append(key)
                continue
            trello_put_body(f"/cards/{card['id']}", {"desc": desired})
            updated.append(key)
        return jsonify({
            "status": "applied",
            "updated": updated,
            "unchanged": unchanged,
        }), 200

    if phase == "archive-legacy":
        strict_keys = set(payload["set_registry"])
        legacy = [
            card for card in state["cards"]
            if cierny_kamen_set_marker_key(card)
            and cierny_kamen_set_marker_key(card) not in strict_keys
            and not card.get("closed")
        ]
        selected = sorted(legacy, key=lambda card: card["id"])[
            start:start + limit
        ]
        archived = []
        for card in selected:
            trello_put_body(f"/cards/{card['id']}", {"closed": "true"})
            archived.append({
                "id": card["id"],
                "name": card.get("name"),
                "url": card.get("shortUrl"),
            })
        return jsonify({
            "status": "applied",
            "archived": archived,
            "remaining": max(0, len(legacy) - len(selected)),
        }), 200

    if phase == "audit-scenes":
        selected = payload["scenes"][start:start + limit]
        errors = []
        verified = []
        for scene in selected:
            card = audit["scene_cards"][scene["scene_id"]][0]
            desired_desc = cierny_kamen_preserve_manual_description(
                card.get("desc") or "",
                cierny_kamen_scene_description(
                    scene, prop_urls, set_urls
                ),
            )
            scene_errors = []
            if card.get("desc") != desired_desc:
                scene_errors.append("description mismatch")
            desired_label = "Nadväzný set" in scene["labels"]
            actual_label = set_label_id in card.get("idLabels", [])
            if desired_label != actual_label:
                scene_errors.append("Nadväzný set label mismatch")
            checklists = trello_get(
                f"/cards/{card['id']}/checklists",
                {"checkItems": "all", "fields": "id,name,pos"},
            )
            by_name = {item["name"]: item for item in checklists}
            actual_set = [
                item.get("name")
                for item in sorted(
                    by_name["SET"].get("checkItems", []),
                    key=lambda item: item.get("pos", 0),
                )
            ]
            expected_set = cierny_kamen_scene_checklists(
                scene, prop_urls, set_urls
            )["SET"]
            if actual_set[:len(expected_set)] != expected_set:
                scene_errors.append("SET items mismatch")
            questions = {
                item.get("name")
                for item in by_name["OTÁZKY NA PORADU"].get(
                    "checkItems", []
                )
            }
            if not set(scene.get("questions", [])).issubset(questions):
                scene_errors.append("question missing")
            if scene["scene_id"] == "02/28":
                if actual_label:
                    scene_errors.append("02/28 has forbidden set label")
                if any(item.startswith("<n> ") for item in actual_set):
                    scene_errors.append("02/28 has forbidden continuity item")
            if scene_errors:
                errors.append({
                    "scene_id": scene["scene_id"],
                    "errors": scene_errors,
                })
            else:
                verified.append(scene["scene_id"])
        return jsonify({
            "status": "audit",
            "start": start,
            "selected": len(selected),
            "verified": verified,
            "errors": errors,
            "remaining": max(
                0, len(payload["scenes"]) - start - len(selected)
            ),
        }), 200 if not errors else 409

    if phase == "audit-final":
        strict_cards, duplicates = cierny_kamen_registry_cards(
            state, "SET", payload
        )
        final_overview = cierny_kamen_strict_set_overview(
            payload, state, audit
        )
        errors = []
        if len(strict_cards) != len(payload["set_registry"]):
            errors.append("strict registry card count mismatch")
        if duplicates:
            errors.append("strict registry duplicates")
        if final_overview["active_legacy_set_registry_cards"]:
            errors.append("active legacy SET registry cards remain")
        if (
            final_overview["current_set_labeled_scenes"]
            != payload["stats"]["continuity_set_scenes"]
        ):
            errors.append("set label count mismatch")
        for key, entry in payload["set_registry"].items():
            card = strict_cards.get(key)
            if not card:
                continue
            desired = cierny_kamen_registry_description(
                "SET", key, entry, scene_urls
            )
            if card.get("desc") != desired:
                errors.append(f"registry description mismatch: {key}")
        return jsonify({
            "status": "audit",
            "valid": not errors,
            "errors": errors,
            "overview": final_overview,
        }), 200 if not errors else 409

    return jsonify({"error": "unknown phase"}), 400


CIERNY_KAMEN_N_MARKER_KEY = "cierny-kamen-n-marker-27jul-91a24fd6"
CIERNY_KAMEN_ANY_CONTINUITY_PREFIX = re.compile(
    r"^(?P<prefix><\s*[nN]?\s*>|\[[nN]\])\s+(?P<suffix>.*)$",
    flags=re.S,
)


def cierny_kamen_continuity_prefix_parts(value):
    match = CIERNY_KAMEN_ANY_CONTINUITY_PREFIX.match(value or "")
    if not match:
        return None
    return {
        "prefix": match.group("prefix"),
        "suffix": match.group("suffix"),
        "valid": match.group("prefix") == "<n>",
    }


def cierny_kamen_marker_batch(
    payload, state, audit, start, limit, apply_changes=False
):
    prop_urls, set_urls = cierny_kamen_registry_urls(payload, state)
    selected = payload["scenes"][start:start + limit]
    prop_label_id = audit["desired_labels"]["Nadväzná rekvizita"][0]["id"]
    set_label_id = audit["desired_labels"]["Nadväzný set"][0]["id"]
    counts = {
        "expected_continuity_items": 0,
        "already_lowercase_n": 0,
        "legacy_empty_angle": 0,
        "uppercase_angle_n": 0,
        "square_n": 0,
        "other_marker_variant": 0,
        "description_forbidden_markers": 0,
        "changed": 0,
    }
    errors = []
    changes = []
    all_pending = []
    for scene in selected:
        card = audit["scene_cards"][scene["scene_id"]][0]
        expected_checklists = cierny_kamen_scene_checklists(
            scene, prop_urls, set_urls
        )
        expected_by_name = {
            name: [
                item for item in items if item.startswith("<n> ")
            ]
            for name, items in expected_checklists.items()
        }
        expected_prop = len(expected_by_name["REKVIZITY"])
        expected_set = len(expected_by_name["SET"])
        counts["expected_continuity_items"] += expected_prop + expected_set
        if (prop_label_id in card.get("idLabels", [])) != bool(expected_prop):
            errors.append({
                "scene_id": scene["scene_id"],
                "error": "Nadväzná rekvizita label/item mismatch",
            })
        if (set_label_id in card.get("idLabels", [])) != bool(expected_set):
            errors.append({
                "scene_id": scene["scene_id"],
                "error": "Nadväzný set label/item mismatch",
            })

        description = card.get("desc") or ""
        forbidden_in_desc = re.findall(
            r"(?m)^(?:<>|<N>|\[[nN]\])\s+", description
        )
        counts["description_forbidden_markers"] += len(forbidden_in_desc)
        if forbidden_in_desc:
            errors.append({
                "scene_id": scene["scene_id"],
                "error": "forbidden marker in description",
            })

        checklists = trello_get(
            f"/cards/{card['id']}/checklists",
            {"checkItems": "all", "fields": "id,name,pos"},
        )
        by_name = {item["name"]: item for item in checklists}
        if not all(
            name in by_name for name in CIERNY_KAMEN_IMPORT_CHECKLISTS
        ):
            errors.append({
                "scene_id": scene["scene_id"],
                "error": "required checklist missing",
            })
            continue
        expected_suffixes = {
            name: {item[4:]: item for item in items}
            for name, items in expected_by_name.items()
        }
        pending = []
        for checklist_name in ("REKVIZITY", "SET"):
            matched_ids = set()
            actual_items = by_name[checklist_name].get("checkItems", [])
            for item in actual_items:
                parts = cierny_kamen_continuity_prefix_parts(
                    item.get("name")
                )
                if not parts:
                    continue
                expected = expected_suffixes[checklist_name].get(
                    parts["suffix"]
                )
                if not expected:
                    errors.append({
                        "scene_id": scene["scene_id"],
                        "error": (
                            f"unexpected marker item in {checklist_name}: "
                            f"{item.get('name')}"
                        ),
                    })
                    continue
                if parts["suffix"] in matched_ids:
                    errors.append({
                        "scene_id": scene["scene_id"],
                        "error": (
                            f"duplicate marker item in {checklist_name}"
                        ),
                    })
                    continue
                matched_ids.add(parts["suffix"])
                prefix = parts["prefix"]
                if prefix == "<n>":
                    counts["already_lowercase_n"] += 1
                elif prefix == "<>":
                    counts["legacy_empty_angle"] += 1
                elif prefix == "<N>":
                    counts["uppercase_angle_n"] += 1
                elif prefix in {"[N]", "[n]"}:
                    counts["square_n"] += 1
                else:
                    counts["other_marker_variant"] += 1
                if item.get("name") != expected:
                    pending.append({
                        "card_id": card["id"],
                        "item_id": item["id"],
                        "checklist": checklist_name,
                        "old": item.get("name"),
                        "new": expected,
                    })
            missing = set(expected_suffixes[checklist_name]) - matched_ids
            for suffix in sorted(missing):
                errors.append({
                    "scene_id": scene["scene_id"],
                    "error": (
                        f"missing continuity item in {checklist_name}: "
                        f"{suffix}"
                    ),
                })
        if pending:
            changes.append({
                "scene_id": scene["scene_id"],
                "items": len(pending),
            })
            all_pending.extend(pending)

    if apply_changes and not errors:
        for change in all_pending:
            trello_put_body(
                f"/cards/{change['card_id']}/checkItem/"
                f"{change['item_id']}",
                {"name": change["new"]},
            )
            counts["changed"] += 1

    return {
        "start": start,
        "selected": len(selected),
        "counts": counts,
        "changes": changes,
        "errors": errors,
        "remaining": max(
            0, len(payload["scenes"]) - start - len(selected)
        ),
    }


@app.route("/api/fix-cierny-kamen-n-marker", methods=["POST"])
def fix_cierny_kamen_n_marker():
    return jsonify({"error": "completed marker endpoint disabled"}), 410

    if request.headers.get("X-Marker-Key") != CIERNY_KAMEN_N_MARKER_KEY:
        return jsonify({"error": "forbidden"}), 403
    phase = request.args.get("phase", "dry-run").strip().casefold()
    if phase not in {"dry-run", "apply", "audit"}:
        return jsonify({"error": "phase must be dry-run, apply, or audit"}), 400
    try:
        start = int(request.args.get("start", "0"))
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        return jsonify({"error": "start and limit must be integers"}), 400
    if start < 0 or limit < 1 or limit > 10:
        return jsonify({"error": "invalid start/limit"}), 400

    payload = cierny_kamen_import_payload()
    state = cierny_kamen_import_state(payload)
    audit = cierny_kamen_target_audit(payload, state)
    if audit["blockers"] or len(audit["scene_cards"]) != 261:
        return jsonify({
            "status": "blocked",
            "blockers": audit["blockers"],
            "scene_ids": len(audit["scene_cards"]),
        }), 409
    result = cierny_kamen_marker_batch(
        payload, state, audit, start, limit, phase == "apply"
    )
    if result["errors"]:
        return jsonify({"status": "blocked", **result}), 409
    return jsonify({
        "status": "applied" if phase == "apply" else phase,
        "writes": result["counts"]["changed"] if phase == "apply" else 0,
        **result,
    }), 200


from cierny_kamen_pdf_migration import register_routes

register_routes(app, globals())

from cierny_kamen_prop_identity_repair import register_routes as register_prop_identity_routes

register_prop_identity_routes(app, globals())

from dok4_board_guard_repair import register_routes as register_dok4_board_guard_routes

register_dok4_board_guard_routes(app, globals())

from cierny_kamen_spaces_props import register_routes as register_spaces_props_routes

register_spaces_props_routes(app, globals())

from cierny_kamen_set_registry_audit import register_routes as register_set_audit_routes

register_set_audit_routes(app, globals())

from cierny_kamen_reference_0116 import register_routes as register_reference_0116_routes

register_reference_0116_routes(app, globals())

from cierny_kamen_reference_all import register_routes as register_reference_all_routes

register_reference_all_routes(app, globals())

from cierny_kamen_props_0101_0115 import register_routes as register_props_0101_0115_routes

register_props_0101_0115_routes(app, globals())

from cierny_kamen_set_links_dedup import register_routes as register_set_links_dedup_routes

register_set_links_dedup_routes(app, globals())

from cierny_kamen_all_props_registry import register_routes as register_all_props_registry_routes

register_all_props_registry_routes(app, globals())

from cierny_kamen_personal_props_markdown import register_routes as register_personal_props_markdown_routes

register_personal_props_markdown_routes(app, globals())

from cierny_kamen_prop_markdown_format import register_routes as register_prop_markdown_format_routes

register_prop_markdown_format_routes(app, globals())

from cierny_kamen_0440_markdown_repair import register_routes as register_0440_markdown_repair_routes

register_0440_markdown_repair_routes(app, globals())

from cierny_kamen_split_0440 import register_routes as register_split_0440_routes

register_split_0440_routes(app, globals())

from cierny_kamen_ep07_10_import import register_routes as register_ep07_10_routes

register_ep07_10_routes(app, globals())

from cierny_kamen_missing_0731_0845 import register_routes as register_ck_missing_0731_0845_routes

register_ck_missing_0731_0845_routes(app, globals())

from dunaj_board_webhook_repair import register_routes as register_dunaj_board_webhook_repair_routes

register_dunaj_board_webhook_repair_routes(app, globals())

from cierny_kamen_police_cars_audit import register_routes as register_ck_police_cars_audit_routes

register_ck_police_cars_audit_routes(app, globals())

from cierny_kamen_vehicles import register_routes as register_ck_vehicle_routes

register_ck_vehicle_routes(app, globals())

from meeting_notes_dryrun import register_routes as register_meeting_notes_dryrun_routes

register_meeting_notes_dryrun_routes(app, globals())

from cierny_kamen_meeting_semantic_dryrun import register_routes as register_ck_meeting_semantic_dryrun_routes

register_ck_meeting_semantic_dryrun_routes(app, globals())

from cierny_kamen_meeting_semantic_apply import register_routes as register_ck_meeting_semantic_apply_routes

register_ck_meeting_semantic_apply_routes(app, globals())

from cierny_kamen_reference_identity_0109 import register_routes as register_ck_reference_identity_0109_routes

register_ck_reference_identity_0109_routes(app, globals())

from cierny_kamen_split_0535flash import register_routes as register_split_0535flash_routes

register_split_0535flash_routes(app, globals())

from cierny_kamen_global_reference import register_routes as register_ck_global_reference_routes

register_ck_global_reference_routes(app, globals())

from cierny_kamen_followup_20260820 import register_routes as register_ck_followup_20260820_routes

register_ck_followup_20260820_routes(app, globals())

from meeting_notes_apply_ep01_03 import register_routes as register_meeting_notes_apply_ep01_03_routes

register_meeting_notes_apply_ep01_03_routes(app, globals())

from cierny_kamen_ep11_13_import import register_routes as register_ep11_13_routes

register_ep11_13_routes(app, globals())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)









































