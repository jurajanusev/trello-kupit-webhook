"""Daily props brief from scheduled scene cards, independent of Trello ToDo."""
import hashlib
import hmac
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import jsonify, request

PROJECTS = {
    "dunaj": ("qCPeWA3e", "DUNAJ"),
    "dok4": ("lzNy4AtY", "DOK"),
    "riverdale": ("CzuD55PR", "RIVERDALE"),
}
LIST_NAME = "Natáčanie – rekvizity"
START = "--- ZACIATOK AUTOMATICKEHO SUHRNU ---"
END = "--- KONIEC AUTOMATICKEHO SUHRNU ---"
SCENE = re.compile(r"^\s*\d+\s*/\s*\d+", re.I)
BODY_LIMIT = 22000


def list_date(name, as_of):
    match = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})\.(?:(\d{4})\.?)?\s*", name)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        if year:
            return date(int(year), int(month), int(day))
        candidates = []
        for offset in (-1, 0, 1):
            try:
                candidates.append(date(as_of.year + offset, int(month), int(day)))
            except ValueError:
                pass
        return min(candidates, key=lambda value: abs((value - as_of).days)) if candidates else None
    except ValueError:
        return None


def fold(value):
    return " ".join(value.upper().split())


def manual_notes(desc):
    match = re.search(r"(?mi)^#{1,6}\s+RUČNÉ DOPLNENIA\s*$", desc or "")
    if not match:
        return ""
    tail = desc[match.end():]
    return re.split(r"(?m)^#{1,6}\s+", tail, maxsplit=1)[0].strip()


