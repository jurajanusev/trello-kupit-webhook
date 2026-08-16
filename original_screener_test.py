import json
from pathlib import Path

from flask import jsonify, request


ORIGINAL_SCREENER_TEST_KEY = "original-screener-test-16aug-9f3c71d2"
BOARD_REF = "CzuD55PR"
LIST_NAME = "original screener"
TEST_SCENE_ID = "01/01"
TEST_START = "00:00:00"
TEST_END = "00:00:31"
MARKER = "<!-- ORIGINAL-SCREENER:01/01 -->"


def _fold(value):
    return (value or "").strip().casefold()


def _payload_scene():
    payload_path = Path(__file__).with_name("cierny_kamen_pdf_payload.json")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return next(
        scene for scene in payload["scenes"]
        if scene.get("scene_id") == TEST_SCENE_ID
    )


def register_routes(app, helpers):
    trello_get = helpers["trello_get"]
    trello_post_body = helpers["trello_post_body"]
    trello_request = helpers["trello_request"]
    base = helpers["BASE"]
    api_key = helpers["API_KEY"]
    token = helpers["TOKEN"]

    @app.route("/api/original-screener-test", methods=["POST"])
    def original_screener_test():
        if request.headers.get("X-Original-Screener-Key") != ORIGINAL_SCREENER_TEST_KEY:
            return jsonify({"error": "forbidden"}), 403

        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode not in {"dry-run", "apply"}:
            return jsonify({"error": "mode must be dry-run or apply"}), 400

        scene = _payload_scene()
        board = trello_get(
            f"/boards/{BOARD_REF}",
            {"fields": "id,name,url,closed,shortLink"},
        )
        if board.get("shortLink") != BOARD_REF or board.get("closed"):
            return jsonify({"error": "unexpected or closed board"}), 409

        lists = trello_get(
            f"/boards/{board['id']}/lists",
            {"fields": "id,name,closed", "filter": "open"},
        )
        target_lists = [item for item in lists if _fold(item.get("name")) == LIST_NAME]
        if len(target_lists) > 1:
            return jsonify({"error": "duplicate original screener lists"}), 409

        cards = trello_get(
            f"/boards/{board['id']}/cards",
            {"fields": "id,name,desc,idList,shortUrl,closed", "filter": "open", "limit": 1000},
        )
        source_cards = [
            card for card in cards
            if (card.get("name") or "").startswith(f"{TEST_SCENE_ID}.")
            and MARKER not in (card.get("desc") or "")
        ]
        source_card = source_cards[0] if len(source_cards) == 1 else None

        plan = {
            "board": {"name": board.get("name"), "url": board.get("url")},
            "list_name": LIST_NAME,
            "list_exists": bool(target_lists),
            "scene_id": TEST_SCENE_ID,
            "card_name": scene["name"],
            "time": f"{TEST_START}–{TEST_END}",
            "source_card": (
                {"name": source_card.get("name"), "url": source_card.get("shortUrl")}
                if source_card else None
            ),
            "source_card_matches": len(source_cards),
        }
        if mode == "dry-run":
            return jsonify({"status": "dry-run", "writes": 0, **plan}), 200

        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "multipart file is required"}), 400
        if not (upload.mimetype or "").startswith("video/"):
            return jsonify({"error": "uploaded file must be a video"}), 400

        if target_lists:
            target_list = target_lists[0]
        else:
            target_list = trello_post_body(
                "/lists",
                {"idBoard": board["id"], "name": LIST_NAME, "pos": "bottom"},
            )

        test_cards = [
            card for card in cards
            if card.get("idList") == target_list["id"]
            and MARKER in (card.get("desc") or "")
        ]
        if len(test_cards) > 1:
            return jsonify({"error": "duplicate test cards"}), 409

        source_url = source_card.get("shortUrl") if source_card else "nenájdená"
        description = (
            f"{MARKER}\n"
            f"**ZDROJOVÝ OBRAZ:** {TEST_SCENE_ID}\n\n"
            f"**ČAS V ORIGINÁLNOM SCREENERI:** {TEST_START}–{TEST_END}\n\n"
            f"**ZDROJOVÁ KARTA:** {source_url}\n\n"
            "Test rozdelenia pôvodného Riverdale S01E01 podľa obrazov zo scenára/Trello."
        )
        if test_cards:
            card = test_cards[0]
        else:
            card = trello_post_body(
                "/cards",
                {
                    "idList": target_list["id"],
                    "name": scene["name"],
                    "desc": description,
                    "pos": "bottom",
                },
            )

        attachments = trello_get(
            f"/cards/{card['id']}/attachments",
            {"fields": "id,name,url,mimeType"},
        )
        attachment_name = "01_01_original_screener.mp4"
        matching_attachments = [
            item for item in attachments
            if item.get("name") == attachment_name
        ]
        if matching_attachments:
            attachment = matching_attachments[0]
            attachment_status = "unchanged"
        else:
            response = trello_request(
                "POST",
                f"{base}/cards/{card['id']}/attachments",
                params={"key": api_key, "token": token, "name": attachment_name},
                files={
                    "file": (
                        attachment_name,
                        upload.stream,
                        upload.mimetype or "video/mp4",
                    )
                },
                timeout=120,
            )
            if not response.ok:
                return jsonify({
                    "error": "Trello attachment upload failed",
                    "status_code": response.status_code,
                    "details": response.text[:1000],
                    "card_url": card.get("shortUrl"),
                }), 502
            attachment = response.json()
            attachment_status = "created"

        return jsonify({
            "status": "applied",
            "list": {"id": target_list["id"], "name": target_list.get("name")},
            "card": {"id": card["id"], "name": card.get("name"), "url": card.get("shortUrl")},
            "attachment": {
                "status": attachment_status,
                "id": attachment.get("id"),
                "name": attachment.get("name"),
                "url": attachment.get("url"),
            },
            **plan,
        }), 200
