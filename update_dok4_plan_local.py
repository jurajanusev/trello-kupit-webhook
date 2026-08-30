import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


BASE = "https://api.trello.com/1"
BOARD_REF = "lzNy4AtY"
WINDOW_SHOOTING_DAYS = 7
START_MARKER = "<!-- DOK4-SCHEDULE-METADATA:START -->"
END_MARKER = "<!-- DOK4-SCHEDULE-METADATA:END -->"
DATE_LIST_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.$")
SCENE_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d+[A-Z]*)(?:\.|\s|$)", re.I)
CANONICAL_CARD_IDS = {
    "05/26": "6a10d965fb3475dfaaa0b7b0",
    "09/23": "6a5631d02a3481e3d024ff28",
}


def load_env(path):
    result = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


class Trello:
    def __init__(self, key, token):
        self.auth = {"key": key, "token": token}

    def request(self, method, path, params=None, data=None):
        query = dict(self.auth)
        if params:
            query.update(params)
        url = BASE + path + "?" + urlencode(query)
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = Request(url, data=body, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json; charset=utf-8")
        for attempt in range(5):
            try:
                with urlopen(request, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429 or 500 <= exc.code < 600:
                    if attempt < 4:
                        __import__("time").sleep(2 ** attempt)
                        continue
                raise RuntimeError(
                    f"Trello {method} {path} failed: {exc.code} {details[:1000]}"
                ) from exc

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, data):
        return self.request("POST", path, data=data)

    def put(self, path, data):
        return self.request("PUT", path, data=data)


def normalize_scene(episode, scene):
    return f"{int(episode):02d}/{str(scene).upper().lstrip('0') or '0'}"


def scene_numeric_base(scene_id):
    """Drop every letter suffix from a normalized scene identifier."""
    return re.sub(r"[A-Z]+$", "", scene_id.upper())


def fallback_scene_ids(scene_id):
    """Return safe card variants from most specific to the numeric base.

    A leading R marks a retake in supplied plans, while a following letter
    (for example L in RL) can still identify the existing Trello card.
    """
    match = re.fullmatch(r"(\d{2}/\d+)([A-Z]+)", scene_id, flags=re.I)
    if not match:
        return []
    base, suffix = match.groups()
    candidates = []
    if len(suffix) > 1 and suffix.upper().startswith("R"):
        candidates.append(base + suffix[1:].upper())
    candidates.append(base)
    return list(dict.fromkeys(candidates))


def date_list_name(date_text):
    _, month, day = (int(value) for value in date_text.split("-"))
    return f"{day}.{month}."


def metadata(
    row, source_date, start_marker=START_MARKER, end_marker=END_MARKER,
    source_label="predbežné dispo DOK 4",
):
    source_date = row.get("source_date", source_date)
    source_day = datetime.strptime(source_date, "%Y-%m-%d").date()
    source_date_display = f"{source_day.day}. {source_day.month}. {source_day.year}"
    return (
        f"{start_marker}\n"
        f"**ČÍSLO OBRAZU:** {row['scene_id']}\n"
        f"**ZDROJ:** {source_label} z {source_date_display}\n"
        f"**NATÁČACÍ DEŇ:** {row['shooting_day']}\n"
        f"**DÁTUM NATÁČANIA:** {row['shooting_date']}\n"
        f"**PORADIE DŇA:** {row['order']}\n"
        f"**UNIT:** {row['unit']}\n"
        f"**LOKÁCIA:** {row['location']}\n"
        f"**POSTAVY:** {row['characters']}\n"
        f"{end_marker}"
    )


def merged_description(
    old_desc, row, source_date, start_marker=START_MARKER,
    end_marker=END_MARKER, source_label="predbežné dispo DOK 4",
):
    block = metadata(row, source_date, start_marker, end_marker, source_label)
    if start_marker in old_desc and end_marker in old_desc:
        pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
        return re.sub(pattern, lambda _: block, old_desc, count=1, flags=re.S)
    return block + ("\n\n" + old_desc if old_desc else "")


def pick_anchor(lists):
    preferred = ["VŠETKY EPIZÓDY", "SCENÁRE", "SERIA 4", "SÉRIA 4"]
    by_folded = {item["name"].strip().casefold(): item for item in lists}
    for name in preferred:
        if name.casefold() in by_folded:
            return by_folded[name.casefold()]
    candidates = [item for item in lists if "epiz" in item["name"].casefold() or "scen" in item["name"].casefold()]
    return sorted(candidates, key=lambda item: item["pos"])[0] if candidates else None


def build_state(
    trello, schedule, source_date, as_of, board_ref=BOARD_REF,
    start_marker=START_MARKER, end_marker=END_MARKER,
    source_label="predbežné dispo DOK 4", ignore_scene_suffix=False,
):
    board = trello.get(f"/boards/{board_ref}", {"fields": "id,name,url,shortLink"})
    lists = trello.get(f"/boards/{board['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "open"
    })
    lists.sort(key=lambda item: item["pos"])
    lists_by_id = {item["id"]: item for item in lists}
    lists_by_name = {}
    for item in lists:
        lists_by_name.setdefault(item["name"], []).append(item)

    def fetch_list_cards(board_list):
        result = []
        before = None
        seen_page_ends = set()
        while True:
            params = {
                "fields": "id,name,desc,idList,shortUrl,due,dueComplete,pos,closed",
                "filter": "open", "limit": 1000,
            }
            if before:
                params["before"] = before
            page = trello.get(f"/lists/{board_list['id']}/cards", params)
            result.extend(page)
            if len(page) < 1000:
                break
            page_end = page[-1]["id"]
            if page_end in seen_page_ends:
                raise RuntimeError("Trello card pagination did not advance")
            seen_page_ends.add(page_end)
            before = page_end
        return result

    cards = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for list_cards in pool.map(fetch_list_cards, lists):
            cards.extend(list_cards)
    cards = list({card["id"]: card for card in cards}.values())
    cards_by_scene = {}
    cards_by_numeric_base = {}
    for card in cards:
        match = SCENE_RE.match(card.get("name", ""))
        if match:
            card_scene_id = normalize_scene(match.group(1), match.group(2))
            cards_by_scene.setdefault(card_scene_id, []).append(card)
            cards_by_numeric_base.setdefault(
                scene_numeric_base(card_scene_id), []
            ).append(card)

    matches = []
    missing = []
    duplicates = []
    resolved_duplicates = []
    ignored_reference_duplicates = []
    fallbacks = []
    card_usage = {}
    for row in schedule:
        planned_id = row["scene_id"]
        matched_id = planned_id
        candidates = cards_by_scene.get(planned_id, [])
        fallback = False
        if not candidates and ignore_scene_suffix:
            matched_id = scene_numeric_base(planned_id)
            candidates = cards_by_numeric_base.get(matched_id, [])
            fallback = bool(candidates)
        if not candidates:
            for fallback_id in fallback_scene_ids(planned_id):
                fallback_candidates = cards_by_scene.get(fallback_id, [])
                if fallback_candidates:
                    matched_id = fallback_id
                    candidates = fallback_candidates
                    fallback = True
                    break
        if not candidates:
            missing.append({"scene_id": planned_id, "base_id": matched_id, "date": row["shooting_date"]})
            continue
        if len(candidates) > 1:
            working = [
                card for card in candidates
                if lists_by_id[card["idList"]]["name"].strip().casefold() != "original screener"
            ]
            references = [card for card in candidates if card not in working]
            if len(working) == 1 and references:
                ignored_reference_duplicates.append({
                    "scene_id": planned_id,
                    "selected": {"id": working[0]["id"], "url": working[0]["shortUrl"]},
                    "ignored": [{"id": card["id"], "url": card["shortUrl"]} for card in references],
                })
                candidates = working
        if len(candidates) > 1 and CANONICAL_CARD_IDS.get(planned_id):
            canonical_id = CANONICAL_CARD_IDS[planned_id]
            canonical = next((card for card in candidates if card["id"] == canonical_id), None)
            if canonical:
                resolved_duplicates.append({
                    "scene_id": planned_id,
                    "canonical": {"id": canonical["id"], "url": canonical["shortUrl"]},
                    "to_archive": [{"id": card["id"], "url": card["shortUrl"]}
                                   for card in candidates if card["id"] != canonical_id],
                })
                candidates = [canonical]
        if len(candidates) != 1:
            duplicates.append({
                "scene_id": planned_id, "matched_id": matched_id,
                "cards": [{"id": c["id"], "name": c["name"], "url": c["shortUrl"],
                           "list": lists_by_id[c["idList"]]["name"],
                           "description_length": len(c.get("desc", "")),
                           "check_due": c.get("due"), "due_complete": c.get("dueComplete")}
                          for c in candidates],
            })
            continue
        card = candidates[0]
        card_usage.setdefault(card["id"], []).append(planned_id)
        item = {"row": row, "card": card, "matched_id": matched_id, "fallback": fallback}
        matches.append(item)
        if fallback:
            fallbacks.append({
                "planned_id": planned_id, "base_id": matched_id, "name": card["name"],
                "url": card["shortUrl"], "list": lists_by_id[card["idList"]]["name"],
            })
    reused_cards = [{"card_id": card_id, "scene_ids": ids} for card_id, ids in card_usage.items() if len(ids) > 1]
    shooting_dates = sorted({
        row["shooting_date"] for row in schedule if row["shooting_date"] >= as_of
    })[:WINDOW_SHOOTING_DAYS]
    shooting_date_set = set(shooting_dates)
    selected_matches = []
    for card_id in card_usage:
        options = [item for item in matches if item["card"]["id"] == card_id]
        options.sort(key=lambda item: (
            item["row"]["shooting_date"] not in shooting_date_set,
            item["row"]["shooting_date"], item["row"]["order"],
        ))
        selected_matches.append(options[0])
    matches = selected_matches

    reused_card_conflicts = []
    schedule_by_scene = {row["scene_id"]: row for row in schedule}
    for reused in reused_cards:
        options = [schedule_by_scene[scene_id] for scene_id in reused["scene_ids"]]
        destinations = {
            ("active", row["shooting_date"])
            if row["shooting_date"] in shooting_date_set
            else ("inactive", None)
            for row in options
        }
        active_destinations = {value for value in destinations if value[0] == "active"}
        if len(active_destinations) > 1:
            reused_card_conflicts.append({
                **reused,
                "destinations": [list(value) for value in sorted(destinations)],
            })
    window_rows = [row for row in schedule if row["shooting_date"] in shooting_date_set]
    target_names = {date: date_list_name(date) for date in shooting_dates}
    missing_lists = [name for name in target_names.values() if name not in lists_by_name]
    duplicate_target_lists = {
        name: [{"id": item["id"], "pos": item["pos"]} for item in values]
        for name, values in lists_by_name.items() if name in target_names.values() and len(values) > 1
    }
    window_matches = [item for item in matches if item["row"]["shooting_date"] in shooting_date_set]
    expected_window_card_ids = {item["card"]["id"] for item in window_matches}
    stale_window_cards = [
        card for card in cards
        if DATE_LIST_RE.match(lists_by_id[card["idList"]]["name"])
        and SCENE_RE.match(card.get("name", ""))
        and card["id"] not in expected_window_card_ids
    ]
    window_moves = []
    for item in window_matches:
        current_name = lists_by_id[item["card"]["idList"]]["name"]
        target_name = target_names[item["row"]["shooting_date"]]
        if current_name != target_name:
            window_moves.append({
                "scene_id": item["row"]["scene_id"], "from": current_name, "to": target_name,
                "date": item["row"]["shooting_date"], "order": item["row"]["order"],
                "url": item["card"]["shortUrl"],
            })

    update_count = 0
    for item in matches:
        expected_desc = merged_description(
            item["card"].get("desc", ""), item["row"], source_date,
            start_marker, end_marker, source_label,
        )
        expected_date = (
            item["row"]["shooting_date"]
            if item["row"]["shooting_date"] in shooting_date_set else ""
        )
        if expected_desc != item["card"].get("desc", "") or (item["card"].get("due") or "")[:10] != expected_date:
            update_count += 1

    anchor = pick_anchor(lists)
    date_lists = []
    for item in lists:
        match = DATE_LIST_RE.match(item["name"])
        if match:
            date_lists.append((int(match.group(2)), int(match.group(1)), item))
    date_lists.sort(key=lambda value: (value[0], value[1]))

    return {
        "board": board, "lists": lists, "lists_by_id": lists_by_id,
        "lists_by_name": lists_by_name, "cards": cards, "matches": matches,
        "missing": missing, "duplicates": duplicates, "resolved_duplicates": resolved_duplicates,
        "ignored_reference_duplicates": ignored_reference_duplicates,
        "fallbacks": fallbacks,
        "reused_cards": reused_cards,
        "reused_card_conflicts": reused_card_conflicts,
        "window_rows": window_rows,
        "window_matches": window_matches, "window_moves": window_moves,
        "stale_window_cards": stale_window_cards,
        "shooting_dates": shooting_dates, "target_names": target_names,
        "missing_lists": missing_lists, "duplicate_target_lists": duplicate_target_lists,
        "update_count": update_count, "anchor": anchor, "date_lists": date_lists,
        "as_of": as_of, "source_date": source_date, "board_ref": board_ref,
        "start_marker": start_marker, "end_marker": end_marker,
        "source_label": source_label,
    }


