from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

API_KEY = os.environ["TRELLO_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]
TARGET_CARD_ID = os.environ["TARGET_CARD_ID"]
TARGET_CHECKLIST_NAME = os.environ.get("TARGET_CHECKLIST_NAME", "Kupit")

BASE = "https://api.trello.com/1"


def trello_get(path, params=None):
    params = params or {}
    params.update({
        "key": API_KEY,
        "token": TOKEN,
    })
    r = requests.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def trello_post(path, params=None):
    params = params or {}
    params.update({
        "key": API_KEY,
        "token": TOKEN,
    })
    r = requests.post(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_or_create_target_checklist():
    checklists = trello_get(f"/cards/{TARGET_CARD_ID}/checklists")
    for cl in checklists:
        if cl["name"].strip().lower() == TARGET_CHECKLIST_NAME.strip().lower():
            return cl["id"]

    created = trello_post(f"/cards/{TARGET_CARD_ID}/checklists", {
        "name": TARGET_CHECKLIST_NAME
    })
    return created["id"]


def item_already_exists(checklist_id, item_name):
    items = trello_get(f"/checklists/{checklist_id}/checkItems")
    wanted = item_name.strip().lower()
    return any((x.get("name", "").strip().lower() == wanted) for x in items)


def add_item_to_target_checklist(item_name):
    checklist_id = get_or_create_target_checklist()

    # nech nevznikajú duplikáty
    if item_already_exists(checklist_id, item_name):
        return {"ok": True, "skipped": "duplicate", "item": item_name}

    created = trello_post(f"/checklists/{checklist_id}/checkItems", {
        "name": item_name
    })
    return {"ok": True, "created": created.get("id"), "item": item_name}


@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/trello-webhook", methods=["HEAD"])
def trello_head():
    # Trello overuje callback URL cez HEAD
    return "", 200


@app.route("/trello-webhook", methods=["POST"])
def trello_webhook():
    data = request.get_json(silent=True) or {}
    action = data.get("action", {})
    action_type = action.get("type", "")

    # zaujíma nás zmena checklist itemu
    if action_type != "updateCheckItem":
        return jsonify({"ok": True, "ignored": action_type})

    action_data = action.get("data", {})
    check_item = action_data.get("checkItem", {})
    item_name = check_item.get("name", "").strip()

    if not item_name:
        return jsonify({"ok": True, "ignored": "empty name"})

    # len položky s [kupit]
    if "[kupit]" not in item_name.lower():
        return jsonify({"ok": True, "ignored": "no [kupit]"})

    result = add_item_to_target_checklist(item_name)
    return jsonify(result)
