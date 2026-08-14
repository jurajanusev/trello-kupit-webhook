from __future__ import annotations

import json
import re
from pathlib import Path


SOURCE = Path(__file__).with_name("cierny_kamen_ep07_10_scenes.json")
TARGET = Path(__file__).with_name("cierny_kamen_ep07_10_identity_map.json")


# Explicit, source-reviewed records.  The evidence phrase must occur verbatim in
# the authoritative scene text; this is intentionally not a keyword classifier.
ROWS = [
    ("07/01LP", "Dogyho osobný mobil", "Zazvoní budík (na mobile)", "DOGY", ["Osobná rekvizita"], "dogy-mobile", None),
    ("07/02LP", "Dogyho uterák", "v pyžame s uterákom", "DOGY", ["Osobná rekvizita"], "dogy-towel", None),
    ("07/02LP", "Dogyho zubná kefka", "s uterákom a kefkou", "DOGY", ["Osobná rekvizita"], None, None),
    ("07/03", "Dogyho uterák", "Dogy stojí v uteráku", "DOGY", ["Osobná rekvizita"], "dogy-towel", None),
    ("07/03", "Dogyho hrebeň", "češe si vlasy", "DOGY", ["Osobná rekvizita"], None, None),
    ("07/04", "Dogyho spacák", "Dogyho spacák", "DOGY", ["Osobná rekvizita"], "dogy-spacak", None),
    ("07/04", "Dogyho tašky s oblečením", "viaceré tašky s vecami na oblečenie", "DOGY", ["Osobná rekvizita"], None, None),
    ("07/04", "Dogyho knihy v kumbále", "knihy", "DOGY", ["Osobná rekvizita", "Dokument"], None, None),
    ("07/05", "Krabice s vybavením Veronikinej izby", "Gajdoš položí škatule", "VERONIKA", ["Osobná rekvizita"], None, "Upresniť presný obsah a počet krabíc s vybavením Veronikinej izby."),
    ("07/06", "Kikov osobný mobil", "Kiko počas rozhovoru skroluje v mobile", "KIKO", ["Osobná rekvizita"], "kiko-mobile", None),
    ("07/06", "Lolin osobný mobil", "Lola pri automate vytiahne mobil", "LOLA", ["Osobná rekvizita"], "lola-mobile", None),
    ("07/06", "Lolina správa Sáre o Bety a Dogym", "začne písať smsku (Sáre)", None, ["Screen"], None, None),
    ("07/08", "Betin školský zošit", "poznámky zo zošita", "BETY", ["Osobná rekvizita", "Dokument"], None, None),
    ("07/10", "Kikov osobný mobil", "Bety mu z ruky vytrhne mobil", "KIKO", ["Osobná rekvizita"], "kiko-mobile", None),
    ("07/10", "Sárina Instagram story o Sofii", "Sára práve zverejnila storku so Sofiinou fotkou", None, ["Screen", "Dokument"], None, None),
    ("07/12", "Andyho fľaše od piva", "ďalšie prázdne fľaše", "ANDY", ["Osobná rekvizita"], None, None),
    ("07/12", "Andyho fľaša piva v ubytovni", "Kašeľ zapije pivom", "ANDY", ["Osobná rekvizita"], None, None),
    ("07/13", "Betin osobný mobil", "Bety vytiahne mobil", "BETY", ["Osobná rekvizita"], "bety-mobile", None),
    ("07/19", "Ivanova podcastová kamera", "Ivan pripravuje kameru", "IVAN", ["Osobná rekvizita"], "ivan-podcast-camera", None),
    ("07/19", "Ivanov podcastový mikrofón", "mikrofón", "IVAN", ["Osobná rekvizita"], "ivan-podcast-microphone", None),
    ("07/19", "Ivanov počítač na podcast", "vracia sa k počítaču", "IVAN", ["Osobná rekvizita"], "ivan-podcast-computer", None),
    ("07/19", "Alicino podcastové vyhlásenie o Sofii", "Na obrazovke sa rozbliká REC", None, ["Screen", "Dokument"], None, None),
    ("07/20", "Notebook Révayovcov", "Oskar otvorený laptop", "OSKAR", ["Osobná rekvizita"], "revay-family-laptop", None),
    ("07/20", "Alicino podcastové vyhlásenie o Sofii", "Pozerajú Alicin LIVE podcast", None, ["Screen", "Dokument"], None, None),
    ("07/24", "Lukášov pracovný počítač na stavbe", "Lukáš sedí za počítačom", "LUKÁŠ", ["Osobná rekvizita"], None, None),
    ("07/24", "Lukášov osobný mobil", "Lukášovi uprostred vety začne zvoniť mobil", "LUKÁŠ", ["Osobná rekvizita"], "lukas-mobile", None),
    ("07/25", "Ivanov osobný mobil", "Ivan sa pozerá do mobilu", "IVAN", ["Osobná rekvizita"], "ivan-mobile", None),
    ("07/23", "Betina baterka na povale", "svieti si na nich baterkou", "BETY", ["Osobná rekvizita"], None, None),
    ("07/28", "Mini basketbalová lopta v Lukášovej unimobunke", "prepadne malá basketbalka", None, [], None, None),
    ("07/29", "Burgre, hranolky a nápoje Alexa, Dogyho a Andyho", "rozjedené/dojedené burgre", None, [], None, None),
    ("07/29", "Andyho peňaženka", "Andy začne hľadať peňaženku", "ANDY", ["Osobná rekvizita"], None, None),
    ("07/29", "Dogyho peniaze od mamy", "To sú peniaze od mamy", "DOGY", ["Osobná rekvizita"], None, None),
    ("07/29", "Účet za jedlo vo Fefe Beef", "Vráti sa Fefe s účtom", None, ["Dokument"], None, None),
    ("07/30", "Laurin notebook", "na ktorých má notebook", "LAURA", ["Osobná rekvizita"], "laura-notebook", None),
    ("07/30", "Laurin pohár vína", "v ruke pohár vína", "LAURA", ["Osobná rekvizita"], None, None),
    ("07/30", "Veronikina kabelka", "Z kabelky si vyberie rúž", "VERONIKA", ["Osobná rekvizita"], "veronika-kabelka", None),
    ("07/30", "Veronikin rúž", "vyberie rúž", "VERONIKA", ["Osobná rekvizita"], None, None),
    ("07/30", "Neidentifikovaný mobil použitý ako zrkadlo – 07/30", "pozerá do mobilu", None, [], None, "Potvrdiť, či sa Veronika líči podľa zrkadla alebo podľa mobilu; scenár uvádza alternatívu."),
    ("07/32", "Drinky Kika, Veroniky, Beky a Seba", "každý s drinkom v ruke", None, [], None, None),
    ("07/32", "Kikov osobný mobil", "Kiko chytí mobil", "KIKO", ["Osobná rekvizita"], "kiko-mobile", None),
    ("07/33", "Basketbalová lopta Alexa a Andyho", "Alex a Andy hrajú basketbal", None, [], None, None),
    ("07/36", "Drinky Kika, Veroniky a Seba", "Kiko zdvihne pohár", None, [], None, None),
    ("07/36", "Platobný terminál diskotéky", "aj s terminálom", None, [], None, None),
    ("07/36", "Veronikina hotovosť na zaplatenie", "Veronika vyberie peniaze", "VERONIKA", ["Osobná rekvizita"], None, None),
    ("07/37", "Fľaše v Dogyho chatke", "zvalia zopár fliaš", None, [], None, None),
    ("07/39", "Veronikina kabelka", "Odkladá kabelku", "VERONIKA", ["Osobná rekvizita"], "veronika-kabelka", None),
    ("07/40", "Kelerova vyšetrovacia nástenka", "Pri nástenke", "KELER", ["Osobná rekvizita", "Dokument"], "keler-investigation-board", None),
    ("07/42", "Kelerov vyšetrovací spis Dogyho", "Keler si odkašle a otvorí spis", "KELER", ["Osobná rekvizita", "Dokument"], "keler-dogy-file", None),
    ("07/47", "Laurin osobný mobil", "Laure zazvoní mobil", "LAURA", ["Osobná rekvizita"], "laura-mobile", None),
    ("07/43", "Sárina podložka na jogu", "rozloženú podložku", "SÁRA", ["Osobná rekvizita"], None, None),
    ("07/50", "Dogyho nafukovací matrac u Alexa", "nafukuje Dogymu posteľ", "DOGY", ["Osobná rekvizita"], "dogy-mattress-alex", "Vybrať, či bude použitá nafukovacia posteľ alebo samostatný matrac; scenár uvádza alternatívu."),
    ("07/51", "Andyho fľaša piva v chatke", "Otvára si v fľašu", "ANDY", ["Osobná rekvizita"], None, None),
    ("07/51", "Jakubova basketbalová bunda s číslom 9", "Jakubova basketbalová bunda s číslom 9", "JAKUB", ["Osobná rekvizita", "Nadväzná rekvizita"], "jakub-jersey-9", None),
    ("08/01LP", "Spoločenské hry Debnárovcov", "hranie spoločenských hier", None, [], None, "Upresniť konkrétne spoločenské hry a počet kusov pre rodinný klip."),
    ("08/02LP", "Dogyho spisovateľský notebook", "ťuká do notebooku", "DOGY", ["Osobná rekvizita"], "dogy-writer-notebook", None),
    ("08/06FLASH", "Rodinný starožitný prsteň Révayovcov", "rodinný starožitný prsteň", None, ["Osobná rekvizita", "Nadväzná rekvizita"], "revay-engagement-ring", None),
    ("08/07FLASH", "Limonády Jakuba a Sofie vo Fefe Beef", "pijú limonádu", None, [], None, None),
    ("08/09", "Alexova herná konzola", "nejakú bojovú hru na playku", "ALEX", ["Osobná rekvizita"], "alex-game-console", None),
    ("08/11", "Stavebné dokumenty Laury a Lukáša", "s papiermi v rukách", None, ["Dokument"], None, "Upresniť druh a obsah papierov, ktoré Laura a Lukáš preberajú s Viliamom."),
    ("08/13", "Lukášov osobný mobil", "po telefóne sa snaží zohnať nových robotníkov", "LUKÁŠ", ["Osobná rekvizita"], "lukas-mobile", None),
    ("08/16", "Lukášov pracovný pickup", "Lukáš ho zablokuje na svojom pickupe", "LUKÁŠ", ["Auto", "Osobná rekvizita"], "lukas-pickup", None),
    ("08/16", "Oskarovo auto", "Oskarom, ktorý nasadne do auta", "OSKAR", ["Auto", "Osobná rekvizita"], "oskar-car", None),
    ("08/17", "Stavebný bager na projekte Černice", "nejakým stavebným bagrom", None, ["Auto"], None, None),
    ("08/17", "Nákladné auto Adamovič s.r.o.", "obrandovaný nákladiak firmy Adamovič", "LUKÁŠ", ["Auto", "Osobná rekvizita"], None, None),
    ("08/18", "Rozpité kávy Alice a Laury", "pri rozpitých kávach", None, [], None, None),
    ("08/19", "Fľaše vody Alexa a Dogyho", "Pijú vodu z fľašiek", None, [], None, None),
    ("08/20", "Pracovné vesty a helmy dobrovoľníkov", "Vyzliekajú vesty, skladajú helmy", None, [], None, None),
    ("08/21", "Patrikov osobný mobil", "nechal som tam mobil", "PATRIK", ["Osobná rekvizita"], "patrik-mobile", None),
    ("08/21", "Lukášov pracovný pickup", "kde je Lukášovo auto", "LUKÁŠ", ["Auto", "Osobná rekvizita"], "lukas-pickup", None),
    ("08/21", "Terénne auto útočníkov", "majú tam aj terénne auto", None, ["Auto", "Nadväzná rekvizita"], "attackers-offroad", None),
    ("08/20", "Kola a nealkoholické pivo dobrovoľníkov", "popíjajú kolu a nealko pivo", None, [], None, None),
    ("08/22", "Terénne auto útočníkov", "Auto je ihneď preč", None, ["Auto", "Nadväzná rekvizita"], "attackers-offroad", None),
    ("08/23", "Policajné auto pri napadnutom stavenisku", "prichádza policajné auto", None, ["Auto"], None, None),
    ("08/23", "Zakrvavená gáza na Patrikovo čelo", "trocha zakrvavenej gázy", "PATRIK", ["Osobná rekvizita"], None, None),
    ("08/26", "Dogyho osobný mobil", "Dogy pozrie na mobil", "DOGY", ["Osobná rekvizita"], "dogy-mobile", None),
    ("08/27", "Motorky členov Vlkov pred krčmou", "Vonku sú zaparkované motorky", None, ["Auto"], None, "Upresniť počet, typy a vlastníkov motoriek zaparkovaných pred krčmou U Vlka."),
    ("08/28", "Biliardový stôl v krčme U Vlka", "hrajú biliard", None, [], None, None),
    ("08/28", "Biliardové tága a gule v krčme U Vlka", "hrajú biliard", None, [], None, None),
    ("08/29", "Lukášovo neidentifikované auto – 08/29", "zastaví auto, z ktorého vystupuje Lukáš", "LUKÁŠ", ["Auto", "Osobná rekvizita"], None, "Potvrdiť, či Lukáš v 08/29 prichádza na tom istom pracovnom pickupe ako v 08/16 a 08/21."),
    ("08/31", "Lukášovo neidentifikované auto – 08/31", "Alex trucovito sedí v Lukášovom aute", "LUKÁŠ", ["Auto", "Osobná rekvizita"], None, "Potvrdiť, či Lukášovo auto v 08/31 je ten istý pracovný pickup ako v 08/16 a 08/21."),
    ("08/30", "Darčeky hostí pre Sofiino bábätko", "pekne zabalený darček", None, [], None, None),
    ("08/30", "Misa s koláčmi na Sofiinu baby shower", "Dogy nesie misu s koláčmi", None, [], None, None),
    ("08/30", "Kvetová výzdoba Sofiinej baby shower", "upravuje kvetovú výzdobu", None, [], None, None),
    ("08/30", "Sárin obrovský detský kočík pre Sofiu", "Sára, tlačí obrovský kočík", "SÁRA", ["Osobná rekvizita"], None, None),
    ("08/30", "Vozíček babky Magdy", "na vozíku tlačí babku Magdu", "MAGDA", ["Osobná rekvizita"], "magda-wheelchair", None),
    ("08/32", "Vozíček babky Magdy", "Magda) je na vozíčku", "MAGDA", ["Osobná rekvizita"], "magda-wheelchair", None),
    ("08/32", "Alicina darčeková taštička pre Sofiu", "svojou darčekovou taštičkou", "ALICA", ["Osobná rekvizita"], None, None),
    ("08/32", "Medvedia lampička pre Sofiino bábätko", "medvedie svetielko do zástrčky", None, ["Nadväzná rekvizita"], "bear-nightlight", None),
    ("08/34", "Drevený maľovaný koník pre Sofiino bábätko", "krásneho dreveného maľovaného koníka", None, [], None, None),
    ("08/35", "Darčeky pre Sofiino bábätko", "veci, ktoré podostávala pre bábätko", None, [], None, None),
    ("08/35", "Poháre po Sofiinej baby shower", "odpratávajú poháre", None, [], None, None),
    ("08/36", "Lukášova fľaša piva", "pije z fľašky pivo", "LUKÁŠ", ["Osobná rekvizita"], None, None),
    ("08/38", "Andyho plechovka sódy", "plechovka so sódou", "ANDY", ["Osobná rekvizita"], None, None),
    ("08/40", "Ivanov televízny ovládač", "Alica hodí ovládač", "IVAN", ["Osobná rekvizita"], None, None),
    ("08/41", "Alexova gitara", "Alex si doma brnká na gitare", "ALEX", ["Osobná rekvizita", "Nadväzná rekvizita"], "alex-guitar", None),
    ("08/42", "Jakubova basketbalová bunda s číslom 9", "Andy roluje Jakubovu bundu", "JAKUB", ["Osobná rekvizita", "Nadväzná rekvizita"], "jakub-jersey-9", None),
    ("08/42", "Taška na ukrytie Jakubovej bundy", "balí ju do tašky", None, [], None, None),
    ("08/42", "Andyho kola", "otvorí si kolu", "ANDY", ["Osobná rekvizita"], None, None),
    ("08/46", "Rodinná fotografia Debnárovcov so Sofiou", "rodinnú fotku, na ktorej je aj Sofia", None, ["Dokument"], None, None),
    ("08/45", "Taxík privážajúci Sofiu k Révayovcom", "zastavuje taxík", None, ["Auto"], None, None),
    ("08/45", "Sofiin kufrík k Révayovcom", "berie si kufrík", "SOFIA", ["Osobná rekvizita"], None, None),
    ("09/02LP", "Fľaša nového ročníka sektu Révayovcov", "Oskar otvorí fľašu sektu", "OSKAR", ["Osobná rekvizita"], "revay-new-vintage-bottle", None),
    ("09/02LP", "Poháre na ochutnávku sektu Révayovcov", "nalieva do pohárikov na stopkách", None, [], None, None),
    ("09/05LP", "Nedopitá fľaša Onyx sektu", "nedopitú fľašu Onyx sektu", None, ["Nadväzná rekvizita"], "onyx-open-bottle", None),
    ("09/08", "Betin osobný mobil", "Bety sa nešťastne pozerá do mobilu", "BETY", ["Osobná rekvizita"], "bety-mobile", None),
    ("09/08", "Betine správy Sofii", "stĺpik správ, čo sestre naposielala", None, ["Screen", "Dokument"], None, None),
    ("09/17", "Fľaša sektu na prezentácii Révayovcov", "Oskar vezme do rúk jednu fľašu sektu", "OSKAR", ["Osobná rekvizita"], None, None),
    ("09/18", "Mačeta na sabráž sektu", "zaťatím mačety", None, [], None, None),
    ("09/17", "Poháre na prezentáciu sektu Révayovcov", "nalieva všetkým ochutnávku", None, [], None, None),
    ("09/20", "Poháre sektu hostí Révayovcov", "s pohárikmi sektu v rukách", None, [], None, None),
    ("09/24", "Alexov osobný mobil", "z vrecka vytiahne telefón", "ALEX", ["Osobná rekvizita"], "alex-mobile", None),
    ("09/24", "Alexova správa Bety z prezentácie sektu", "Píše správu Bety", None, ["Screen"], None, None),
    ("09/24", "Poháre vína Oskara a Alexa", "Príde s dvomi pohármi vína", None, [], None, None),
    ("09/25", "Alicin jablkový koláč", "krája jej jablkový koláč", "ALICA", ["Osobná rekvizita"], None, None),
    ("09/25", "Alicin veľký nôž na koláč", "Alica veľkým nožom", "ALICA", ["Osobná rekvizita"], None, None),
    ("09/26", "Neidentifikovaný mobil na storku – 09/26", "pozerajú nejakú storku", None, [], None, "Potvrdiť, na čí mobil Sára, Lola a Popy pozerajú storku."),
    ("09/28LP", "Oblečenie a doplnky na nákupnej storke Veroniky a Evy", "skúšajú si topánky, čelenky, klobúky", None, [], None, None),
    ("09/28LP", "Nákupné tašky Veroniky a Evy", "s plnými nákupnými taškami", None, [], None, None),
    ("09/28LP", "Nákupná Instagram story Veroniky a Evy", "instagramovej storky", None, ["Screen", "Dokument"], None, None),
    ("09/29", "Oblek pre Alexa od Sáry", "priehľadnom obale oblek pre Alexa", "ALEX", ["Osobná rekvizita"], "alex-suit-from-sara", "Upresniť vzhľad a veľkosť obleku, ktorý Sára priniesla Alexovi."),
    ("09/30", "Alicin pracovný notebook", "Otvorí notebook", "ALICA", ["Osobná rekvizita"], "alica-notebook", None),
    ("09/30", "Alicin podcastový mikrofón", "mikrofón, kameru, osvetlenie", "ALICA", ["Osobná rekvizita"], "alica-podcast-microphone", None),
    ("09/30", "Alicina podcastová kamera", "mikrofón, kameru, osvetlenie", "ALICA", ["Osobná rekvizita"], "alica-podcast-camera", None),
    ("09/30", "Alicino podcastové osvetlenie", "mikrofón, kameru, osvetlenie", "ALICA", ["Osobná rekvizita"], "alica-podcast-light", None),
    ("09/31", "Alicin podcastový mikrofón", "mikrofón s držiakom", "ALICA", ["Osobná rekvizita"], "alica-podcast-microphone", None),
    ("09/32", "Alicin pohár vína po vyhadzove", "Alica plače a pije víno", "ALICA", ["Osobná rekvizita"], None, None),
    ("09/34", "Lein osobný mobil", "Lea sedí v klubovni a scrolluje na mobile", "LEA", ["Osobná rekvizita"], "lea-mobile", None),
    ("09/34", "Leine slúchadlá", "Lea si zloží slúchadlá", "LEA", ["Osobná rekvizita"], "lea-headphones", None),
    ("09/35", "Alexova gitara", "Alex práve docvičil na gitare", "ALEX", ["Osobná rekvizita", "Nadväzná rekvizita"], "alex-guitar", None),
    ("09/35", "Puzdro na Alexovu gitaru", "odkladá ju do puzdra", "ALEX", ["Osobná rekvizita"], "alex-guitar-case", None),
    ("09/37LP", "Veronikina pôvodná retiazka s príveskom V", "retiazku so zlatým príveskom v tvare „V“", "VERONIKA", ["Osobná rekvizita"], "veronika-original-v-necklace", None),
    ("09/44", "Alicina fľaša vína", "s fľašou vína", "ALICA", ["Osobná rekvizita"], None, None),
    ("09/44", "Alicin pohár vína", "naliatym pohárikom", "ALICA", ["Osobná rekvizita"], None, None),
    ("09/46", "Leine slúchadlá", "Lea si rovno vyberie slúchadla", "LEA", ["Osobná rekvizita"], "lea-headphones", None),
    ("09/47", "Lukášov pracovný počítač vo firme", "pustí do práce na počítači", "LUKÁŠ", ["Osobná rekvizita"], None, None),
    ("09/45", "Oblek pre Alexa od Sáry", "Alex v obleku", "ALEX", ["Osobná rekvizita", "Nadväzná rekvizita"], "alex-suit-from-sara", None),
    ("09/50", "Luxusné auto Eleny a Štefana Révayovcov", "nastupujú do luxusného auta", None, ["Auto"], None, None),
    ("09/51", "Rodinná fotografia Révayovcov s Alexom a Sofiou", "pozerá si fotku z prezentácie", "SÁRA", ["Osobná rekvizita", "Dokument"], None, "Potvrdiť, či Sára pozerá fyzickú vytlačenú fotografiu alebo digitálnu fotku na displeji."),
    ("10/06", "Alexova herná konzola", "Dogy hrá playko", "ALEX", ["Osobná rekvizita"], "alex-game-console", None),
    ("10/01LP", "Dogyho spisovateľský notebook", "Dogy sedí vo Fefeho bistre a píše román", "DOGY", ["Osobná rekvizita"], "dogy-writer-notebook", None),
    ("10/02LP", "Školské zošity Alexa, Bety a Veroniky", "robia si poznámky", None, ["Dokument"], None, "Upresniť, či má mať každý študent samostatný zošit a aký predmet sa vyučuje."),
    ("10/03LP", "Alkoholické nápoje na párty u Alexa", "očividne majú vypité", None, [], None, None),
    ("10/07", "Lukášova cestovná taška", "má cestovnú tašku", "LUKÁŠ", ["Osobná rekvizita"], None, None),
    ("10/11", "Andyho osobný mobil", "zodvihne mobil, volá mu Bety", "ANDY", ["Osobná rekvizita"], "andy-mobile", None),
    ("10/11", "Andyho káva", "pije kávu", "ANDY", ["Osobná rekvizita"], None, None),
    ("10/13", "Betina čierna parochňa", "Bety v parochni", "BETY", ["Osobná rekvizita", "Nadväzná rekvizita"], "bety-black-wig", None),
    ("10/17", "Pizza Alexa a Dogyho", "vyťahuje z rúry pizzu", None, [], None, None),
    ("10/17", "Nôž alebo krájač na pizzu", "Vezme nôž/krájač", None, [], None, "Vybrať, či sa použije nôž alebo krájač na pizzu; scenár uvádza alternatívu."),
    ("10/17", "Plechovky limonády Alexa a Dogyho", "plechovky s limonádou", None, [], None, None),
    ("10/18", "Liborove spisy a dokumenty pre právnika", "Liborových spisoch", "LAURA", ["Osobná rekvizita", "Dokument"], "libor-legal-files", None),
    ("10/18", "Liborov notebook zaistený Laurou", "notebooku, ktorý nezhabali", "LAURA", ["Osobná rekvizita"], None, None),
    ("10/16", "Betin nákupný zoznam na Dogyho oslavu", "zoznam vecí, ktoré treba kúpiť", "BETY", ["Osobná rekvizita", "Dokument"], None, None),
    ("10/20", "Alexov osobný mobil", "Zazvoní mu mobil", "ALEX", ["Osobná rekvizita"], "alex-mobile", None),
    ("10/21", "Lukášov osobný mobil", "volá z auta Alexovi", "LUKÁŠ", ["Osobná rekvizita"], "lukas-mobile", None),
    ("10/20", "Fľaša alkoholu z párty", "vyberie si odtiaľ fľašu", None, [], None, None),
    ("10/23", "Liborov list Veronike", "Právnik vytiahne list od Libora", "VERONIKA", ["Osobná rekvizita", "Dokument"], "libor-letter-veronika", None),
    ("10/22", "Matejova literatúra o prežití v džungli", "číta nejakú literatúru o prežití v džungli", "MATEJ", ["Osobná rekvizita", "Dokument"], None, "Upresniť konkrétny titul knihy alebo časopisu o prežití v džungli."),
    ("10/22", "Fifov burger a limonáda vo Fefe Beef", "dáva burger a limču", "FIFO", ["Osobná rekvizita"], None, None),
    ("10/25", "Kikov osobný mobil", "Kikovi príde správa od Bety", "KIKO", ["Osobná rekvizita"], "kiko-mobile", None),
    ("10/25", "Betina správa Kikovi o príchode na oslavu", "Kikovi príde správa od Bety", None, ["Screen"], None, None),
    ("10/26", "Fľaša alkoholu na Dogyho oslave", "Veronika nalieva z fľaše alkohol", None, [], None, None),
    ("10/26", "Dogyho narodeninová torta", "Bety s tortou a sviečkami", "DOGY", ["Osobná rekvizita"], None, None),
    ("10/26", "Sviečky na Dogyho narodeninovej torte", "tortou a sviečkami", "DOGY", ["Osobná rekvizita"], None, None),
    ("10/27", "Drink Alexa a Veroniky", "Alex ponúkne drink", None, [], None, None),
    ("10/28", "Sud piva prinesený Patrikom", "Patrik aj so sudom piva", "PATRIK", ["Osobná rekvizita"], None, None),
    ("10/30", "Andyho zabalená kniha pre Dogyho", "darček (zabalenú knihu)", "DOGY", ["Osobná rekvizita", "Dokument"], None, None),
    ("10/32", "Kikov pohár na Dogyho oslave", "Kiko s pohárom v ruke", "KIKO", ["Osobná rekvizita"], None, None),
    ("10/33", "Betin sáčok na odpadky", "Bety má v ruke sáčok na smeti", "BETY", ["Osobná rekvizita"], None, None),
    ("10/33", "Umelé poháre z Dogyho oslavy", "umelé poháre po pití", None, [], None, None),
    ("10/33", "Betina čierna parochňa", "BETY V PAROCHNI", "BETY", ["Osobná rekvizita", "Nadväzná rekvizita"], "bety-black-wig", None),
    ("10/37", "Alexov osobný mobil", "berie do ruky mobil", "ALEX", ["Osobná rekvizita"], "alex-mobile", None),
    ("10/40", "Andyho čierna kožená bunda", "dala dolu koženú bundu", "ANDY", ["Osobná rekvizita"], None, "Potvrdiť, či replika označuje fyzicky prítomnú Andyho bundu v obraze alebo iba obrazné pomenovanie minulosti."),
    ("10/41", "Mastné jedlo študentov po párty", "dojedajú mastné jedlo", None, [], None, None),
    ("10/43", "Dogyho nafukovací matrac u Alexa", "Dogyho matraci", "DOGY", ["Osobná rekvizita", "Nadväzná rekvizita"], "dogy-mattress-alex", None),
    ("10/45", "Gajdošova kosačka alebo smetiaky", "kosí, dáva pred dom smetiaky", None, [], None, "Vybrať konkrétnu činnosť a rekvizitu Gajdoša na predzáhradke; scenár uvádza alternatívu kosačka/smetiaky."),
    ("10/46", "Laurina káva", "Laura sedí za stolom a pije kávu", "LAURA", ["Osobná rekvizita"], None, None),
    ("10/47", "Alexov osobný mobil", "Alexovi zazvoní mobil", "ALEX", ["Osobná rekvizita"], "alex-mobile", None),
    ("10/49", "Veronikina matcha pre Bety", "Matcha a šišky", "BETY", ["Osobná rekvizita"], None, None),
    ("10/49", "Šišky od Veroniky pre Bety", "Matcha a šišky", "BETY", ["Osobná rekvizita"], None, None),
    ("10/48", "Betina káva od Alice", "Podá Bety kávu", "BETY", ["Osobná rekvizita"], None, None),
    ("10/50", "Liborova náhradná retiazka s príveskom V pre Veroniku", "krabičku s retiazkou a príveskom", "VERONIKA", ["Osobná rekvizita"], None, None),
    ("10/50", "Krabička na náhradnú retiazku pre Veroniku", "krabičku s retiazkou", "VERONIKA", ["Osobná rekvizita"], None, None),
    ("10/50", "Liborov odkaz Veronike k retiazke", "V balíčku je odkaz", "VERONIKA", ["Osobná rekvizita", "Dokument"], None, None),
]