def summary(state, schedule):
    by_date = {}
    for row in state["window_rows"]:
        by_date.setdefault(row["shooting_date"], 0)
        by_date[row["shooting_date"]] += 1
    return {
        "status": "dry-run",
        "board": state["board"]["name"], "board_url": state["board"]["url"],
        "board_short_link": state["board"]["shortLink"],
        "schedule_rows": len(schedule), "schedule_unique_scene_ids": len({row['scene_id'] for row in schedule}),
        "board_open_lists": len(state["lists"]), "board_open_cards": len(state["cards"]),
        "matched_unique": len(state["matches"]), "missing_count": len(state["missing"]),
        "missing": state["missing"], "duplicate_scene_ids_count": len(state["duplicates"]),
        "duplicates": state["duplicates"], "fallback_count": len(state["fallbacks"]),
        "resolved_duplicates": state["resolved_duplicates"],
        "ignored_reference_duplicates": state.get("ignored_reference_duplicates", []),
        "fallbacks": state["fallbacks"], "reused_card_count": len(state["reused_cards"]),
        "shared_fallback_card_count": len(state["reused_cards"]),
        "shared_fallback_cards": state["reused_cards"],
        "fallback_collision_count": len(state["reused_card_conflicts"]),
        "fallback_collisions": state["reused_card_conflicts"],
        "reused_cards": state["reused_cards"], "metadata_due_to_update": state["update_count"],
        "window_type": "next_shooting_days", "window_shooting_days": WINDOW_SHOOTING_DAYS,
        "window_as_of": state["as_of"],
        "window_start": (state["shooting_dates"][0] if state["shooting_dates"] else None),
        "window_end": (state["shooting_dates"][-1] if state["shooting_dates"] else None),
        "window_schedule_rows": len(state["window_rows"]), "window_matches": len(state["window_matches"]),
        "window_to_move": len(state["window_moves"]), "window_moves": state["window_moves"],
        "stale_window_count": len(state["stale_window_cards"]),
        "stale_window_cards": [{
            "name": card["name"], "url": card["shortUrl"],
            "from": state["lists_by_id"][card["idList"]]["name"],
        } for card in state["stale_window_cards"]],
        "shooting_dates": state["shooting_dates"],
        "shooting_days_selected": len(state["shooting_dates"]),
        "rows_by_date": by_date, "missing_target_lists": state["missing_lists"],
        "duplicate_target_lists": state["duplicate_target_lists"],
        "series_anchor": ({"name": state["anchor"]["name"], "pos": state["anchor"]["pos"]}
                          if state["anchor"] else None),
        "existing_date_lists": [item[2]["name"] for item in state["date_lists"]],
        "board_list_order": [item["name"] for item in state["lists"]],
    }


