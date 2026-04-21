from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

API_KEY = os.environ["TRELLO_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]
TARGET_CARD_ID = os.environ["TARGET_CARD_ID"]
TARGET_CHECKLIST_NAME = os.environ.get("TARGET_CHECKLIST_NAME", "Kupit")

ALLOWED_LIST_ID = os.environ["ALLOWED_LIST_ID"]

BASE = "https://api.trello.com/1"


def trello_get(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def trello_post(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.post(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_or_create_checklist():
    checklists = trello_get(f"/cards/{TARGET_CARD_ID}/checklists")
    for cl in checklists:
        if cl["name"].lower() == TARGET_CHECKLIST_NAME.lower():
            return cl["id"]

    created = trello_post(f"/cards/{TARGET_CARD_ID}/checklists", {
        "name": TARGET_CHECKLIST_NAME
    })
    return created["id"]


def item_exists(checklist_id, name):
    items = trello_get(f"/checklists/{checklist_id}/checkItems")
    return any(x["name"].lower() == name.lower() for x in items)


@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/trello-webhook", methods=["HEAD"])
def head():
    return "", 200


@app.route("/trello-webhook", methods=["POST"])
def webhook():
    data = request.json or {}

    action = data.get("action", {})
    action_type = action.get("type", "")

    if action_type != "updateCheckItem":
        return jsonify({"ignored": action_type})

    action_data = action.get("data", {})
    item = action_data.get("checkItem", {})
    name = item.get("name", "")

    if "[kupit]" not in name.lower():
        return jsonify({"ignored": "no tag"})

    card = action_data.get("card", {})
    card_id = card.get("id")

    if not card_id:
        return jsonify({"ignored": "no card"})

    card_info = trello_get(f"/cards/{card_id}", {"fields": "idList,name"})
    if card_info.get("idList") != ALLOWED_LIST_ID:
        return jsonify({"ignored": "wrong list"})

    clean_name = name.replace("[kupit]", "").strip()
    new_item_text = f"{clean_name} - {card_info['name']}"

    checklist_id = get_or_create_checklist()

    if item_exists(checklist_id, new_item_text):
        return jsonify({"skipped": "duplicate"})

    trello_post(f"/checklists/{checklist_id}/checkItems", {
        "name": new_item_text
    })

    return jsonify({"ok": True})
