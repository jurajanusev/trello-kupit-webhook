"""Build the reviewed, versioned identity/space map used by the importer."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

SOURCE = Path(__file__).with_name("cierny_kamen_ep11_13_scenes.json")
SPACE_SOURCE = Path(__file__).with_name("cierny_kamen_ep07_10_space_map.json")
TARGET = Path(__file__).with_name("cierny_kamen_ep11_13_identity_space_map.json")


def folded(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().casefold()


# Explicit human-reviewed records. The evidence key must occur in that scene.
SPECS = [
    ("11/02", "Dogyho spisovateľský notebook", "píše do notebooku", "DOGY", ["Osobná rekvizita", "Nadväzná rekvizita"], "dogy-notebook", "Dogy na ňom píše text o dianí v meste", None, "13/45", None),
    ("11/01", "Fotografie starých školských tabiel", "fotky starých tabiel", None, ["Dokument"], None, "visia v hudobnej miestnosti ako história školy", None, None, None),
    ("11/03", "Basketbalové dresy mužstva Onyx", "basketbalových dresoch", None, [], None, "hráči ich majú oblečené pred zápasom", None, None, None),
    ("11/07", "Dve kávy pre Dogyho a Andyho", "dve kávy", "DOGY", [], None, "Dogy ich prináša do Andyho bytu", None, None, None),
    ("11/07", "Vrecko s pečivom od Dogyho", "vrecko s pečivom", "DOGY", [], None, "Dogy ho prináša k raňajkám", None, None, None),
    ("11/07", "Dogyho rozpracovaný román", "kapitol z tvojej knihy", "DOGY", ["Dokument", "Osobná rekvizita"], None, "Andy číta kapitoly Dogyho knihy", None, None, None),
    ("11/08", "Veronikin osobný mobil", "zavibruje mobil", "VERONIKA", ["Osobná rekvizita"], None, "Veronika prijíma a číta správu", None, None, None),
    ("11/09", "Nástenka so schémou podozrivých z Jakubovej vraždy", "nástenku so schémou podozrivých", None, ["Dokument"], None, "Alica na nej ukazuje mená podozrivých", None, None, None),
    ("11/22", "Zásnubný rodinný prsteň Jakuba a Sáry", "drží v ruke prsteň", "SÁRA", ["Osobná rekvizita", "Nadväzná rekvizita"], "zasnubny-prsten-jakuba-a-sary", "Sofia ho nájde v Oskarovom saku", None, "11/38", None),
    ("11/38", "Zásnubný rodinný prsteň Jakuba a Sáry", "vytiahne prsteň", "SÁRA", ["Osobná rekvizita", "Nadväzná rekvizita"], "zasnubny-prsten-jakuba-a-sary", "Sára ho nosí pri sebe a vytiahne ho počas plesu", "11/22", None, None),
    ("11/25", "Kľúč od Andyho bytu", "nájde ukrytý kľúč", "ANDY", ["Osobná rekvizita"], None, "Alex ho nájde v skrinke hydrantu a vloží do zámku", None, None, "Overiť, či sa ten istý kľúč fyzicky ukáže aj v 11/26 alebo 11/31."),
    ("11/39LP", "Policajné vozidlo pri ubytovni – 11/39LP", "policajné majáky", None, ["Auto"], None, "Andy vidí jeho blikajúce majáky cez okno", None, None, "Je to rovnaké vozidlo ako v 11/40LP?"),
    ("11/40LP", "Policajné vozidlo pri ubytovni – 11/40LP", "Policajné majáky blikajú", None, ["Auto"], None, "Keler a dvaja policajti ním prichádzajú k ubytovni", None, None, "Je to rovnaké vozidlo ako v 11/39LP?"),
    ("11/41", "Vražedná zbraň nájdená v Andyho byte", "kufríku je zbraň", None, ["Nadväzná rekvizita"], None, "policajti ju fyzicky nájdu v kufríku", None, None, "Potvrdiť pôvod a totožnosť zbrane pred spojením s inou zbraňou."),
    ("11/33", "Andyho auto – 11/33", "dvere Andyho auta", "ANDY", ["Auto", "Osobná rekvizita"], None, "Dogy sedí s Andym vo vozidle pred školou", None, None, "Neprepájať s iným autom bez potvrdenia konkrétneho kusu."),
    ("13/30", "Veronikin osobný mobil", "Veronika vezme mobil", "VERONIKA", ["Osobná rekvizita"], None, "Veronika na ňom číta Sárinu správu", None, None, None),
    ("13/31", "Dogyho osobný mobil", "Dogy hľadá mobil", "DOGY", ["Osobná rekvizita"], None, "Dogy ním volá 112 pri záchrane Sáry", None, None, None),
    ("13/35", "Betina bunda pri záchrane Sáry", "prikryje svojou bundou", "BETY", ["Osobná rekvizita"], None, "Bety ňou prikryje zachránenú Sáru", None, None, None),
    ("13/40", "Betin podcastový mikrofón", "pred mikrofónom", "BETY", ["Osobná rekvizita", "Nadväzná rekvizita"], "betin-podcast-setup", "Bety doň vysiela živý podcast", None, None, None),
    ("13/40", "Kamera Betinho videopodcastu", "aj s kamerou", "BETY", ["Osobná rekvizita", "Screen", "Nadväzná rekvizita"], "betin-podcast-setup", "kamera sníma Betin živý podcast", None, None, None),
    ("13/40", "Betine poznámky k podcastu", "napraví si pred sebou poznámky", "BETY", ["Dokument", "Osobná rekvizita"], None, "Bety ich používa pri vysielaní", None, None, None),
    ("13/45", "Dogyho spisovateľský notebook", "počúva na počítači", "DOGY", ["Osobná rekvizita", "Nadväzná rekvizita"], "dogy-notebook", "Dogy na ňom počúva Betin podcast u Fefeho", "11/02", None, "Scenár používa slovo počítač; potvrdené zadanie ho mapuje na Dogyho notebook."),
    ("13/47", "Jedálenská sada partie vo Fefe Beef – 13/47", "burgre a limonády", None, [], None, "burgre a limonády štyroch kamarátov na stole", None, None, None),
    ("13/48", "Benzín vo vinárskom sklade – 13/48", "smrad benzínu", None, [], None, "rozliaty spotrebný materiál určený na zapálenie skladu", None, None, None),
    ("13/48", "Sárin zapaľovač", "drží zapaľovač", "SÁRA", ["Osobná rekvizita"], None, "Sára ho škrtne a hodí na zem", None, None, None),
    ("13/48", "Papierové krabice vo vinárskom sklade", "Papierové krabice", None, [], None, "krabice okolo Sáry vzbĺknu", None, None, None),
    ("13/51", "Dogyho kožená bunda s Vlčím symbolom", "koženú bundu s Vlčím symbolom", "DOGY", ["Osobná rekvizita"], None, "Kolečko ju odovzdá Dogymu a Dogy si ju oblečie", None, None, None),
    ("13/53", "Zbraň Čiernej kukly", "vytiahne zbraň", None, ["Nadväzná rekvizita"], "zbran-ciernej-kukly", "páchateľ ňou mieri na Fefeho", None, "13/54", None),
    ("13/54", "Zbraň Čiernej kukly", "zlodej v čiernej kukle", None, ["Nadväzná rekvizita"], "zbran-ciernej-kukly", "páchateľ s ňou uteká z bistra", "13/53", None, "Zbraň nie je v skrátenom texte 13/54 výslovne pomenovaná; kontinuita vyplýva z bezprostredného úteku páchateľa."),
    ("13/53", "Čierna kukla páchateľa", "čiernou kuklou na hlave", None, ["Nadväzná rekvizita"], "cierna-kukla-pachatela", "páchateľ ju má na hlave pri lúpeži", None, "13/54", None),
    ("13/54", "Čierna kukla páchateľa", "zlodej v čiernej kukle", None, ["Nadväzná rekvizita"], "cierna-kukla-pachatela", "páchateľ v nej uteká z bistra", "13/53", None, None),
    ("13/53", "Peniaze z kasy Fefe Beef", "Peniaze z kasy", None, [], None, "lupič ich žiada a berie z kasy", None, None, None),
    ("13/53", "Lukášova peňaženka", "peňaženku", "LUKÁŠ", ["Osobná rekvizita"], None, "Lukáš ju odovzdáva ozbrojenému páchateľovi", None, None, None),
    ("13/53", "Lukášove hodinky", "hodinky", "LUKÁŠ", ["Osobná rekvizita"], None, "páchateľ ich žiada od Lukáša", None, None, None),
    ("13/53", "Slamky a servítky pri bare Fefe Beef", "slamky a servítky", None, [], None, "Alex je pri nich otočený chrbtom k páchateľovi", None, None, None),
    ("13/55LP", "Servítky na Lukášovu ranu", "servítky na postrelený hrudník", None, [], None, "Alex nimi tlačí Lukášovu ranu", None, None, None),
    ("13/55LP", "Plastové vidličky rozhádzané vo Fefe Beef", "plastové vidličky", None, [], None, "sú rozhádzané po prestrelke", None, None, None),
]


def evidence(scene, phrase):
    target = folded(phrase)
    for block in re.split(r"\n\s*\n", scene["action_raw"]):
        if target in folded(block):
            return re.sub(r"\s+", " ", block).strip()
    raise ValueError(f"{scene['scene_id']}: evidence not found: {phrase}")


def build():
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    scenes = {row["scene_id"]: row for row in payload["scenes"]}
    old_spaces = json.loads(SPACE_SOURCE.read_text(encoding="utf-8"))
    space_lookup = {folded(raw): canonical for raw, canonical in old_spaces.items()}
    props = []
    for scene_id, name, phrase, owner, categories, group, state, previous, next_, question in SPECS:
        props.append({"scene_id": scene_id, "stable_name": name,
                      "source_evidence": evidence(scenes[scene_id], phrase),
                      "owner": owner, "categories": categories,
                      "continuity_group": group, "current_state": state,
                      "previous": previous, "next": next_,
                      "ambiguity_question": question})
    spaces = {}
    for scene in payload["scenes"]:
        raw = scene["location"]
        canonical = space_lookup.get(folded(raw), [raw])
        if isinstance(canonical, str):
            canonical = [canonical]
        spaces[scene["scene_id"]] = {"raw_heading": raw, "canonical_spaces": canonical,
                                     "mapping_evidence": "existing ep07-10 map" if folded(raw) in space_lookup else "new exact story-space identity"}
    result = {"version": 1, "project": "Čierny Kameň", "board_ref": "CzuD55PR",
              "source_payload": SOURCE.name, "scene_count": len(scenes),
              "space_mapping_count": len(spaces), "prop_record_count": len(props),
              "spaces_by_scene": spaces, "props": props}
    if set(spaces) != set(scenes):
        raise ValueError("space mapping does not cover every source scene")
    return result


if __name__ == "__main__":
    data = build()
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: data[key] for key in ("scene_count", "space_mapping_count", "prop_record_count")}))