def apply(trello, state, metadata_only=False, skip_metadata=False, metadata_limit=None):
    blockers = {
        "wrong_board": state["board"].get("shortLink") != state.get("board_ref", BOARD_REF),
        "duplicates": len(state["duplicates"]),
        "fallback_collisions": len(state.get("reused_card_conflicts", [])),
        "duplicate_target_lists": len(state["duplicate_target_lists"]),
        "missing_anchor": state["anchor"] is None,
    }
    if any(blockers.values()):
        raise RuntimeError("apply blocked: " + json.dumps(blockers, ensure_ascii=False))

    lists_by_name = {name: values[0] for name, values in state["lists_by_name"].items()}
    created_lists = []
    if not metadata_only:
        for date in state["shooting_dates"]:
            name = state["target_names"][date]
            if name not in lists_by_name:
                item = trello.post("/lists", {"idBoard": state["board"]["id"], "name": name, "pos": "bottom"})
                lists_by_name[name] = item
                created_lists.append(name)

    stale_returned = [] if metadata_only else cleanup_stale(trello, state)

    metadata_due_updated = []
    metadata_errors = []
    unchanged = 0
    metadata_processed = 0
    for item in ([] if skip_metadata else state["matches"]):
        row = item["row"]
        card = item["card"]
        payload = {}
        new_desc = merged_description(
            card.get("desc", ""), row, state["source_date"],
            state.get("start_marker", START_MARKER),
            state.get("end_marker", END_MARKER),
            state.get("source_label", "predbežné dispo DOK 4"),
        )
        if new_desc != card.get("desc", ""):
            payload["desc"] = new_desc
        expected_due_date = (
            row["shooting_date"] if row["shooting_date"] in state["shooting_dates"] else ""
        )
        if (card.get("due") or "")[:10] != expected_due_date:
            payload["due"] = (
                f"{expected_due_date}T10:00:00.000Z" if expected_due_date else ""
            )
        if payload:
            if metadata_limit is not None and metadata_processed >= metadata_limit:
                continue
            metadata_processed += 1
            try:
                result = trello.put(f"/cards/{card['id']}", payload)
                metadata_due_updated.append({
                    "scene_id": row["scene_id"], "url": result["shortUrl"],
                    "fields": sorted(payload),
                })
            except Exception as exc:
                metadata_errors.append({
                    "scene_id": row["scene_id"], "url": card["shortUrl"],
                    "fields": sorted(payload), "error": str(exc),
                })
        else:
            unchanged += 1

    if metadata_only:
        return {
            "status": "metadata-batch-applied",
            "metadata_due_updated": len(metadata_due_updated),
            "metadata_due_unchanged": unchanged,
            "metadata_errors_count": len(metadata_errors),
            "metadata_errors": metadata_errors,
        }

    moved = []
    reordered = []
    move_errors = []
    window_unchanged = 0
    for item in sorted(state["window_matches"], key=lambda value: (value["row"]["shooting_date"], value["row"]["order"])):
        row = item["row"]
        card = item["card"]
        target = lists_by_name[state["target_names"][row["shooting_date"]]]
        expected_pos = row["order"] * 16384
        payload = {}
        if card["idList"] != target["id"]:
            payload["idList"] = target["id"]
        if abs(float(card.get("pos") or 0) - expected_pos) > 0.5:
            payload["pos"] = expected_pos
        current_name = state["lists_by_id"][card["idList"]]["name"]
        if "NATOČEN" in current_name.upper() or card.get("dueComplete"):
            payload["dueComplete"] = False
        if not payload:
            window_unchanged += 1
            continue
        try:
            result = trello.put(f"/cards/{card['id']}", payload)
            entry = {
                "scene_id": row["scene_id"], "list": target["name"],
                "order": row["order"], "url": result["shortUrl"],
            }
            (moved if "idList" in payload else reordered).append(entry)
        except Exception as exc:
            move_errors.append({
                "scene_id": row["scene_id"], "url": card["shortUrl"],
                "target_list": target["name"], "error": str(exc),
            })

    archived_old_lists = []
    retained_old_lists = []
    active_date_names = set(state["target_names"].values())
    for _, _, old_list in state["date_lists"]:
        if old_list["name"] in active_date_names:
            continue
        remaining_cards = trello.get(f"/lists/{old_list['id']}/cards", {
            "fields": "id,name,shortUrl", "filter": "open", "limit": 1000,
        })
        if remaining_cards:
            retained_old_lists.append({
                "name": old_list["name"], "remaining_cards": len(remaining_cards),
            })
        else:
            trello.put(f"/lists/{old_list['id']}", {"closed": True})
            archived_old_lists.append(old_list["name"])

    refreshed_lists = trello.get(f"/boards/{state['board']['id']}/lists", {
        "fields": "id,name,pos,closed", "filter": "open"
    })
    refreshed_lists.sort(key=lambda item: item["pos"])
    anchor = pick_anchor(refreshed_lists)
    date_items = []
    for item in refreshed_lists:
        match = DATE_LIST_RE.match(item["name"])
        if match:
            date_items.append((int(match.group(2)), int(match.group(1)), item))
    date_items.sort(key=lambda value: (value[0], value[1]))
    date_ids = {item[2]["id"] for item in date_items}
    following = [item for item in refreshed_lists if item["id"] not in date_ids and item["pos"] > anchor["pos"]]
    if following:
        next_pos = following[0]["pos"]
        step = (next_pos - anchor["pos"]) / (len(date_items) + 1)
    else:
        step = 16384
    list_order_updates = []
    list_order_errors = []
    for index, (_, _, item) in enumerate(date_items, start=1):
        desired_pos = anchor["pos"] + step * index
        try:
            result = trello.put(f"/lists/{item['id']}", {"pos": desired_pos})
            list_order_updates.append({"name": result["name"], "pos": result["pos"]})
        except Exception as exc:
            list_order_errors.append({"name": item["name"], "error": str(exc)})

    archived_duplicates = []
    for item in state["resolved_duplicates"]:
        for duplicate in item["to_archive"]:
            trello.put(f"/cards/{duplicate['id']}", {"closed": True})
            archived_duplicates.append({"scene_id": item["scene_id"], "url": duplicate["url"]})

    return {
        "status": "applied", "created_lists": created_lists,
        "metadata_due_updated": len(metadata_due_updated), "metadata_due_unchanged": unchanged,
        "metadata_errors_count": len(metadata_errors), "metadata_errors": metadata_errors,
        "moved_count": len(moved), "reordered_count": len(reordered),
        "window_unchanged": window_unchanged,
        "move_errors_count": len(move_errors), "move_errors": move_errors,
        "list_order_updates": list_order_updates, "moved": moved,
        "list_order_errors_count": len(list_order_errors),
        "list_order_errors": list_order_errors,
        "archived_old_lists": archived_old_lists,
        "retained_old_lists": retained_old_lists,
        "missing_skipped": state["missing"], "archived_duplicates": archived_duplicates,
        "stale_returned": stale_returned,
    }