def day_briefs(project, lists, cards, checklists, as_of, days=5):
    """No card due date or ToDo membership is required to include a scene."""
    last = as_of + timedelta(days=days - 1)
    dated_lists = {item["id"]: list_date(item["name"], as_of)
                   for item in lists if not item.get("closed")}
    dated_lists = {key: value for key, value in dated_lists.items()
                   if value is not None and as_of <= value <= last}
    by_card = defaultdict(list)
    for checklist in checklists:
        by_card[checklist["idCard"]].append(checklist)
    by_day = defaultdict(list)
    for card in cards:
        if not card.get("closed") and card.get("idList") in dated_lists:
            by_day[dated_lists[card["idList"]]].append(card)
    briefs = []
    for shooting_date, day_cards in sorted(by_day.items()):
        blocks = []
        scene_count = props_count = 0
        consolidated = {}
        warnings = []
        for card in sorted(day_cards, key=lambda value: value.get("pos", 0)):
            name = card.get("name", "")
            link = card.get("shortUrl") or f"https://trello.com/c/{card['id']}"
            lines = [name, link]
            if not SCENE.match(name):
                lines += ["POZNÁMKA / PRÍPRAVA DŇA:", card.get("desc", "")]
            else:
                scene_count += 1
                cls = sorted(by_card.get(card["id"], []), key=lambda item: item.get("pos", 0))
                expected = set(card.get("idChecklists", []))
                returned = {item["id"] for item in cls}
                if expected - returned:
                    raise ValueError(f"Missing checklists for {link}")
                props = [item for item in cls if fold(item["name"]) == "REKVIZITY"]
                if not props or not any(item.get("checkItems") for item in props):
                    warning = f"{name.split('.')[0]}: prázdny/chýbajúci checklist REKVIZITY – preveriť scenár"
                    warnings.append(warning)
                    lines += ["POZOR: REKVIZITY nie sú vypísané. Neznamená to, že nie sú potrebné."]
                for checklist in cls:
                    items = sorted(checklist.get("checkItems", []), key=lambda value: value.get("pos", 0))
                    if not items:
                        continue
                    lines.append(checklist["name"] + ":")
                    for item in items:
                        if fold(checklist["name"]) == "REKVIZITY":
                            props_count += 1
                            prop_name = item.get("name", "").strip()
                            entry = consolidated.setdefault(prop_name, {"scenes": [], "checked": True})
                            scene_id = re.match(r"\s*(\d+\s*/\s*\d+[A-Za-z]*)", name).group(1)
                            if scene_id not in entry["scenes"]:
                                entry["scenes"].append(scene_id)
                            entry["checked"] = entry["checked"] and item.get("state", "").lower() == "complete"
                        status = "zaškrtnuté v Trello" if item.get("state", "").lower() == "complete" else "nezaškrtnuté"
                        lines.append(f"- [{status}] {item.get('name', '')}")
                manual = manual_notes(card.get("desc", ""))
                if manual:
                    lines += ["RUČNÉ DOPLNENIA:", manual]
                schedule_dates = re.findall(r"DÁTUM NATÁČANIA:\*{0,2}\s*(\d{4}-\d{2}-\d{2})", card.get("desc", ""))
                if schedule_dates and schedule_dates[0] != shooting_date.isoformat():
                    warning = f"Rozpor dátumu na {link}: stĺpec {shooting_date}, metadata {schedule_dates[0]}"
                    warnings.append(warning)
                    lines.append("POZOR: " + warning)
            blocks.append("\n".join(lines))
        if not scene_count:
            continue
        if consolidated:
            prop_lines = ["SÚHRNNÝ ZOZNAM REKVIZÍT NA DEŇ:"]
            for prop_name, entry in consolidated.items():
                status = "zaškrtnuté vo všetkých výskytoch" if entry["checked"] else "preveriť prípravu / nezaškrtnuté"
                prop_lines.append(f"- {prop_name} | obrazy: {', '.join(entry['scenes'])} | {status}")
            blocks.insert(0, "\n".join(prop_lines) + "\n\nPODROBNOSTI PODĽA OBRAZOV:")
        intro = (f"{PROJECTS[project][1]} | {shooting_date.strftime('%d.%m.%Y')}\n"
                 f"Obrazy: {scene_count} | Položky REKVIZITY: {props_count}\n"
                 "Zdroj: obrazové karty v dátumových stĺpcoch Trella.\n"
                 "Stav zaškrtnutia je údaj z Trella, nie potvrdenie fyzického stavu.\n"
                 "Rovnaké predmety sú uvedené pri každom obraze; množstvá sa nesčítavajú naslepo.\n\n")
        # Split on whole lines rather than silently truncating long days.
        chunks = []
        chunk = intro
        for block in blocks:
            for line in (block + "\n").splitlines():
                while len(line) > BODY_LIMIT - len(intro) - 100:
                    cut = BODY_LIMIT - len(intro) - 100
                    if chunk.strip() != intro.strip():
                        chunks.append(chunk.rstrip()); chunk = intro
                    chunks.append(intro + line[:cut]); line = line[cut:]
                if len(chunk) + len(line) + 1 > BODY_LIMIT:
                    chunks.append(chunk.rstrip()); chunk = intro
                chunk += line + "\n"
        if chunk.strip() != intro.strip():
            chunks.append(chunk.rstrip())
        for part, content in enumerate(chunks, 1):
            marker = f"SHOOTING PROPS: {project}:{shooting_date.isoformat()}:{part}"
            digest = hashlib.sha256(content.encode()).hexdigest()
            body = f"{START}\n{marker}\nSOURCE SHA256: {digest}\n{content}\n{END}"
            suffix = f" ({part}/{len(chunks)})" if len(chunks) > 1 else ""
            briefs.append({"marker": marker, "digest": digest, "body": body,
                           "title": f"{PROJECTS[project][1]} | {shooting_date.strftime('%d.%m.')} | Rekvizity na natáčanie{suffix}",
                           "date": shooting_date.isoformat(), "part": part,
                           "parts": len(chunks), "scene_count": scene_count,
                           "prop_count": props_count, "unique_prop_count": len(consolidated), "warnings": warnings})
    return briefs


def task_plan(brief, tasks):
    matches = [task for task in tasks if re.search(
        r"(?m)^" + re.escape(brief["marker"]) + r"\s*$",
        (task.get("body") or {}).get("content", "").replace("\r\n", "\n"))]
    if len(matches) > 1:
        raise ValueError("Duplicate daily brief identity")
    if not matches:
        return {"action": "create", "task": None, "changes": {}}
    task = matches[0]
    if task.get("status") == "completed":
        return {"action": "completed", "task": task, "changes": {}}
    body = (task.get("body") or {}).get("content", "")
    changes = {}
    if f"SOURCE SHA256: {brief['digest']}" not in body:
        if START not in body or END not in body:
            raise ValueError("Managed brief boundaries missing")
        beginning, rest = body.split(START, 1)
        _, ending = rest.split(END, 1)
        changes["body"] = {"contentType": "text", "content": beginning + brief["body"] + ending}
    if task.get("title") != brief["title"]:
        changes["title"] = brief["title"]
    return {"action": "update" if changes else "unchanged", "task": task, "changes": changes}


