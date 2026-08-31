import json
from pathlib import Path

from flask import jsonify, request


UPLOAD_KEY = "original-screener-requested-31aug-8f2c6d91"
BOARD_REF = "CzuD55PR"
LIST_NAME = "original screener"
MARKER_PREFIX = "ORIGINAL-SCREENER:"


def _fold(value):
    return (value or "").strip().casefold()


def _scenes():
    path = Path(__file__).with_name("original_screener_requested_manifest.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _marker(scene_id):
    return f"<!-- {MARKER_PREFIX}{scene_id} -->"


def register_routes(app, helpers):
    trello_get = helpers["trello_get"]
    trello_post_body = helpers["trello_post_body"]
    trello_request = helpers["trello_request"]
    base = helpers["BASE"]
    api_key = helpers["API_KEY"]
    token = helpers["TOKEN"]

    @app.route("/api/original-screener-requested", methods=["POST"])
    def original_screener_requested():
        if request.headers.get("X-Original-Screener-Key") != UPLOAD_KEY:
            return jsonify({"error": "forbidden"}), 403
        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode not in {"dry-run", "apply"}:
            return jsonify({"error": "mode must be dry-run or apply"}), 400

        scenes = _scenes()
        scene_by_id = {item["scene_id"]: item for item in scenes}
        scene_id = (request.form.get("scene_id") or request.args.get("scene_id") or "").strip()
        if scene_id not in scene_by_id:
            return jsonify({"error": "valid scene_id is required"}), 400
        scene = scene_by_id[scene_id]

        board = trello_get(f"/boards/{BOARD_REF}", {"fields": "id,name,url,closed,shortLink"})
        if board.get("shortLink") != BOARD_REF or board.get("closed"):
            return jsonify({"error": "unexpected or closed board"}), 409
        lists = trello_get(f"/boards/{board['id']}/lists", {"fields": "id,name,closed", "filter": "open"})
        target_lists = [item for item in lists if _fold(item.get("name")) == LIST_NAME]
        if len(target_lists) != 1:
            return jsonify({"error": "original screener list must exist exactly once"}), 409
        target_list = target_lists[0]

        search = trello_get("/search", {
            "query": scene_id, "idBoards": board["id"], "modelTypes": "cards",
            "cards_limit": 100, "card_fields": "id,name,desc,idList,shortUrl,closed",
        })
        source_cards = [card for card in search.get("cards", [])
                        if not card.get("closed")
                        and (card.get("name") or "").startswith(f"{scene_id}.")
                        and _marker(scene_id) not in (card.get("desc") or "")]
        target_cards = trello_get(f"/lists/{target_list['id']}/cards",
                                  {"fields": "id,name,desc,idList,shortUrl,closed", "filter": "open"})
        destination_cards = [card for card in target_cards if _marker(scene_id) in (card.get("desc") or "")]
        start_time, end_time = _clock(scene["start"]), _clock(scene["end"])
        plan = {
            "scene_id": scene_id, "episode": scene["episode"],
            "list": {"id": target_list["id"], "name": target_list["name"]},
            "source_card_matches": len(source_cards),
            "destination_card_matches": len(destination_cards),
            "time": f"{start_time}–{end_time}",
        }
        if mode == "dry-run":
            return jsonify({"status": "dry-run", "writes": 0, **plan}), 200
        if len(source_cards) != 1 or len(destination_cards) > 1:
            return jsonify({"error": "card match validation failed", **plan}), 409

        upload = request.files.get("file")
        if upload is None or not upload.filename or not (upload.mimetype or "").startswith("video/"):
            return jsonify({"error": "valid multipart video file is required"}), 400
        source_card = source_cards[0]
        description = (
            f"{_marker(scene_id)}\n**ZDROJOVÝ OBRAZ:** {scene_id}\n\n"
            f"**ČAS V ORIGINÁLNOM SCREENERI:** {start_time}–{end_time}\n\n"
            f"**ZDROJOVÁ KARTA:** {source_card.get('shortUrl')}\n\n"
            f"Riverdale S01E{int(scene['episode']):02d} rozdelený podľa obrazov zo scenára/Trello."
        )
        if destination_cards:
            card = destination_cards[0]
        else:
            card = trello_post_body("/cards", {"idList": target_list["id"],
                                    "name": f"{scene_id}. {scene['title']}",
                                    "desc": description, "pos": "bottom"})
        attachment_name = f"{scene_id.replace('/', '_')}_original_screener.mp4"
        attachments = trello_get(f"/cards/{card['id']}/attachments", {"fields": "id,name,url,mimeType"})
        matching = [item for item in attachments if item.get("name") == attachment_name]
        if matching:
            attachment, attachment_status = matching[0], "unchanged"
        else:
            response = trello_request("POST", f"{base}/cards/{card['id']}/attachments",
                params={"key": api_key, "token": token, "name": attachment_name},
                files={"file": (attachment_name, upload.stream, upload.mimetype or "video/mp4")}, timeout=180)
            if not response.ok:
                return jsonify({"error": "attachment upload failed", "status_code": response.status_code,
                                "details": response.text[:1000], "card_url": card.get("shortUrl")}), 502
            attachment, attachment_status = response.json(), "created"
        return jsonify({"status": "applied", **plan,
                        "card": {"id": card["id"], "url": card.get("shortUrl")},
                        "attachment": {"status": attachment_status, "id": attachment.get("id"),
                                       "name": attachment.get("name"), "url": attachment.get("url")}}), 200
