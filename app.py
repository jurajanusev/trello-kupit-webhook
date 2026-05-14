processed_actions = set()

from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

API_KEY = os.environ["TRELLO_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]

TARGET_CARD_ID = os.environ["TARGET_CARD_ID"]
TARGET_CHECKLIST_NAME = os.environ.get("TARGET_CHECKLIST_NAME", "Kupit")
TARGET_LIST_ID = os.environ["TARGET_LIST_ID"]
ALLOWED_LIST_ID = os.environ["ALLOWED_LIST_ID"]

CHECKLIST_TAG = os.environ.get("CHECKLIST_TAG", "[Z]")

BASE = "https://api.trello.com/1"


def trello_get(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.get(f"{BASE}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def trello_post(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.post(f"{BASE}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_card(card_id):
    return trello_get(f"/cards/{card_id}", {
        "fields": "name,idList,shortUrl,desc"
    })


def get_checklists_on_card(card_id):
    return trello_get(f"/cards/{card_id}/checklists", {
        "checkItems": "all"
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


def create_card(list_id, name, desc=""):
    return trello_post("/cards", {
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


def find_cards_with_exact_item(search_term, exclude_card_id=None):
    print("SEARCH TERM:", search_term)
    matching_cards = []
    search_norm = normalize_item_name(search_term)

    # Optimalizované API volanie: Stiahneme karty AJ s checklistami v jednom balíku
    params = {
        "fields": "name",
        "checklists": "all",      # Toto je kľúčová zmena
        "checklist_fields": "id", # Stačí nám ID checklistu
        "limit": 1000
    }

    try:
        # Použijeme cestu pre list, ktorá vráti karty so zanorenými checklistami
        cards = trello_get(f"/lists/{ALLOWED_LIST_ID}/cards", params)
        print(f"CARDS LOADED: {len(cards)}")
    except Exception as e:
        print(f"ERROR loading cards from list: {str(e)}")
        return []

    for card in cards:
        card_id = card["id"]
        card_name = card["name"]

        if exclude_card_id and card_id == exclude_card_id:
            continue

        # Dáta checklistov sú už v objekte karty vďaka parametru checklists=all
        checklists = card.get("checklists", [])
        
        for checklist in checklists:
            # Každý checklist obsahuje pole checkItems
            for item in checklist.get("checkItems", []):
                item_name = item.get("name", "")
                if normalize_item_name(item_name) == search_norm:
                    print(f"MATCH FOUND IN CARD: {card_name}")
                    matching_cards.append(card_name)
                    break 

    print("FINAL MATCHING CARDS:", matching_cards)
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

    processed_actions.add(action_id)

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

    if card_info["idList"] != ALLOWED_LIST_ID:
        print("IGNORED: wrong list")
        return jsonify({"status": "ignored", "reason": "card not in allowed list"}), 200

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

    # 1. Pridanie položky do cieľového checklistu
    try:
        target_checklists = get_checklists_on_card(TARGET_CARD_ID)
        target_checklist = find_checklist_by_name(
            target_checklists,
            TARGET_CHECKLIST_NAME
        )

        if target_checklist:
            matching_cards = find_cards_with_exact_item(
                clean_name,
                exclude_card_id=None
            )

            if matching_cards:
                found_text = ", ".join(matching_cards)
            else:
                found_text = "nenájdené"

            new_item_text = f"{clean_name} - {found_text}"
            add_checkitem_to_checklist(target_checklist["id"], new_item_text)

            print("CHECKLIST ITEM CREATED:", new_item_text)
        else:
            print("ERROR: target checklist not found")

    except Exception as e:
        return jsonify({"status": "error", "reason": f"checklist failed: {str(e)}"}), 500

    # 2. Vytvorenie novej karty
    try:
        new_card_name = f"{clean_name} - {card_info['name']}"

        matching_cards = find_cards_with_exact_item(
            clean_name,
            exclude_card_id=card_id
        )

        if matching_cards:
            found_text = ", ".join(matching_cards)
        else:
            found_text = "nenájdené"

        new_card_desc = (
            f"Vytvorené automaticky z checklist položky.\n\n"
            f"Pôvodná karta: {card_info['name']}\n"
            f"Odkaz na pôvodnú kartu: {card_info['shortUrl']}\n\n"
            f"Pôvodná checklist položka: {checkitem_name}\n\n"
            f"Nájdené v kartách:\n{found_text}"
        )

        exists = card_exists_in_list(TARGET_LIST_ID, new_card_name)

        if exists:
            print("SKIP existing card:", new_card_name)
        else:
            created_card = create_card(TARGET_LIST_ID, new_card_name, new_card_desc)
            print("CARD CREATED:", created_card)

    except Exception as e:
        print("CARD ERROR:", repr(e))
        return jsonify({"status": "error", "reason": f"card failed: {str(e)}"}), 500

    return jsonify({"status": "ok", "mode": "both"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
