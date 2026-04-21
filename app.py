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
    r = requests.get(f"{BASE}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def trello_post(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.post(f"{BASE}{path}", params=params, timeout=10)
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

def card_exists_in_list(list_id, card_name):
    cards = trello_get(f"/lists/{list_id}/cards", {
        "fields": "name"
    })

    for card in cards:
        if card["name"].strip().lower() == card_name.strip().lower():
            return True

    return False
    
def clean_item_name(item_name, tag=None):
    cleaned = item_name.strip()

    if "[" in cleaned:
        cleaned = cleaned.split("[")[0].strip()

    return cleaned
    
def find_cards_with_term_in_checklists(search_term, exclude_card_id=None):
    print("SEARCH TERM:", search_term)
    matching_cards = []

    cards = trello_get(f"/lists/{ALLOWED_LIST_ID}/cards", {
        "fields": "name"
    })

    search_term_lower = search_term.strip().lower()

    for i, card in enumerate(cards):
        if i >= 15:
            print("STOP: reached search limit")
            break

        if exclude_card_id and card["id"] == exclude_card_id:
            continue

        try:
            checklists = get_checklists_on_card(card["id"])

            for checklist in checklists:
                for item in checklist.get("checkItems", []):
                    item_name = item.get("name", "").strip()

                    if "[" in item_name:
                        item_name = item_name.split("[")[0].strip()

                    if search_term_lower in item_name.lower():
                        print("MATCH FOUND IN CARD:", card["name"])
                        matching_cards.append(card["name"])
                        break
                else:
                    continue
                break

        except Exception as e:
            print(f"ERROR reading card {card.get('name')}: {str(e)}")

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
        print("IGNORED: no action")
        return jsonify({"status": "ignored", "reason": "no action"}), 200

    action = data["action"]
    action_type = action.get("type", "")
    action_id = action.get("id")

    print("ACTION TYPE:", action_type)
    print("ACTION ID:", action_id)

    if not action_id:
        return jsonify({"status": "ignored", "reason": "missing action id"}), 200

    if action_id in processed_actions:
        print(f"SKIP duplicate action: {action_id}")
        return jsonify({"status": "ignored", "reason": "duplicate action"}), 200

    processed_actions.add(action_id)

    if action_type not in ["createCheckItem", "updateCheckItem"]:
        print(f"IGNORED: unsupported action type {action_type}")
        return jsonify({"status": "ignored", "reason": f"unsupported action {action_type}"}), 200

    # pri updateCheckItem reaguj LEN na zmenu názvu
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
        return jsonify({"status": "ignored", "reason": "missing card or checkitem"}), 200

    card_id = card["id"]
    checkitem_name = checkitem.get("name", "").strip()

    if not checkitem_name:
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

    print("ITEM:", checkitem_name)
    print("CHECKLIST TAG:", CHECKLIST_TAG)

    if checklist_tag_lower in item_lower:
        clean_name = clean_item_name(checkitem_name, CHECKLIST_TAG)
        print("CLEAN NAME:", clean_name)

        if not clean_name:
            return jsonify({"status": "ignored", "reason": "empty name"}), 200

        # try:
        #     target_checklists = get_checklists_on_card(TARGET_CARD_ID)
        #     target_checklist = find_checklist_by_name(target_checklists, TARGET_CHECKLIST_NAME)
        
        #     if not target_checklist:
        #         print("ERROR: target checklist not found")
        #     else:
        #         new_item_text = f"{clean_name} - {card_info['name']}"
        #         add_checkitem_to_checklist(target_checklist["id"], new_item_text)
        #         print("CHECKLIST CREATED:", new_item_text)
        
        # except Exception as e:
        #     return jsonify({"status": "error", "reason": f"checklist failed: {str(e)}"}), 500

        try:
            new_card_name = f"{clean_name} - {card_info['name']}"
            print("NEW CARD NAME:", new_card_name)
            print("TARGET_LIST_ID:", TARGET_LIST_ID)

            matching_cards = find_cards_with_term_in_checklists(
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
            print("CARD DESC READY")
            print("MATCHING CARDS:", matching_cards)

            print("BEFORE CARD EXISTS CHECK")
            exists = card_exists_in_list(TARGET_LIST_ID, new_card_name)
            print("CARD EXISTS RESULT:", exists)

            if exists:
                print("SKIP existing card:", new_card_name)
            else:
                print("BEFORE CREATE_CARD")
                created_card = create_card(TARGET_LIST_ID, new_card_name, new_card_desc)
                print("CARD CREATED:", created_card)

        except Exception as e:
            print("CARD ERROR:", repr(e))
            return jsonify({"status": "error", "reason": f"card failed: {str(e)}"}), 500

        return jsonify({"status": "ok", "mode": "both"}), 200

    return jsonify({"status": "ignored", "reason": "no matching tag"}), 200
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
