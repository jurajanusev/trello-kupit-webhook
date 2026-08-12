from flask import jsonify, request

from cierny_kamen_prop_markdown_format import exact_named
from cierny_kamen_reference_all import board_support_data


KEY = "cierny-kamen-split-0440-12aug-5ac9e730"
CARD_0439 = "6a67b0fd060d03b43843c129"


def register_routes(app, api):
    @app.route("/api/cierny-kamen-split-0440", methods=["POST"])
    def split_0440():
        if request.headers.get("X-Split-0440-Key") != KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "audit").casefold().strip()
        if mode not in {"audit", "dry-run"}:
            return jsonify({"error": "read-only endpoint"}), 400
        payload = api["cierny_kamen_import_payload"]()
        state = api["cierny_kamen_import_state"](payload)
        groups = api["cierny_kamen_scene_cards_by_id"](state)
        support = board_support_data(api, state["board"]["id"])
        cards = {card["id"]: card for card in state["cards"]}
        selected = []
        for scene_id in ("02/13", "02/14", "04/39", "04/40"):
            matches = groups.get(scene_id, [])
            selected.append({
                "scene_id": scene_id, "matches": [{
                    "card": card,
                    "list": state["lists_by_id"].get(card.get("idList"), {}).get("name"),
                    "checklists": support["checklists"].get(card["id"], []),
                    "attachments": support["attachments"].get(card["id"], []),
                    "comments": support["comments"].get(card["id"], []),
                } for card in matches],
            })
        registry_search = []
        terms = ("mobil", "amfiteáter", "školská taška")
        for card in state["cards"]:
            text = f"{card.get('name') or ''}\n{card.get('desc') or ''}".casefold()
            if any(term.casefold() in text for term in terms):
                registry_search.append({
                    "id": card["id"], "name": card.get("name"),
                    "url": card.get("shortUrl"), "closed": card.get("closed"),
                    "list": state["lists_by_id"].get(card.get("idList"), {}).get("name"),
                    "desc": card.get("desc"), "idLabels": card.get("idLabels", []),
                })
        lists = [{"id": item["id"], "name": item.get("name"), "closed": item.get("closed")}
                 for item in state["lists"]]
        return jsonify({
            "status": mode, "writes": 0,
            "board": state["board"], "scene_groups": selected,
            "container_by_id": {
                "card": cards.get(CARD_0439),
                "checklists": support["checklists"].get(CARD_0439, []),
                "attachments": support["attachments"].get(CARD_0439, []),
                "comments": support["comments"].get(CARD_0439, []),
            },
            "registry_search": registry_search, "lists": lists,
            "scene_count": len([key for key, value in groups.items() if len(value) == 1]),
            "duplicates": {key: len(value) for key, value in groups.items() if len(value) > 1},
        }), 200