def register_routes(app, api):
    @app.route("/api/shooting-props-brief/<project>", methods=["POST"])
    def shooting_props_brief(project):
        # Reuse the already configured, user-authorized sync credential.
        if not hmac.compare_digest(request.headers.get("X-Microsoft-Sync-Key", ""),
                                   "dunaj-ms-todo-sync-19jul-84c2f1a7"):
            return jsonify({"error": "forbidden"}), 403
        if project not in PROJECTS:
            return jsonify({"error": "unknown project"}), 404
        mode = request.args.get("mode", "dry-run")
        if mode not in {"dry-run", "apply"}:
            return jsonify({"error": "invalid mode"}), 400
        try:
            days = int(request.args.get("days", "5"))
            limit = int(request.args.get("limit", "2"))
            as_of = date.fromisoformat(request.args["as_of"]) if request.args.get("as_of") else datetime.now(ZoneInfo("Europe/Bratislava")).date()
            if not 1 <= days <= 31 or not 1 <= limit <= 3:
                raise ValueError()
        except ValueError:
            return jsonify({"error": "invalid days, limit, or as_of"}), 400
        board = PROJECTS[project][0]
        lists = api["trello_get"](f"/boards/{board}/lists", {"filter": "open", "fields": "name,closed,pos"})
        cards = api["trello_get"](f"/boards/{board}/cards", {
            "filter": "open", "fields": "name,desc,idList,pos,shortUrl,closed,idChecklists"})
        checklists = api["trello_get"](f"/boards/{board}/checklists", {
            "fields": "name,idCard,pos", "checkItems": "all", "checkItem_fields": "name,state,pos"})
        try:
            briefs = day_briefs(project, lists, cards, checklists, as_of, days)
        except ValueError as exc:
            return jsonify({"error": str(exc), "writes": 0}), 409
        if not api["microsoft_enabled"]():
            return jsonify({"error": "Microsoft is not configured", "briefs": briefs}), 503
        token = api["get_microsoft_access_token"]()
        ms_lists = api["graph_get_all"]("/me/todo/lists", token)
        targets = [item for item in ms_lists if item.get("displayName") == LIST_NAME]
        if len(targets) > 1:
            return jsonify({"error": "ambiguous destination list", "writes": 0}), 409
        target = targets[0] if targets else None
        tasks = api["graph_get_all"](f"/me/todo/lists/{target['id']}/tasks", token) if target else []
        try:
            plans = [{**brief, **task_plan(brief, tasks)} for brief in briefs]
        except ValueError as exc:
            return jsonify({"error": str(exc), "writes": 0}), 409
        summary = {"project": PROJECTS[project][1], "list_name": LIST_NAME,
                   "window_start": as_of.isoformat(),
                   "window_end": (as_of + timedelta(days=days - 1)).isoformat(),
                   "timezone": "Europe/Bratislava", "briefs": len(plans),
                   "shooting_days": len({b["date"] for b in briefs}),
                   "to_create": sum(p["action"] == "create" for p in plans),
                   "to_update": sum(p["action"] == "update" for p in plans),
                   "unchanged": sum(p["action"] == "unchanged" for p in plans),
                   "completed": sum(p["action"] == "completed" for p in plans)}
        if mode == "dry-run":
            return jsonify({"status": "dry-run", **summary,
                            "days": [{k: p[k] for k in ("title", "date", "part", "parts", "scene_count", "prop_count", "unique_prop_count", "warnings", "action", "body")} for p in plans]})
        actionable = [plan for plan in plans if plan["action"] in {"create", "update"}]
        if actionable and not target:
            target = api["graph_post"]("/me/todo/lists", token, {"displayName": LIST_NAME})
        changed = []
        for plan in actionable[:limit]:
            base = f"/me/todo/lists/{target['id']}/tasks"
            if plan["action"] == "create":
                task = api["graph_post"](base, token, {
                    "title": plan["title"], "body": {"contentType": "text", "content": plan["body"]},
                    "dueDateTime": {"dateTime": plan["date"] + "T12:00:00", "timeZone": "Central Europe Standard Time"}})
            else:
                task = api["graph_patch"](base + "/" + plan["task"]["id"], token, plan["changes"])
            changed.append({"title": plan["title"], "action": plan["action"], "task_id": task["id"]})
        return jsonify({"status": "applied", **summary, "changed": changed,
                        "remaining": max(0, len(actionable) - limit)})