def cleanup_stale(trello, state):
    if state["board"].get("shortLink") != state.get("board_ref", BOARD_REF) or not state["anchor"]:
        raise RuntimeError("cleanup blocked: wrong board or missing series anchor")
    returned = []
    for card in state["stale_window_cards"]:
        result = trello.put(f"/cards/{card['id']}", {
            "idList": state["anchor"]["id"], "pos": "bottom",
            "due": "", "dueComplete": False,
        })
        returned.append({
            "name": result["name"], "url": result["shortUrl"],
            "from": state["lists_by_id"][card["idList"]]["name"],
            "to": state["anchor"]["name"], "due_cleared": True,
        })
    return returned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--mode", choices=("dry-run", "apply", "cleanup"), default="dry-run")
    parser.add_argument(
        "--as-of",
        default=datetime.now(ZoneInfo("Europe/Bratislava")).date().isoformat(),
        help="First eligible calendar date (YYYY-MM-DD); selects the next 7 shooting dates.",
    )
    args = parser.parse_args()
    env = load_env(args.env)
    trello = Trello(env.get("TRELLO_API_KEY") or env["TRELLO_KEY"], env["TRELLO_TOKEN"])
    schedule_document = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    schedule = schedule_document["rows"]
    source_date = schedule_document.get("source", {}).get("dated", args.as_of)
    state = build_state(trello, schedule, source_date, args.as_of)
    if args.mode == "dry-run":
        result = summary(state, schedule)
    elif args.mode == "cleanup":
        result = {"status": "cleanup-applied", "stale_returned": cleanup_stale(trello, state)}
    else:
        result = apply(trello, state)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
