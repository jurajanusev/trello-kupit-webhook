from flask import Flask, request, jsonify
import requests
import os

processed_actions = set()

app = Flask(__name__)

API_KEY = os.environ["TRELLO_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]

TARGET_CARD_ID = os.environ["TARGET_CARD_ID"]
TARGET_CHECKLIST_NAME = os.environ.get("TARGET_CHECKLIST_NAME", "Kupit")
TARGET_LIST_ID = os.environ["TARGET_LIST_ID"]
ALLOWED_LIST_ID = os.environ["ALLOWED_LIST_ID"]

CHECKLIST_TAG = os.environ.get("CHECKLIST_TAG", "[kupit]")
CARD_TAG = os.environ.get("CARD_TAG", "[karta]")

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


def get_card(card_id):
    return trello_get(f"/cards/{card_id}", {
        "fields": "name,idList,shortUrl,desc"
    })


def get_checklists_on_card(card_id):
    return trello_get(f"/cards/{card_id}/checklists")


def find_checklist_by_name(checklists, checklist_name):
    for cl in checklists:
        if cl["name"].strip().lower() == checklist_name.strip().lower():
            return cl
    return None


def add_checkitem_to_checklist(checklist_id, item_name):
    return trello_post(f"/checklists/{checklist_id}/checkItems", {
        "name": item_name
    })


def create_card(list_id, name, desc=""):
    return trello_post("/cards", {
        "idList": list_id,
        "name": name,
        "desc": desc,
        "pos": "bottom"
    })


def clean_item_name(item_name, tag):
    return item_name.replace(tag, "").strip()


def checklist_item_exists(checklist_id, item_name):
    print("CHECK EXISTING ITEM IN CHECKLIST:", checklist_id, item_name)
    items = trello_get(f"/checklists/{checklist_id}/checkItems")
    print("CHECKLIST ITEMS:", items)

    for item in items:
        if item["name"].strip().lower() == item_name.strip().lower():
            return True

    return False


def card_exists(list_id, card_name):
    print("CHECK EXISTING CARD IN LIST:", list_id, card_name)
    cards = trello_get(f"/lists/{list_id}/cards")
    print("LIST CARDS:", cards)

    for card in cards:
        if card["name"].strip().lower() == card_name.strip().lower():
            return True

    return False


@app.route("/", methods=["GET"])
def home():
    return "Trello webhook server is running", 200


@app.route("/trello-webhook", methods=["HEAD"])
def trello_head():
    return "", 200


@app.route("/trello-webhook", methods=["POST"])
def trello_webhook():
    data = request.json
    print("RAW DATA:", data)

    if not data or "action" not in data:
        print("IGNORED: no action")
        return jsonify({"status": "ignored", "reason": "no action"}), 200

    action = data["action"]
    action_type = action.get("type", "")
    action_id = action.get("id")

    print("ACTION TYPE:", action_type)
    print("ACTION ID:", action_id)

    if not action_id:
        print("IGNORED: missing action id")
        return jsonify({"status": "ignored", "reason": "missing action id"}), 200

    if action_id in processed_actions:
        print(f"SKIP duplicate action: {action_id}")
        return jsonify({"status": "ignored", "reason": "duplicate action"}), 200

    processed_actions.add(action_id)

    # reagujeme na vytvorenie alebo update checklist polozky
    if action_type not in ["createCheckItem", "updateCheckItem"]:
        print(f"IGNORED: unsupported action type {action_type}")
        return jsonify({"status": "ignored", "reason": f"unsupported action {action_type}"}), 200

    action_data = action.get("data", {})
    card = action_data.get("card")
    checkitem = action_data.get("checkItem")

    print("CARD:", card)
    print("CHECKITEM:", checkitem)

    if not card or not checkitem:
        print("IGNORED: missing card or checkitem")
        return jsonify({"status": "ignored", "reason": "missing card or checkitem"}), 200

    card_id = card["id"]
    checkitem_name = checkitem.get("name", "").strip()

    if not checkitem_name:
        print("IGNORED: empty checkitem name")
        return jsonify({"status": "ignored", "reason": "empty checkitem name"}), 200

    try:
        card_info = get_card(card_id)
        print("CARD INFO:", card_info)
    except Exception as e:
        print("ERROR loading card:", str(e))
        return jsonify({"status": "error", "reason": f"failed to load card: {str(e)}"}), 500

    if card_info["idList"] != ALLOWED_LIST_ID:
        print("IGNORED: wrong list", card_info["idList"], "!=", ALLOWED_LIST_ID)
        return jsonify({"status": "ignored", "reason": "card not in allowed list"}), 200

    item_lower = checkitem_name.lower()
    checklist_tag_lower = CHECKLIST_TAG.lower()
    card_tag_lower = CARD_TAG.lower()

    print("ITEM:", checkitem_name)
    print("CHECKLIST TAG:", CHECKLIST_TAG)
    print("CARD TAG:", CARD_TAG)

    # [kupit] -> pridaj do centralneho checklistu
    if checklist_tag_lower in item_lower:
        print("MATCH: checklist mode")
        clean_name = clean_item_name(checkitem_name, CHECKLIST_TAG)
        print("CLEAN NAME:", clean_name)

        if not clean_name:
            print("IGNORED: empty checklist item after cleanup")
            return jsonify({"status": "ignored", "reason": "empty checklist item after cleanup"}), 200

        try:
            print("TARGET_CARD_ID:", TARGET_CARD_ID)
            print("TARGET_CHECKLIST_NAME:", TARGET_CHECKLIST_NAME)

            target_checklists = get_checklists_on_card(TARGET_CARD_ID)
            print("TARGET CHECKLISTS:", target_checklists)

            target_checklist = find_checklist_by_name(target_checklists, TARGET_CHECKLIST_NAME)
            print("FOUND TARGET CHECKLIST:", target_checklist)

            if not target_checklist:
                print("ERROR: target checklist not found")
                return jsonify({"status": "error", "reason": "target checklist not found"}), 500

            new_item_text = f"{clean_name} - {card_info['name']}"
            print("NEW ITEM TEXT:", new_item_text)

            if checklist_item_exists(target_checklist["id"], new_item_text):
                print(f"SKIP existing item: {new_item_text}")
                return jsonify({
                    "status": "ignored",
                    "reason": "item already exists"
                }), 200

            created_item = add_checkitem_to_checklist(target_checklist["id"], new_item_text)
            print("CREATED ITEM:", created_item)

            return jsonify({
                "status": "ok",
                "mode": "checklist",
                "created_checkitem_id": created_item["id"],
                "created_checkitem_name": created_item["name"]
            }), 200

        except Exception as e:
            print("CHECKLIST MODE FAILED:", str(e))
            return jsonify({"status": "error", "reason": f"checklist mode failed: {str(e)}"}), 500

    # [karta] -> vytvor novu kartu
    elif card_tag_lower in item_lower:
        print("MATCH: card mode")
        clean_name = clean_item_name(checkitem_name, CARD_TAG)
        print("CLEAN NAME:", clean_name)

        if not clean_name:
            print("IGNORED: empty card name after cleanup")
            return jsonify({"status": "ignored", "reason": "empty card name after cleanup"}), 200

        new_card_name = f"{clean_name} - {card_info['name']}"
        new_card_desc = (
            f"Vytvorené automaticky z checklist položky.\n\n"
            f"Pôvodná karta: {card_info['name']}\n"
            f"Odkaz na pôvodnú kartu: {card_info['shortUrl']}\n\n"
            f"Pôvodná checklist položka: {checkitem_name}"
        )

        try:
            print("TARGET_LIST_ID:", TARGET_LIST_ID)
            print("NEW CARD NAME:", new_card_name)

            if card_exists(TARGET_LIST_ID, new_card_name):
                print(f"SKIP existing card: {new_card_name}")
                return jsonify({
                    "status": "ignored",
                    "reason": "card already exists"
                }), 200

            created_card = create_card(TARGET_LIST_ID, new_card_name, new_card_desc)
            print("CREATED CARD:", created_card)

            return jsonify({
                "status": "ok",
                "mode": "card",
                "created_card_id": created_card["id"],
                "created_card_name": created_card["name"]
            }), 200

        except Exception as e:
            print("CARD MODE FAILED:", str(e))
            return jsonify({"status": "error", "reason": f"card mode failed: {str(e)}"}), 500

    else:
        print("IGNORED: no matching tag")
        return jsonify({"status": "ignored", "reason": "no matching tag"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
