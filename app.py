from flask import Flask, request, jsonify
import requests
import os

processed_actions = set()

app = Flask(__name__)

API_KEY = os.environ["TRELLO_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]

# Cieľová karta a checklist
TARGET_CARD_ID = os.environ["TARGET_CARD_ID"]
TARGET_CHECKLIST_NAME = os.environ.get("TARGET_CHECKLIST_NAME", "Kupit")

# Zdrojový list, v ktorom sa majú prehľadávať karty
ALLOWED_LIST_ID = os.environ["ALLOWED_LIST_ID"]

# Tag, ktorý spustí akciu
CHECKLIST_TAG = os.environ.get("CHECKLIST_TAG", "[Z]")

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


def get_cards_in_list(list_id):
    return trello_get(f"/lists/{list_id}/cards", {
        "fields": "name"
    })


def find_checklist_by_name(checklists, checklist_name):
    for cl in checklists:
        if cl["name"].strip().lower() == checklist_name.strip().lower():
            return cl
    return None


def add_checkitem_to_checklist(checklist_id, item_name):
    return trello_post(f"/checklists/{checklist_id}/checkItems", {
        "name": item_name
    })


def clean_item_name(item_name, tag):
    return item_name.replace(tag, "").strip()


def checklist_item_exists(checklist_id, item_name):
    items = trello_get(f"/checklists/{checklist_id}/checkItems")
    for item in items:
        if item.get("name", "").strip().lower() == item_name.strip().lower():
            return True
    return False


def normalize_checkitem_text(item_name):
    """
    Odstráni trigger tag [Z] a znormalizuje text checklist položky.
    """
    return item_name.replace(CHECKLIST_TAG, "").strip().lower()


def card_has_checkitem_text(card_id, search_text):
    """
    Zistí, či karta obsahuje v niektorom checkliste položku s presným textom search_text.
    """
    checklists = get_checklists_on_card(card_id)
    wanted = search_text.strip().lower()

    for checklist in checklists:
        for item in checklist.get("checkItems", []):
            item_name = item.get("name", "")
            normalized = normalize_checkitem_text(item_name)
            if normalized == wanted:
                return True

    return False


def find_cards_with_checkitem_in_list(list_id, search_text):
    """
    Vráti zoznam názvov kariet v danom liste, ktoré obsahujú checklist položku search_text.
    """
    cards = get_cards_in_list(list_id)
    matching_cards = []

    for card in cards:
        try:
            if card_has_checkitem_text(card["id"], search_text):
                matching_cards.append(card["name"])
        except Exception as e:
            print(f"ERROR checking card {card.get('id')}: {str(e)}")

    return matching_cards


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

    if action_type not in ["createCheckItem", "updateCheckItem"]:
        print(f"IGNORED: unsupported action type {action_type}")
        return jsonify({"status": "ignored", "reason": f"unsupported action {action_type}"}), 200

    # Pri update reaguj len na zmenu názvu položky
    if action_type == "updateCheckItem":
        old = action.get("data", {}).get("old", {})
        if "name" not in old:
            print("IGNORED: update not changing name")
            return jsonify({"status": "ignored", "reason": "not a name change"}), 200

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

    # Spracuj len karty z povoleného listu
    if card_info["idList"] != ALLOWED_LIST_ID:
        print("IGNORED: wrong list", card_info["idList"], "!=", ALLOWED_LIST_ID)
        return jsonify({"status": "ignored", "reason": "card not in allowed list"}), 200

    item_lower = checkitem_name.lower()
    checklist_tag_lower = CHECKLIST_TAG.lower()

    print("ITEM:", checkitem_name)
    print("CHECKLIST TAG:", CHECKLIST_TAG)

    # Spusti akciu len ak položka obsahuje trigger tag
    if checklist_tag_lower not in item_lower:
        print("IGNORED: no matching tag")
        return jsonify({"status": "ignored", "reason": "no matching tag"}), 200

    clean_name = clean_item_name(checkitem_name, CHECKLIST_TAG)

    if not clean_name:
        print("IGNORED: empty name after cleanup")
        return jsonify({"status": "ignored", "reason": "empty name"}), 200

    try:
        target_checklists = get_checklists_on_card(TARGET_CARD_ID)
        target_checklist = find_checklist_by_name(target_checklists, TARGET_CHECKLIST_NAME)

        if not target_checklist:
            print("ERROR: target checklist not found")
            return jsonify({"status": "error", "reason": "target checklist not found"}), 500

        # Nájdeme všetky karty v povolenom liste, kde sa nachádza rovnaká položka
        matching_cards = find_cards_with_checkitem_in_list(ALLOWED_LIST_ID, clean_name)
        print("MATCHING CARDS:", matching_cards)

        if matching_cards:
            new_item_text = f"{clean_name} - {', '.join(matching_cards)}"
        else:
            new_item_text = f"{clean_name} - {card_info['name']}"

        if checklist_item_exists(target_checklist["id"], new_item_text):
            print("SKIP existing checklist item:", new_item_text)
            return jsonify({
                "status": "ignored",
                "reason": "item already exists"
            }), 200

        add_checkitem_to_checklist(target_checklist["id"], new_item_text)
        print("CHECKLIST CREATED:", new_item_text)

        return jsonify({
            "status": "ok",
            "mode": "summary",
            "created_checkitem_name": new_item_text
        }), 200

    except Exception as e:
        print("ERROR creating checklist summary:", str(e))
        return jsonify({"status": "error", "reason": f"summary failed: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