def sentence_for(text, phrase):
    position = text.casefold().find(phrase.casefold())
    if position < 0:
        raise ValueError(f"evidence not found: {phrase!r}")
    left = max(text.rfind("\n", 0, position), text.rfind(".", 0, position)) + 1
    right_candidates = [value for value in (text.find("\n", position), text.find(".", position)) if value >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def main():
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    scenes = {scene["scene_id"]: scene for scene in payload["scenes"]}
    records = []
    for scene_id, stable_name, phrase, owner, categories, group, question in ROWS:
        scene = scenes[scene_id]
        evidence = sentence_for(scene["action_raw"], phrase)
        records.append({
            "scene_id": scene_id, "stable_name": stable_name,
            "source_evidence": evidence, "evidence_phrase": phrase,
            "physical_presence": not bool(
                (question and "iba obrazné" in question)
                or stable_name.startswith("Neidentifikovaný mobil použitý ako zrkadlo")
            ),
            "owner": owner, "categories": categories,
            "continuity_group": group,
            "action": evidence, "current_state": evidence,
            "previous": None, "next": None,
            "ambiguity_question": question,
        })
    groups = {}
    for record in records:
        if record["continuity_group"] and record["physical_presence"]:
            groups.setdefault(record["continuity_group"], []).append(record)
    order = {scene["scene_id"]: scene["order"] for scene in payload["scenes"]}
    for members in groups.values():
        members.sort(key=lambda record: order[record["scene_id"]])
        for index, record in enumerate(members):
            record["previous"] = members[index - 1]["scene_id"] if index else None
            record["next"] = members[index + 1]["scene_id"] if index + 1 < len(members) else None
            if len(members) > 1 and "Nadväzná rekvizita" not in record["categories"]:
                record["categories"].append("Nadväzná rekvizita")
    output = {
        "source": SOURCE.name, "record_count": len(records),
        "scene_count_with_props": len({record["scene_id"] for record in records}),
        "records": records,
        "questions": [
            {"scene_id": record["scene_id"], "question": record["ambiguity_question"]}
            for record in records if record["ambiguity_question"]
        ],
    }
    TARGET.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "records"}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
