processed_actions = set()

from flask import Flask, request, jsonify
from flask import send_from_directory
from pathlib import Path
import re
import requests
import os
import unicodedata

app = Flask(__name__)

API_KEY = os.environ["TRELLO_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]
MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET")
MICROSOFT_REFRESH_TOKEN = os.environ.get("MICROSOFT_REFRESH_TOKEN")
MICROSOFT_AUTHORITY = os.environ.get("MICROSOFT_AUTHORITY", "consumers")
TODO_LIST_ID = os.environ.get("TODO_LIST_ID")
TODO_TASK_TITLE_TEMPLATE = os.environ.get("TODO_TASK_TITLE_TEMPLATE", "{item} - {card}")

DEFAULT_BOARD_CONFIG = {
    "69cd95eed6bf6120fee7dd22": {
        "target_list_id": "69e53446a823be00f2e5e837"
    },

    "69f74077554ff079f9472308": {
        "target_list_id": "6a057f30a60d4ab5aee502b6"
    },

    # DOK4: VSETKY EPIZODY -> ToDo
    "6a3d776cbd0488b47076d8e6": {
        "target_list_id": "6a4776f530468dee7ea5fbfc"
    },

    # DOK4: SCENARE -> ToDo
    "6a4524898cb771a99433699b": {
        "target_list_id": "6a4776f530468dee7ea5fbfc"
    }
}


def load_board_config():
    """
    SOURCE_TARGET_LISTS format:
    source_list_id:target_list_id,source_list_id:target_list_id
    """
    raw = os.environ.get("SOURCE_TARGET_LISTS", "").strip()
    if not raw:
        return DEFAULT_BOARD_CONFIG

    # Environment mappings override defaults, but do not accidentally remove
    # another board that was added to the built-in configuration later.
    config = {
        source_list_id: values.copy()
        for source_list_id, values in DEFAULT_BOARD_CONFIG.items()
    }
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue

        if ":" not in pair:
            raise RuntimeError(f"Invalid SOURCE_TARGET_LISTS pair: {pair}")

        source_list_id, target_list_id = pair.split(":", 1)
        source_list_id = source_list_id.strip()
        target_list_id = target_list_id.strip()

        if source_list_id and target_list_id:
            config[source_list_id] = {"target_list_id": target_list_id}

    return config


BOARD_CONFIG = load_board_config()

CHECKLIST_TAG = os.environ.get("CHECKLIST_TAG", "[Z]")

BASE = "https://api.trello.com/1"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def trello_get(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.get(f"{BASE}{path}", params=params, timeout=20)

    if not r.ok:
        print("TRELLO GET ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_post(path, params=None):
    params = params or {}
    params.update({"key": API_KEY, "token": TOKEN})
    r = requests.post(f"{BASE}{path}", params=params, timeout=20)

    if not r.ok:
        print("TRELLO POST ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def trello_post_body(path, data=None):
    data = data or {}
    data.update({"key": API_KEY, "token": TOKEN})
    r = requests.post(f"{BASE}{path}", data=data, timeout=20)

    if not r.ok:
        print("TRELLO POST BODY ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def microsoft_enabled():
    return all([
        MICROSOFT_CLIENT_ID,
        MICROSOFT_CLIENT_SECRET,
        MICROSOFT_REFRESH_TOKEN,
        TODO_LIST_ID
    ])


def get_microsoft_access_token():
    if not microsoft_enabled():
        raise RuntimeError("Microsoft To Do env variables are not configured")

    r = requests.post(
        f"https://login.microsoftonline.com/{MICROSOFT_AUTHORITY}/oauth2/v2.0/token",
        data={
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "refresh_token": MICROSOFT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
            "scope": "offline_access User.Read Tasks.ReadWrite",
        },
        timeout=20
    )

    if not r.ok:
        print("MICROSOFT TOKEN ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()["access_token"]


def graph_get(path, access_token, params=None):
    r = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params or {},
        timeout=20
    )

    if not r.ok:
        print("GRAPH GET ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def graph_post(path, access_token, payload):
    r = requests.post(
        f"{GRAPH_BASE}{path}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20
    )

    if not r.ok:
        print("GRAPH POST ERROR:", r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def todo_task_exists(access_token, title):
    data = graph_get(
        f"/me/todo/lists/{TODO_LIST_ID}/tasks",
        access_token,
        params={"$top": 100}
    )

    for task in data.get("value", []):
        if task.get("title", "").strip().lower() == title.strip().lower():
            return True

    return False


def create_todo_task(item_name, original_item_name, card_info, matching_cards):
    if not microsoft_enabled():
        print("TODO SKIP: Microsoft To Do is not configured")
        return None

    title = TODO_TASK_TITLE_TEMPLATE.format(
        item=item_name,
        card=card_info["name"],
        original_item=original_item_name
    )

    found_text = ", ".join(matching_cards) if matching_cards else "nenajdene"
    body = (
        "Vytvorene automaticky z Trello checklist polozky.\n\n"
        f"Povodna karta: {card_info['name']}\n"
        f"Odkaz na povodnu kartu: {card_info['shortUrl']}\n\n"
        f"Povodna checklist polozka: {original_item_name}\n\n"
        f"Najdene v kartach:\n{found_text}"
    )

    access_token = get_microsoft_access_token()

    if todo_task_exists(access_token, title):
        print("TODO SKIP existing task:", title)
        return None

    task = graph_post(
        f"/me/todo/lists/{TODO_LIST_ID}/tasks",
        access_token,
        {
            "title": title,
            "body": {
                "content": body,
                "contentType": "text"
            }
        }
    )
    print("TODO TASK CREATED:", task.get("id"), task.get("title"))
    return task


def get_card(card_id):
    return trello_get(f"/cards/{card_id}", {
        "fields": "name,idList,shortUrl,desc"
    })


def create_card(list_id, name, desc=""):
    return trello_post_body("/cards", {
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


def find_cards_with_exact_item(search_term, allowed_list_id, exclude_card_id=None):
    print("SEARCH TERM:", search_term)
    matching_cards = []
    search_norm = normalize_item_name(search_term)

    params = {
        "fields": "name",
        "checklists": "all",
        "checklist_fields": "all",
        "limit": 1000
    }

    try:
        cards = trello_get(f"/lists/{allowed_list_id}/cards", params)
        print(f"CARDS LOADED: {len(cards)}")
    except Exception as e:
        print(f"ERROR loading cards from list: {str(e)}")
        return []

    for card in cards:
        card_id = card["id"]
        card_name = card["name"]

        if exclude_card_id and card_id == exclude_card_id:
            continue

        checklists = card.get("checklists", [])
        found_on_card = False

        for checklist in checklists:
            for item in checklist.get("checkItems", []):
                item_name = item.get("name", "")

                if normalize_item_name(item_name) == search_norm:
                    print(f"MATCH FOUND IN CARD: {card_name}")
                    matching_cards.append(card_name)
                    found_on_card = True
                    break

            if found_on_card:
                break

    print("FINAL MATCHING CARDS:", matching_cards)
    return matching_cards



ROOT = Path(__file__).parent.resolve()
PUBLIC = ROOT / "public"

SCENE_HEADING_RE = re.compile(
    r"^\s*(?:(?:OBRAZ|SC[ÉE]NA|SCENE)\s*)?(\d{1,4})[\).:-]?\s*(.*)$",
    re.IGNORECASE,
)

TV_SCENE_HEADING_RE = re.compile(
    r"^\s*(?P<scene>\d+/\d+)(?P<tag>[A-Z]{0,12})?\.?\s*(?P<title>(?:INT\.?|EXT\.?).*)$",
    re.IGNORECASE,
)


@app.route("/screener", methods=["GET"])
def screener():
    return send_from_directory(PUBLIC, "index.html")


@app.route("/screener-assets/<path:filename>", methods=["GET"])
def screener_assets(filename):
    return send_from_directory(PUBLIC, filename)

@app.route("/api/parse", methods=["POST"])
def parse_script():
    payload = request.get_json(silent=True) or {}
    cards = split_scenes(payload.get("script", ""))
    return jsonify({"cards": cards})


def split_scenes(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    starts = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()
        if not stripped:
            continue
        if (
            upper.startswith("OBRAZ ")
            or upper.startswith("SCÉNA ")
            or upper.startswith("SCENA ")
            or upper.startswith("SCENE ")
        ):
            starts.append(idx)

    tv_starts = [
        (idx, TV_SCENE_HEADING_RE.match(line.strip()))
        for idx, line in enumerate(lines)
        if TV_SCENE_HEADING_RE.match(line.strip())
    ]
    if tv_starts:
        starts = select_script_body_starts(tv_starts)
        return build_tv_scene_cards(lines, starts)

    if not starts:
        starts = [idx for idx, line in enumerate(lines) if SCENE_HEADING_RE.match(line.strip())]

    if not starts:
        body = "\n".join(lines).strip()
        return [scene_card(1, "Celý scenár", body)]

    cards = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        heading = lines[start].strip()
        match = SCENE_HEADING_RE.match(heading)
        number = int(match.group(1)) if match else pos + 1
        title_tail = match.group(2).strip(" -:") if match else heading
        title = title_tail or heading
        block_lines = block.split("\n")
        body = "\n".join(block_lines[1:]).strip() if len(block_lines) > 1 else block
        cards.append(scene_card(number, title, body))

    return cards



def select_script_body_starts(tv_starts):
    first_scene = tv_starts[0][1].group("scene")
    body_start_pos = 0
    for pos, (_, match) in enumerate(tv_starts[1:], start=1):
        if match.group("scene") == first_scene:
            body_start_pos = pos
    return tv_starts[body_start_pos:]


def build_tv_scene_cards(lines, starts):
    cards = []
    for pos, (start, match) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        scene_id = match.group("scene")
        tag = (match.group("tag") or "").strip()
        title = match.group("title").strip()
        scene_key = format_scene_key(scene_id, tag)
        block_lines = block.split("\n")
        body = "\n".join(block_lines[1:]).strip() if len(block_lines) > 1 else block
        cards.append(scene_card_from_id(scene_key, title, body))
    return cards


def format_scene_key(scene_id, tag):
    episode, scene = scene_id.split("/", 1)
    return f"{int(episode):02d}/{int(scene):02d}{tag}"


def build_trello_scene_title(scene_id, title, characters):
    normalized = normalize_scene_heading(title)
    suffix = f" — {', '.join(name.upper() for name in characters)}" if characters else ""
    return f"{scene_id}. {normalized}{suffix}"


def normalize_scene_heading(title):
    title = re.sub(r"\s+", " ", title.strip())
    title = title.replace(" – ", " - ")
    title = re.sub(r"\s+-\s+(DAY|NIGHT|DEŇ|NOC|RÁNO|RANO|VEČER|VECER)\b", r", \1", title, flags=re.IGNORECASE)
    replacements = {
        "DAY": "DEŇ",
        "NIGHT": "NOC",
        "RANO": "RÁNO",
        "VECER": "VEČER",
    }
    for source, target in replacements.items():
        title = re.sub(rf"\b{source}\b", target, title, flags=re.IGNORECASE)
    return title.upper()


def guess_opening_characters(body):
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    collected = []
    for line in lines[:8]:
        if looks_like_character_line(line):
            collected.extend(split_character_line(line))
            continue
        if collected:
            break
    seen = []
    for name in collected:
        if name and name not in seen:
            seen.append(name)
    return seen[:16]


def looks_like_character_line(line):
    if len(line) > 130:
        return False
    if any(token in line.upper() for token in ["INT.", "EXT.", "OBRAZ", "SCÉNA", "SCENA"]):
        return False
    letters = re.sub(r"[^A-Za-zÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽÄÖÜáčďéíľĺňóôŕšťúýžäöü]", "", line)
    return bool(letters) and line == line.upper()


def split_character_line(line):
    cleaned = re.sub(r"\([^)]*\)", "", line)
    names = re.split(r",|\+| A | S ", cleaned)
    ignored = set()
    return [name.strip().title() for name in names if name.strip().upper() not in ignored]


def build_trello_description(characters, body):
    cleaned = body.strip()
    lines = cleaned.split("\n")
    while lines and (not lines[0].strip() or looks_like_character_line(lines[0].strip())):
        lines.pop(0)
    scene_text = "\n".join(lines).strip()
    lead, rest = split_lead_sentence(scene_text)
    parts = [
        f"POSTAVY: {', '.join(name.upper() for name in characters) if characters else 'DOPLNIŤ'}",
        "",
        f"**PREPIS: {lead}**" if lead else "**PREPIS:**",
    ]
    if rest:
        parts.extend(["", format_scene_body(rest)])
    return "\n".join(parts).strip()


def split_lead_sentence(text):
    normalized = text.strip()
    if not normalized:
        return "", ""
    first_line, separator, rest = normalized.partition("\n")
    if separator:
        return first_line.strip(), rest.strip()
    match = re.search(r"(?<=[.!?])\s+", normalized)
    if not match:
        return normalized, ""
    return normalized[: match.start()].strip(), normalized[match.end() :].strip()


def format_scene_body(text):
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line and not re.fullmatch(r"\d{1,3}", line)]
    blocks = []
    buffer = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if looks_like_character_line(line):
            flush_text_block(blocks, buffer)
            speaker = line
            dialogue = []
            i += 1
            while i < len(lines) and not looks_like_character_line(lines[i]):
                if not re.fullmatch(r"\d{1,3}", lines[i]):
                    dialogue.append(lines[i])
                i += 1
            spoken = join_wrapped_lines(dialogue)
            blocks.append(f"**{speaker}:** {spoken}".strip())
            continue

        buffer.append(line)
        i += 1

    flush_text_block(blocks, buffer)
    return "\n\n".join(block for block in blocks if block).strip()


def flush_text_block(blocks, buffer):
    if buffer:
        blocks.append(join_wrapped_lines(buffer))
        buffer.clear()


def join_wrapped_lines(lines):
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()



PROP_RULES = [
    ("Policajné auto", r"\bpolicajne auto\b"),
    ("Policajná páska / opáskované miesto", r"\bopaskoval\w*|\bpask\w*"),
    ("Nosidlá / vak na telo", r"\bnosidl\w*|\bzazipsovan\w*"),
    ("Auto", r"\baut(?:o|a|e|om|u)\b"),
    ("Limuzína / SUV", r"\blimuzin\w*|\bsuv\b"),
    ("Čln", r"\bcln\w*"),
    ("Notebook", r"\bnotebook\w*"),
    ("Mobil", r"\bmobil\w*"),
    ("Fotoalbum", r"\bfotoalbum\w*"),
    ("Fotky", r"\bfotk\w*"),
    ("Šatka", r"\bsatk\w*"),
    ("Batoh", r"\bbatoh\w*"),
    ("Školská taška", r"\bskolsk\w+\s+task\w*"),
    ("Taška s jedlom", r"\btask\w*.{0,40}\bjedl\w*|\bjedl\w*.{0,40}\btask\w*"),
    ("Nákupné tašky", r"\bnakupn\w+\s+task\w*"),
    ("Cestovná taška s monogramom L.S.", r"\bcestovn\w+\s+.*task\w*|\bmonogram\w*"),
    ("Taška", r"\btask\w*"),
    ("Obálka s peniazmi", r"\bobalk\w*|\bpeniaz\w*"),
    ("Blister s liekmi / Ritalin", r"\bblister\w*|\britalin\b|\bliek\w*"),
    ("DJ pult", r"\bdj pult\w*"),
    ("Laptop", r"\blaptop\w*"),
    ("Looper", r"\blooper\w*"),
    ("Klávesy", r"\bklaves\w*"),
    ("Slúchadlá", r"\bsluchadl\w*"),
    ("Automaty na snacky a pitie", r"\bautomat\w*"),
    ("Nástenka", r"\bnastenk\w*"),
    ("JBL reproduktor", r"\bjbl\b"),
    ("Pištoľ / zbraň", r"\bpistol\w*|\bzbran\w*"),
    ("Basketbalová lopta", r"\blopt\w*"),
    ("Uterák", r"\buterak\w*"),
    ("Mikrofón", r"\bmikrofon\w*"),
    ("Gitara", r"\bgitara\b|\bgitare\b|\bgitarou\b|\bna gitare\b"),
    ("Loptička pre psa", r"\bloptick\w*"),
    ("Pivo", r"\bpiv\w*"),
    ("Výzdoba", r"\bvyzdob\w*"),
    ("Jedlo a pitie", r"\bjedlo\b|\bpitie\b"),
    ("Drinky", r"\bdrink\w*"),
    ("Víno", r"\bvin\w*"),
]


def extract_rekvizity(text):
    normalized = normalize_for_lookup(text)
    props = []
    for label, pattern in PROP_RULES:
        if re.search(pattern, normalized, re.IGNORECASE):
            props.append(label)
    return prune_rekvizity(props)


def normalize_for_lookup(text):
    replacements = str.maketrans(
        "áäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ",
        "aacdeillnoorstuyzAACDEILLNOORSTUYZ",
    )
    return text.translate(replacements).lower()


def prune_rekvizity(props):
    if "Školská taška" in props or "Taška s jedlom" in props or "Nákupné tašky" in props or "Cestovná taška s monogramom L.S." in props:
        props = [prop for prop in props if prop != "Taška"]
    if "Loptička pre psa" in props:
        props = [prop for prop in props if prop != "Basketbalová lopta"]
    seen = []
    for prop in props:
        if prop not in seen:
            seen.append(prop)
    return seen


def adjust_rekvizity_for_scene(scene_id, props):
    removals = {
        "01/12FLASH": {"Čln", "Šatka"},
        "01/17": {"Gitara"},
        "01/27FLASH": {"Notebook", "Mikrofón"},
    }
    blocked = removals.get(scene_id, set())
    if blocked:
        props = [prop for prop in props if prop not in blocked]
    return props


SCENE_REKVIZITY_DETAILS = {
    "01/02LP": {
        "Auto": "Auto Jakuba a Sáry - cesta k rieke; nadväzuje na 01/03LP a 01/04LP; aj letecký záber na auto",
    },
    "01/03LP": {
        "Auto": "Auto Jakuba a Sáry - pokračuje lesom k rieke; nadväzuje na 01/02LP a pokračuje v 01/04LP",
    },
    "01/04LP": {
        "Auto": "Auto Jakuba a Sáry - zastaví pri rieke, výstup z auta; nadväzuje na 01/02LP-01/03LP",
        "Čln": "Čln pri rieke - Jakub a Sára sa presúvajú k plavbe; nadväzuje na 01/06LP",
    },
    "01/06LP": {
        "Čln": "Čln na rieke - Jakub vesluje, Sára sedí v člne; nadväzuje na 01/04LP",
    },
    "01/08LP": {
        "Čln": "Policajný čln - policajti z člna koordinujú hľadanie Jakubovho tela",
    },
    "01/09": {
        "Policajné auto": "Policajné auto - blikajúce v pozadí na brehu rieky pri vyšetrovaní Jakuba",
        "Čln": "Policajný čln / riečny zásah - nadväzuje na hľadanie tela v 01/08LP",
        "Auto": None,
    },
    "01/11FLASH": {
        "Šatka": "Sárina šatka - pláva vo vode; súčasť Sárinej verzie nehody, nadväzuje na rozprávanie v 01/12FLASH",
    },
    "01/12FLASH": {
        "Notebook": "Dogyho notebook vo Fefe Beef - Dogy píše román/VO, rámuje flashback so Sárou",
        "Fotoalbum": "Sárin fotoalbum - Sára si v izbe prezerá Jakubove fotky",
        "Fotky": "Jakubove fotky vo fotoalbume - používa Sára pri spomienke na Jakuba",
    },
    "01/13": {
        "Limuzína / SUV": "Čierna limuzína / SUV vyššej triedy - Veronika a Laura prichádzajú pred vilu",
    },
    "01/15": {
        "Auto": "Kikove auto - Kiko a Bety prichádzajú pred dom Bety; Alex sa objaví pred autom",
    },
    "01/16": {
        "Mobil": "Betin mobil - Bety kontroluje displej, Kiko jej ho berie",
    },
    "01/17": {
        "Taška s jedlom": "Zabalená taška s jedlom pre Veroniku - Fefe ju prinesie a položí na pult",
    },
    "01/18": {
        "Batoh": "Alexov batoh do školy - Alex doň hodí posledné veci a zazipsuje ho",
        "Obálka s peniazmi": "Obálka s peniazmi od Lukáša - Lukáš ňou máva, rieši prácu v kancli",
    },
    "01/19": {
        "Batoh": "Betin školský batoh/taška - Bety sa chystá do školy a balí si veci",
        "Taška": "Betina taška do školy - Bety si ju balí pred odchodom",
        "Blister s liekmi / Ritalin": "Blister s Ritalinom - Alica ho podá Bety, Bety si ho berie",
    },
    "01/22": {
        "DJ pult": "DJ pult v hudobnej miestnosti - obsluhuje ho Mery",
        "Laptop": "Laptop pri DJ pulte - súčasť Merynej hudobnej zostavy",
        "Looper": "Looper - súčasť Merynej elektronickej hudobnej zostavy",
        "Klávesy": "Klávesy / malé klávesy - Lea hrá na klávesoch, Mery ich má pri DJ pulte",
        "Slúchadlá": "Slúchadlá Mery - Mery ich má na ušiach pri obsluhe DJ pultu",
    },
    "01/23": {
        "Mobil": "Alexov mobil - Alex ťuká do mobilu pri automate/nástenke",
        "Automaty na snacky a pitie": "Automat na chodbe - Alex si pri ňom vyberá vec alebo sa zastaví pri nástenke",
        "Nástenka": "Školská nástenka - alternatívna akcia Alexa pri chodbe so skrinkami",
    },
    "01/27FLASH": {
        "Auto": "Auto Olasovej - deň pri stavbe a noc na parkovisku; kontinuita s 01/26FLASH a 01/32FLASH",
    },
    "01/30": {
        "Mobil": "Alexov mobil - Alex púšťa Bety a Kikovi svoju pesničku",
        "Školská taška": "Alexova školská taška - Alex ju berie pri odchode",
        "Automaty na snacky a pitie": "Automaty v školskej klubovni - snacky a pitie v pozadí scény",
        "Jedlo a pitie": "Jedlo a pitie v klubovni - decká sedia, kecajú a jedia",
    },
    "01/32FLASH": {
        "Auto": "Auto Olasovej - odstavené pri rieke počas výstrelu; kontinuita 01/26FLASH-01/27FLASH-01/32FLASH",
        "Mobil": "Alexov mobil - Alex púšťa Olasovej demo/pesničku",
        "Pištoľ / zbraň": "Pištoľ / zbraň mimo obrazu - postavy počujú výstrel pri rieke",
    },
    "01/33": {
        "Mobil": "Mobil s hudbou - púšťa sa rovnaká pesnička/demoverzia",
        "JBL reproduktor": "JBL reproduktor - hudba pustená z mobilu cez JBL, Sára chce hudbu vypnúť",
    },
    "01/34": {
        "Basketbalová lopta": "Basketbalová lopta - tréning v telocvični, Alex dribluje a dáva kôš",
        "Uterák": "Alexov uterák - Alex sa utiera po tréningu",
    },
    "01/38": {
        "Nákupné tašky": "Nákupné tašky Laury - Gajdoš ich nesie za Laurou a položí ich",
        "Cestovná taška s monogramom L.S.": "Stratená cestovná príručná taška s monogramom L.S. - priniesol ju taxík, Laura ju otvorí",
    },
    "01/39": {
        "Gitara": "Alexova gitara - Alex na terase hrá/brnká a skladá",
        "Loptička pre psa": "Loptička pre Bona - voliteľná rekvizita pri psovi, ak ju bude Bono nosiť",
        "Pivo": "Lukášovo pivo - Lukáš vyjde na terasu s pivom v ruke",
    },
    "01/40": {
        "Výzdoba": "Výzdoba imatrikulačnej párty v telocvični - školská párty, nadväzuje na 01/42-01/43",
        "Jedlo a pitie": "Jedlo a nealko pitie na imatrikulačnej párty - školská akcia, bez alkoholu",
    },
    "01/44": {
        "Drinky": "Drinky na Sárinej afterke - partia sedí v Sárinej izbe a popíja",
    },
    "01/48": {
        "Víno": "Laurino víno - Laura sedí na gauči v župane a pije víno",
    },
    "01/49": {
        "Notebook": "Dogyho notebook vo Fefe Beef - Dogy sedí a píše svoj román, nadväzuje na 01/52",
    },
    "01/52": {
        "Policajné auto": "Policajné auto - miesto nálezu Jakubovho tela pri rieke; strihák 01/53LP je zatiaľ v karte 01/52",
        "Policajná páska / opáskované miesto": "Policajná páska / opáskované miesto - pri náleze Jakubovho tela",
        "Nosidlá / vak na telo": "Nosidlá / vak na telo - policajti odnášajú Jakubovo telo už zazipsované",
        "Notebook": "Dogyho notebook vo Fefe Beef - Dogy píše o zastrelení Jakuba; nadväzuje na 01/49",
        "Mobil": "Alicin mobil - Alica si robí zábery z miesta činu, Bety na ňu zazerá",
        "Auto": None,
    },
}


def enrich_rekvizity_for_scene(scene_id, props):
    details = SCENE_REKVIZITY_DETAILS.get(scene_id, {})
    enriched = []
    for prop in props:
        if prop in details:
            replacement = details[prop]
            if replacement:
                enriched.append(replacement)
            continue
        enriched.append(prop)
    return enriched

def scene_card_from_id(scene_id, title, body):
    characters = guess_opening_characters(body)
    props = extract_rekvizity(f"{title}\n{body}")
    props = adjust_rekvizity_for_scene(scene_id, props)
    props = enrich_rekvizity_for_scene(scene_id, props)
    card_title = build_trello_scene_title(scene_id, title, characters)
    card = scene_card(0, title, body)
    card["number"] = scene_id
    card["name"] = card_title
    card["description"] = build_trello_description(characters, body)
    card["characters"] = characters
    card["labels"] = []
    card["checklistName"] = "Rekvizity"
    card["checklist"] = props
    card["checklists"] = [
        {"name": "Rekvizity", "items": props},
        {"name": "Poznamky z porady", "items": []},
        {"name": "Info z natacania", "items": []},
    ]
    return card


def scene_card(number, title, body):
    clean_body = body.strip()
    location = guess_location(title, clean_body)
    time_of_day = guess_time(title, clean_body)
    characters = guess_characters(clean_body)
    labels = [
        value
        for value in [
            time_of_day,
            "interiér" if "INT" in title.upper() else None,
            "exteriér" if "EXT" in title.upper() else None,
        ]
        if value
    ]

    return {
        "number": number,
        "name": f"Obraz {number:02d} - {title.strip() or 'Bez názvu'}",
        "description": build_description(location, time_of_day, characters, clean_body),
        "location": location,
        "timeOfDay": time_of_day,
        "characters": characters,
        "labels": labels,
        "checklist": [
            "Overiť postavy v obraze",
            "Doplniť lokáciu",
            "Doplniť rekvizity/kostýmy",
            "Potvrdiť produkčné poznámky",
        ],
    }


def guess_location(title, body):
    first = title or body.split("\n", 1)[0]
    normalized = first.replace("INT.", "").replace("EXT.", "").replace("INT", "").replace("EXT", "")
    normalized = re.split(
        r"\s+-\s+|\s+–\s+|\s+/\s*(?:DEŇ|DEN|NOC|RÁNO|RANO|VEČER|VECER)",
        normalized,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return normalized.strip(" .:-")[:80] or "Neurčená lokácia"


def guess_time(title, body):
    sample = f"{title}\n{body[:500]}".upper()
    for key, value in [
        ("NOC", "noc"),
        ("VEČER", "večer"),
        ("VECER", "večer"),
        ("RÁNO", "ráno"),
        ("RANO", "ráno"),
        ("DEŇ", "deň"),
        ("DEN", "deň"),
    ]:
        if key in sample:
            return value
    return ""


def guess_characters(body):
    names = []
    for line in body.split("\n"):
        stripped = line.strip()
        if (
            2 <= len(stripped) <= 32
            and stripped == stripped.upper()
            and re.search(r"[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ]", stripped)
            and not any(token in stripped for token in ["INT", "EXT", "OBRAZ", "SCENA", "SCÉNA"])
        ):
            names.append(stripped.title())

    seen = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen[:12]


def build_description(location, time_of_day, characters, body):
    parts = [
        f"Lokácia: {location}",
        f"Čas: {time_of_day or 'neurčený'}",
        f"Postavy: {', '.join(characters) if characters else 'doplniť'}",
        "",
        "Scenár / poznámky:",
        body,
    ]
    return "\n".join(parts).strip()


@app.route("/", methods=["GET"])
def home():
    return "Trello webhook server is running", 200


@app.route("/trello-webhook", methods=["HEAD"])
def trello_head():
    return "", 200


@app.route("/api/create-riverdale-workflow-test-v2", methods=["POST"])
def create_riverdale_workflow_test_v2():
    if request.headers.get("X-Test-Key") != "riverdale-workflow-v2-8c31e74a":
        return jsonify({"error": "forbidden"}), 403

    board_id = trello_get("/boards/CzuD55PR", {"fields": "id"})["id"]
    existing_lists = trello_get(f"/boards/{board_id}/lists", {"fields": "name,closed"})
    lists_by_name = {item["name"]: item for item in existing_lists if not item.get("closed")}

    def ensure_list(name):
        if name not in lists_by_name:
            lists_by_name[name] = trello_post_body("/lists", {
                "idBoard": board_id, "name": name, "pos": "bottom"
            })
        return lists_by_name[name]

    inbox = ensure_list("TEST — SPRACOVANÉ OBRAZY")
    sourcing = ensure_list("TEST — TREBA ZOHNAŤ / VYROBIŤ")
    shoot_day = ensure_list("TEST — NATÁČANIE 31. 7. 2026")
    shot = ensure_list("TEST — NATOČENÉ")

    all_test_cards = []
    for target_list in (inbox, sourcing, shoot_day, shot):
        all_test_cards.extend(trello_get(
            f"/lists/{target_list['id']}/cards", {"fields": "name,shortUrl", "limit": 100}
        ))
    if all_test_cards:
        return jsonify({"status": "exists", "cards": [
            {"name": card["name"], "url": card.get("shortUrl")} for card in all_test_cards
        ]})

    board_labels = trello_get(f"/boards/{board_id}/labels", {"fields": "name,color", "limit": 1000})
    labels = {item.get("name", "").casefold(): item for item in board_labels}

    def ensure_label(name, color):
        if name.casefold() not in labels:
            labels[name.casefold()] = trello_post_body("/labels", {
                "idBoard": board_id, "name": name, "color": color
            })
        return labels[name.casefold()]["id"]

    label_test = ensure_label("TEST WORKFLOW", "sky")
    label_source = ensure_label("TREBA ZOHNAŤ", "orange")
    label_ready = ensure_label("PRIPRAVENÉ", "green")
    label_shot = ensure_label("NATOČENÉ", "blue")
    label_continuity = ensure_label("KONTINUITA", "red")

    def add_checklist(card_id, name, items):
        checklist = trello_post_body("/checklists", {"idCard": card_id, "name": name})
        for item in items:
            trello_post_body(f"/checklists/{checklist['id']}/checkItems", {"name": item})

    imported = trello_post_body("/cards", {
        "idList": inbox["id"],
        "name": "[TEST][SPRACOVANÉ] 01/06 — INT. ŠKOLA, CHODBA — DEŇ",
        "desc": (
            "**DIEL:** 1  |  **OBRAZ:** 01/06\n\n"
            "**LOKÁCIA:** Škola — chodba\n"
            "**ČAS:** Deň\n"
            "**POSTAVY:** Bety, Veronika, Sebo\n"
            "**STAV:** čaká na zaradenie do natáčacieho plánu\n\n"
            "### DEJ A AKCIA\n"
            "Bety zastaví Seba na chodbe a ukáže mu vytlačenú fotografiu. Sebo si ju vezme, "
            "prehne ju a vloží do zadného vrecka.\n\n"
            "### REKVIZITY V KONTEXTE\n"
            "- **Vytlačená fotografia Bety a Seba** — Bety ju podá Sebovi; Sebo ju prehne a odloží do vrecka. "
            "Treba pripraviť identické kusy pred prehnutím aj po prehnutí.\n"
            "- **Sebov mobil** — drží ho v pravej ruke pri príchode; rovnaký čierny obal ako v predchádzajúcich obrazoch.\n\n"
            "### KONTINUITA\n"
            "Fotografia prechádza zo stavu NEPREHNUTÁ na PREHNUTÁ. Evidovať variant a miesto uloženia."
        ),
        "idLabels": f"{label_test},{label_continuity}",
        "pos": "bottom",
    })
    add_checklist(imported["id"], "AUTOMATICKÁ KONTROLA", [
        "Dej a postavy vypísané", "Rekvizity vypísané v kontexte", "Nadväznosť označená",
        "Čaká na dátum natáčania",
    ])

    acquisition = trello_post_body("/cards", {
        "idList": sourcing["id"],
        "name": "[TEST][ZOHNAŤ] Fotografia Bety a Seba — 6 identických kusov",
        "desc": (
            "**VZNIKLO AUTOMATICKY Z OBRAZU:** 01/06\n"
            "**SPÔSOB:** vyrobiť / vytlačiť\n"
            "**MNOŽSTVO:** 3× neprehnutá + 3× prehnutá\n"
            "**INTERNÝ DEADLINE:** 29. 7. 2026\n"
            "**PRVÉ NATÁČANIE:** 31. 7. 2026\n\n"
            "Fotografia musí byť rovnakého formátu, orezu a papiera. Jeden čistý kus odložiť ako kontinuitný master."
        ),
        "idLabels": f"{label_test},{label_source},{label_continuity}",
        "due": "2026-07-29T12:00:00.000Z",
        "pos": "bottom",
    })
    add_checklist(acquisition["id"], "ZABEZPEČENIE", [
        "Vybrať a schváliť fotografiu", "Pripraviť tlačové dáta", "Vytlačiť 6 kusov",
        "Pripraviť tri prehnuté varianty", "Označiť kontinuitný master", "Odovzdať na pľac",
    ])

    scheduled = trello_post_body("/cards", {
        "idList": shoot_day["id"],
        "name": "[TEST][PLÁN 04] 01/06 — INT. ŠKOLA, CHODBA — DEŇ",
        "desc": (
            "**NATÁČANIE:** 31. 7. 2026  |  **PORADIE DŇA:** 4\n"
            "**CALL:** 10:40  |  **LOKÁCIA:** Škola — chodba\n\n"
            "Táto karta demonštruje automatické zaradenie spracovaného obrazu podľa natáčacieho plánu.\n\n"
            "### PRÍPRAVA NA DEŇ\n"
            "Fotografia: 1× neprehnutá v ruke Bety, náhradné kusy pri rekvizitárovi. "
            "Sebov mobil: čierny obal, nabitý, bez viditeľných notifikácií."
        ),
        "idLabels": f"{label_test},{label_ready},{label_continuity}",
        "due": "2026-07-31T08:40:00.000Z",
        "pos": "bottom",
    })
    add_checklist(scheduled["id"], "REKVIZITY NA PĽAC", [
        "Fotografia — hero kus neprehnutý", "Fotografia — 5 náhradných variantov",
        "Sebov mobil — čierny obal", "Kontinuitná fotografia pred prvou klapkou",
    ])
    add_checklist(scheduled["id"], "PO OBRAZE", [
        "Označiť použitý variant", "Nahrať fotografiu kontinuity", "Zapísať poškodenie / zmenu",
        "Označiť obraz ako natočený",
    ])

    completed = trello_post_body("/cards", {
        "idList": shot["id"],
        "name": "[TEST][NATOČENÉ] 01/05 — EXT. PRED ŠKOLOU — DEŇ",
        "desc": (
            "**NATOČENÉ:** 30. 7. 2026  |  **POSLEDNÁ KLAPKA:** 16:25\n"
            "**STAV:** natočené — automaticky presunuté po potvrdení rekvizitárom\n\n"
            "### SKUTOČNÝ STAV PO NATÁČANÍ\n"
            "Sebov mobil bez poškodenia, čierny obal zostáva nasadený. Kontinuitná fotografia priložená/doplní sa. "
            "Mobil pokračuje do obrazu 01/06."
        ),
        "idLabels": f"{label_test},{label_shot},{label_continuity}",
        "dueComplete": "true",
        "pos": "bottom",
    })
    add_checklist(completed["id"], "UZAVRETIE OBRAZU", [
        "Rekvizity spočítané", "Stav nadväzných rekvizít zapísaný", "Kontinuita zdokumentovaná",
        "Rekvizity vrátené / presunuté k ďalšiemu obrazu",
    ])

    for source, target, name in (
        (imported, acquisition, "Zabezpečenie — fotografia"),
        (acquisition, imported, "Zdrojový obraz 01/06"),
        (scheduled, acquisition, "Úloha — fotografia"),
        (completed, scheduled, "Nasledujúci obraz 01/06"),
    ):
        trello_post_body(f"/cards/{source['id']}/attachments", {
            "url": target["shortUrl"], "name": name
        })

    cards = (imported, acquisition, scheduled, completed)
    return jsonify({"status": "created", "cards": [
        {"name": card["name"], "url": card["shortUrl"]} for card in cards
    ]})


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

    allowed_list_id = card_info["idList"]

    if allowed_list_id not in BOARD_CONFIG:
        print("IGNORED: wrong list", allowed_list_id, "configured:", list(BOARD_CONFIG.keys()))
        return jsonify({"status": "ignored", "reason": "card not in configured list"}), 200

    config = BOARD_CONFIG[allowed_list_id]
    target_list_id = config["target_list_id"]

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

    try:
        new_card_name = f"{clean_name} - {card_info['name']}"

        matching_cards = find_cards_with_exact_item(
            clean_name,
            allowed_list_id,
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

        exists = card_exists_in_list(target_list_id, new_card_name)

        if exists:
            print("SKIP existing card:", new_card_name)
        else:
            created_card = create_card(target_list_id, new_card_name, new_card_desc)
            print("CARD CREATED:", created_card)

    except Exception as e:
        print("CARD ERROR:", repr(e))
        return jsonify({"status": "error", "reason": f"card failed: {str(e)}"}), 500

    todo_status = "skipped"
    try:
        todo_task = create_todo_task(
            clean_name,
            checkitem_name,
            card_info,
            matching_cards
        )
        if todo_task:
            todo_status = "created"
        elif microsoft_enabled():
            todo_status = "already_exists_or_skipped"
        else:
            todo_status = "not_configured"

    except Exception as e:
        todo_status = "error"
        print("TODO ERROR:", repr(e))

    processed_actions.add(action_id)
    return jsonify({"status": "ok", "mode": "card_and_todo", "todo": todo_status}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)









































