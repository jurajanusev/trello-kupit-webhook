processed_actions = set()

from flask import Flask, request, jsonify
from flask import send_from_directory
from pathlib import Path
import re
import requests
import os
import json
import unicodedata

app = Flask(__name__)

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

    "69f74077554ff079f9472308": {
        "target_list_id": "6a057f30a60d4ab5aee502b6"
    },

    # DOK4: VSETKY EPIZODY -> ToDo
    "6a3d776cbd0488b47076d8e6": {
        "target_list_id": "6a4776f530468dee7ea5fbfc"
    },

    # DOK4: SCENARE -> ToDo
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

CHECKLIST_TAG = os.environ.get("CHECKLIST_TAG", "[Z]")

BASE = "https://api.trello.com/1"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def trello_get(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.get(f"{BASE}{path}", params=params, timeout=20)

    if not r.ok:
        print("TRELLO GET ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_post(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.post(f"{BASE}{path}", params=params, timeout=20)

    if not r.ok:
        print("TRELLO POST ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_post_body(path, data=None):
    data = data or {}
    data.update({"key": API_KEY, "token": TOKEN})
    r = requests.post(f"{BASE}{path}", data=data, timeout=20)

    if not r.ok:
        print("TRELLO POST BODY ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_put_body(path, data=None):
    data = data or {}
    data.update({"key": API_KEY, "token": TOKEN})
    r = requests.put(f"{BASE}{path}", data=data, timeout=20)

    if not r.ok:
        print("TRELLO PUT BODY ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_delete(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.delete(f"{BASE}{path}", params=params, timeout=20)
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
            due_marker_present = bool(desired_date and re.search(
                r"(?:\*\*DUE DATE:\*\*|SYNC DUE DATE:)\s*" + re.escape(desired_date), current_body, flags=re.I
            ))
            # Graph may normalize text bodies on write. The Trello URL is the
            # stable sync identity, so do not rewrite an already linked body.
            if card["shortUrl"] not in current_body or (desired_date and not due_marker_present):
                changes["body"] = {"content": desired_body, "contentType": "text"}
            if desired_date and not due_marker_present:
                changes["dueDateTime"] = desired_due
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
    for board_list in lists:
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

    mode = request.args.get("mode", "dry-run")
    summary = {
        "project": config["name"], "board": board["name"],
        "registry_list_exists": bool(registry_list), "scene_cards": len(scene_cards),
        "unique_props": len(plans), "registry_cards": len(registry_cards),
        "repeated_props": sum(1 for plan in plans if len(plan["occurrences"]) > 1),
        "registry_to_create": sum(1 for plan in plans if not plan["existing"]),
        "registry_to_update": sum(1 for plan in plans if plan["existing"]),
        "registry_duplicates": sum(max(0, len(plan["existing"]) - 1) for plan in plans),
        "scene_cards_to_update": len(scene_cards),
    }
    if mode == "dry-run":
        return jsonify({"status": "dry-run", **summary, "repeated_sample": [{
            "prop": plan["display"],
            "scenes": [occ["scene_id"] for occ in plan["occurrences"]],
        } for plan in plans if len(plan["occurrences"]) > 1][:40]})

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


def find_cards_with_exact_item(search_term, allowed_list_id, exclude_card_id=None):
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
        cards = trello_get(f"/lists/{allowed_list_id}/cards", params)
        print(f"CARDS LOADED: {len(cards)}")
    except Exception as e:
        print(f"ERROR loading cards from list: {str(e)}")
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

SCENE_HEADING_RE = re.compile(
    r"^\s*(?:(?:OBRAZ|SC[ÉE]NA|SCENE)\s*)?(\d{1,4})[\).:-]?\s*(.*)$",
    re.IGNORECASE,
)

TV_SCENE_HEADING_RE = re.compile(
    r"^\s*(?P<scene>\d+/\d+)(?P<tag>[A-Z]{0,12})?\.?\s*(?P<title>(?:INT\.?|EXT\.?).*)$",
    re.IGNORECASE,
)


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


def build_trello_description(characters, body):
    cleaned = body.strip()
    lines = cleaned.split("\n")
    while lines and (not lines[0].strip() or looks_like_character_line(lines[0].strip())):
        lines.pop(0)
    scene_text = "\n".join(lines).strip()
    lead, rest = split_lead_sentence(scene_text)
    parts = [
        f"POSTAVY: {', '.join(name.upper() for name in characters) if characters else 'DOPLNIŤ'}",
        "",
        f"**PREPIS: {lead}**" if lead else "**PREPIS:**",
    ]
    if rest:
        parts.extend(["", format_scene_body(rest)])
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
    card["description"] = build_trello_description(characters, body)
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
    if request.headers.get("X-Sync-Key") != "dunaj-1516-schedule-19jul-2f8c41d6":
        return jsonify({"error": "forbidden"}), 403

    window_start = "2026-07-20"
    window_end = "2026-07-26"
    schedule_path = os.path.join(os.path.dirname(__file__), "dunaj_schedule_2026-07-19.json")
    with open(schedule_path, "r", encoding="utf-8") as handle:
        schedule_rows = json.load(handle)["rows"]
    row_by_scene = {row["scene_id"]: row for row in schedule_rows}

    board = trello_get("/boards/qCPeWA3e", {"fields": "id,name,url"})
    board_lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed"})
    open_lists = {item["id"]: item for item in board_lists if not item.get("closed")}
    lists_by_name = {item["name"]: item for item in open_lists.values()}
    cards = []
    for list_id in open_lists:
        cards.extend(trello_get(f"/lists/{list_id}/cards", {
            "fields": "id,name,desc,idList,shortUrl,due,dueComplete,pos,closed", "filter": "open", "limit": 1000
        }))

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
    for scene_id, row in row_by_scene.items():
        candidates = cards_by_scene.get(scene_id, [])
        if not candidates:
            missing.append(scene_id)
        else:
            if len(candidates) > 1:
                duplicate_ids.append(scene_id)
            for card in candidates:
                matched.append({"scene_id": scene_id, "row": row, "card": card})

    window_rows = [row for row in schedule_rows if window_start <= row["shooting_date"] <= window_end]
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

    shooting_dates = sorted({row["shooting_date"] for row in window_rows})
    target_names = {date_text: date_list_name(date_text) for date_text in shooting_dates}
    missing_target_lists = [name for name in target_names.values() if name not in lists_by_name]

    mode = request.args.get("mode", "dry-run")
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
            "open_lists": [item["name"] for item in open_lists.values()],
            "open_cards": len(cards), "schedule_rows": len(schedule_rows),
            "matched_scene_ids": len(schedule_rows) - len(missing), "matched_card_copies": len(matched),
            "missing_count": len(missing), "missing_sample": missing[:60],
            "duplicate_scene_ids_count": len(duplicate_ids), "duplicate_scene_ids_sample": duplicate_ids[:30],
            "matched_by_list": matched_by_list,
            "window_start": window_start, "window_end": window_end,
            "window_schedule_rows": len(window_rows), "window_unique_cards": len(window_cards),
            "window_missing_count": len(window_missing), "window_missing": window_missing,
            "window_duplicates_count": len(window_duplicates), "window_duplicates": window_duplicates[:20],
            "shooting_dates": shooting_dates, "days_without_shooting": 7 - len(shooting_dates),
            "missing_target_lists": missing_target_lists, "window_by_date": window_by_date,
            "window_sample": [{
                "scene_id": item["row"]["scene_id"], "date": item["row"]["shooting_date"],
                "matched_scene_id": item["matched_scene_id"], "fallback_match": item["fallback_match"],
                "order": item["row"]["order"], "unit": item["row"]["unit"],
                "from": open_lists.get(item["card"]["idList"], {}).get("name"),
                "to": target_names[item["row"]["shooting_date"]], "url": item["card"]["shortUrl"],
            } for item in window_cards[:40]],
        })

    if mode == "metadata":
        batch_start = max(0, int(request.args.get("start", "0")))
        batch_limit = min(75, max(1, int(request.args.get("limit", "40"))))
        batch = matched[batch_start:batch_start + batch_limit]
        start_marker = "<!-- DUNAJ-SCHEDULE-METADATA:START -->"
        end_marker = "<!-- DUNAJ-SCHEDULE-METADATA:END -->"
        updated = []; unchanged = 0; moved = []; errors = []
        for item in batch:
            row = item["row"]; card = item["card"]
            metadata = (
                f"{start_marker}\n"
                f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
                f"**ZDROJ:** predbežná dispo DUNAJ 16 z 19. 7. 2026\n"
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
            expected_due = f"{row['shooting_date']}T10:00:00.000Z"
            if new_desc == old_desc and card.get("due", "")[:10] == row["shooting_date"]:
                unchanged += 1; continue
            try:
                result = trello_put_body(f"/cards/{card['id']}", {"desc": new_desc, "due": expected_due})
                if result.get("idList") != card.get("idList"):
                    moved.append(item["scene_id"])
                updated.append(item["scene_id"])
            except Exception as exc:
                errors.append({"scene_id": item["scene_id"], "error": str(exc)})
        return jsonify({
            "status": "metadata-applied", "matched_card_copies": len(matched),
            "batch_start": batch_start, "batch_size": len(batch),
            "remaining": max(0, len(matched) - batch_start - len(batch)),
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
                    f"**ZDROJ:** predbežná dispo DUNAJ 16 z 19. 7. 2026\n"
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
                f"**ZDROJ:** predbežná dispo DUNAJ 16 z 19. 7. 2026\n"
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

    summary = {
        "board": board["name"], "scene_cards_scanned": scanned_scene_cards,
        "tagged_occurrences": tagged_occurrences, "unique_props": len(plans),
        "todo_cards_before": len(todo_cards),
        "to_create": sum(1 for item in plans if not item["existing"]),
        "to_update": sum(1 for item in plans if item["existing"]),
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
            "due": item["earliest_card"].get("due") if item["earliest_card"] else None,
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
    apply_plans = [item for item in plans if not item["existing"]] if request.args.get("only_missing") == "1" else plans
    batch = apply_plans[start:start + limit]
    marker_start = "<!-- DUNAJ-PROP-SYNC:START -->"
    marker_end = "<!-- DUNAJ-PROP-SYNC:END -->"
    created = []; updated = []; archived = []; errors = []
    for plan in batch:
        earliest_scene = plan["earliest_scene"] or "bez dátumu"
        earliest_card = plan["earliest_card"]
        lines = [
            marker_start,
            "Vytvorené a synchronizované automaticky z obrazových kariet.", "",
            f"**REKVIZITA:** {plan['display']}",
            f"**NAJSKORŠÍ OBRAZ:** {earliest_scene}",
            f"**DUE DATE:** {(earliest_card.get('due') or 'nenastavený')[:10] if earliest_card else 'nenastavený'}", "",
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
        if primary:
            old_desc = primary.get("desc", "")
            if marker_start in old_desc and marker_end in old_desc:
                pattern = re.escape(marker_start) + r".*?" + re.escape(marker_end)
                new_desc = re.sub(pattern, lambda _: synced, old_desc, count=1, flags=re.S)
            else:
                new_desc = synced + ("\n\n---\n\n**PÔVODNÝ ZÁZNAM / RUČNÉ POZNÁMKY:**\n\n" + old_desc if old_desc else "")
            payload = {"desc": new_desc}
            if earliest_card and earliest_card.get("due"):
                payload["due"] = earliest_card["due"]
            try:
                trello_put_body(f"/cards/{primary['id']}", payload)
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
                "desc": synced, "pos": "bottom",
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
    checklist_items = ["[ZMENA]", "[ZRUŠENÉ]", "[PRIDANÉ]", "[POŽIADAVKY]", "[PODĽA LOKÁCIE]"]
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
        for item in batch:
            try:
                if item["checklist"] and (not item["item_names"] or item["only_obsolete"]):
                    trello_delete(f"/checklists/{item['checklist']['id']}")
                    trello_post_body("/checklists", {
                        "idCard": item["card"]["id"], "name": "POZNÁMKY Z PORADY",
                        "pos": "bottom", "idChecklistSource": meeting_checklist["id"],
                    })
                elif item["checklist"]:
                    for obsolete in item["obsolete_items"]:
                        trello_delete(f"/checklists/{item['checklist']['id']}/checkItems/{obsolete['id']}")
                    for item_name in checklist_items:
                        if item_name.upper() not in item["item_names"]:
                            trello_post_body(f"/checklists/{item['checklist']['id']}/checkItems", {"name": item_name})
                else:
                    trello_post_body("/checklists", {
                        "idCard": item["card"]["id"], "name": "POZNÁMKY Z PORADY",
                        "pos": "bottom", "idChecklistSource": meeting_checklist["id"],
                    })
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

    allowed_list_id = card_info["idList"]

    if allowed_list_id in BOARD_CONFIG:
        target_list_id = BOARD_CONFIG[allowed_list_id]["target_list_id"]
    else:
        board_info = trello_get(f"/boards/{card_info['idBoard']}", {"fields": "shortLink"})
        is_dunaj_scene = (
            board_info.get("shortLink") == "qCPeWA3e" and
            re.match(r"^\s*[0-9]{1,2}\s*/\s*[0-9]+[A-Z]*(?:\.|\s|$)", card_info.get("name", ""), re.I)
        )
        if not is_dunaj_scene:
            print("IGNORED: wrong list", allowed_list_id, "configured:", list(BOARD_CONFIG.keys()))
            return jsonify({"status": "ignored", "reason": "card not in configured list"}), 200
        target_list_id = "69e53446a823be00f2e5e837"

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
            allowed_list_id,
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)









































