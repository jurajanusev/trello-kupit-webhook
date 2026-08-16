import json
from pathlib import Path

from flask import jsonify, request


ORIGINAL_SCREENER_KEY = "original-screener-test-16aug-9f3c71d2"
BOARD_REF = "CzuD55PR"
LIST_NAME = "original screener"
MARKER_PREFIX = "ORIGINAL-SCREENER:"

SCENE_TIMES = {
    "01/01": ("00:00:00", "00:00:31"),
    "01/02LP": ("00:00:32", "00:00:39"),
    "01/03LP": ("00:00:40", "00:00:47"),
    "01/04LP": ("00:00:48", "00:00:51"),
    "01/05": ("00:00:52", "00:00:55"),
    "01/06LP": ("00:00:56", "00:01:08"),
    "01/07": ("00:01:09", "00:01:27"),
    "01/08LP": ("00:01:28", "00:01:31"),
    "01/09": ("00:01:32", "00:01:47"),
    "01/10": ("00:01:48", "00:02:03"),
    "01/11FLASH": ("00:02:04", "00:02:07"),
    "01/12LP": ("00:02:08", "00:02:17"),
    "01/13": ("00:02:18", "00:02:44"),
    "01/14": ("00:02:45", "00:03:14"),
    "01/15": ("00:03:15", "00:03:34"),
    "01/16": ("00:03:35", "00:04:08"),
    "01/17": ("00:04:09", "00:07:08"),
    "01/18": ("00:07:09", "00:07:38"),
    "01/19": ("00:07:39", "00:08:44"),
    "01/20": ("00:08:45", "00:09:28"),
    "01/21": ("00:09:29", "00:10:39"),
    "01/22": ("00:10:40", "00:11:47"),
    "01/23": ("00:11:48", "00:12:27"),
    "01/24": ("00:12:28", "00:13:08"),
    "01/25": ("00:12:28", "00:13:08"),
    "01/26FLASH": ("00:13:09", "00:13:27"),
    "01/27FLASH": ("00:13:28", "00:13:39"),
    "01/28": ("00:13:40", "00:14:23"),
    "01/29": ("00:14:24", "00:15:58"),
    "01/30": ("00:15:59", "00:18:56"),
    "01/31": ("00:18:57", "00:20:39"),
    "01/32FLASH": ("00:19:59", "00:20:06"),
    "01/33": ("00:20:40", "00:23:39"),
    "01/34": ("00:23:40", "00:24:43"),
    "01/35": ("00:24:44", "00:26:44"),
    "01/36": ("00:26:45", "00:27:59"),
    "01/37": ("00:28:00", "00:29:24"),
    "01/38": ("00:29:25", "00:29:59"),
    "01/39": ("00:30:00", "00:32:27"),
    "01/40": ("00:32:28", "00:33:44"),
    "01/41": ("00:33:45", "00:34:39"),
    "01/42": ("00:34:40", "00:36:39"),
    "01/43": ("00:35:25", "00:36:47"),
    "01/44": ("00:36:48", "00:37:44"),
    "01/45": ("00:37:45", "00:40:09"),
    "01/46": ("00:40:10", "00:40:31"),
    "01/47": ("00:40:32", "00:40:46"),
    "01/48": ("00:40:47", "00:41:24"),
    "01/49": ("00:41:25", "00:43:14"),
    "01/50": ("00:43:15", "00:44:46"),
    "01/51": ("00:44:47", "00:45:24"),
    "01/52": ("00:45:25", "00:46:18"),
}


def _fold(value):
    return (value or "").strip().casefold()


def _episode_scenes():
    payload_path = Path(__file__).with_name("cierny_kamen_pdf_payload.json")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    scenes = [
        scene for scene in payload["scenes"]
        if scene.get("scene_id") in SCENE_TIMES
    ]
    scenes.sort(key=lambda item: item["order_in_episode"])
    return scenes


def _marker(scene_id):
    return f"<!-- {MARKER_PREFIX}{scene_id} -->"


def _attachment_name(scene_id):
    return f"{scene_id.replace('/', '_')}_original_screener.mp4"


def register_routes(app, helpers):
    trello_get = helpers["trello_get"]
    trello_post_body = helpers["trello_post_body"]
    trello_request = helpers["trello_request"]
    base = helpers["BASE"]
    api_key = helpers["API_KEY"]
    token = helpers["TOKEN"]

    @app.route("/api/original-screener-test", methods=["POST"])
    def original_screener_test():
        if request.headers.get("X-Original-Screener-Key") != ORIGINAL_SCREENER_KEY:
            return jsonify({"error": "forbidden"}), 403

        mode = request.args.get("mode", "dry-run").strip().casefold()
        if mode not in {"dry-run", "apply"}:
            return jsonify({"error": "mode must be dry-run or apply"}), 400

        scenes = _episode_scenes()
        scene_by_id = {scene["scene_id"]: scene for scene in scenes}
        requested_scene_id = (
            request.form.get("scene_id")
            or request.args.get("scene_id")
            or ""
        ).strip()
        if requested_scene_id and requested_scene_id not in scene_by_id:
            return jsonify({"error": "unknown scene_id"}), 400

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

        def source_cards_for(scene_id):
            marker = _marker(scene_id)
            return [
                card for card in cards
                if (card.get("name") or "").startswith(f"{scene_id}.")
                and marker not in (card.get("desc") or "")
            ]

        if mode == "dry-run" and not requested_scene_id:
            source_counts = {
                scene["scene_id"]: len(source_cards_for(scene["scene_id"]))
                for scene in scenes
            }
            invalid_sources = {
                scene_id: count for scene_id, count in source_counts.items()
                if count != 1
            }
            destination_cards = [
                card for card in cards
                if MARKER_PREFIX in (card.get("desc") or "")
            ]
            return jsonify({
                "status": "dry-run",
                "writes": 0,
                "board": {"name": board.get("name"), "url": board.get("url")},
                "list_name": LIST_NAME,
                "list_exists": bool(target_lists),
                "episode": 1,
                "scene_count": len(scenes),
                "source_cards_with_one_match": len(scenes) - len(invalid_sources),
                "invalid_source_matches": invalid_sources,
                "existing_destination_cards": len(destination_cards),
            }), 200

        scene_id = requested_scene_id or "01/01"
        scene = scene_by_id[scene_id]
        start_time, end_time = SCENE_TIMES[scene_id]
        source_cards = source_cards_for(scene_id)
        source_card = source_cards[0] if len(source_cards) == 1 else None
        plan = {
            "board": {"name": board.get("name"), "url": board.get("url")},
            "list_name": LIST_NAME,
            "list_exists": bool(target_lists),
            "scene_id": scene_id,
            "card_name": scene["name"],
            "time": f"{start_time}–{end_time}",
            "source_card": (
                {"name": source_card.get("name"), "url": source_card.get("shortUrl")}
                if source_card else None
            ),
            "source_card_matches": len(source_cards),
        }
        if mode == "dry-run":
            return jsonify({"status": "dry-run", "writes": 0, **plan}), 200
        if len(source_cards) != 1:
            return jsonify({"error": "source card match must equal one", **plan}), 409

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

        marker = _marker(scene_id)
        destination_cards = [
            card for card in cards
            if card.get("idList") == target_list["id"]
            and marker in (card.get("desc") or "")
        ]
        if len(destination_cards) > 1:
            return jsonify({"error": "duplicate destination cards", **plan}), 409

        description = (
            f"{marker}\n"
            f"**ZDROJOVÝ OBRAZ:** {scene_id}\n\n"
            f"**ČAS V ORIGINÁLNOM SCREENERI:** {start_time}–{end_time}\n\n"
            f"**ZDROJOVÁ KARTA:** {source_card.get('shortUrl')}\n\n"
            "Riverdale S01E01 rozdelený podľa obrazov zo scenára/Trello."
        )
        if destination_cards:
            card = destination_cards[0]
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
        attachment_name = _attachment_name(scene_id)
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
