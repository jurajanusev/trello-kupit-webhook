# Riverdale Trello workflow

## Čierny Kameň – autoritatívne pravidlá obrazov a registrov

Táto časť nahrádza staršie pravidlá Riverdale pre board `CzuD55PR`. Projekt sa
volá **Čierny Kameň**; názov boardu sa bez osobitného pokynu nemení.

- Zdrojom scenára je desať schválených finálnych PDF pre epizódy 01–10.
  Trvalý autoritatívny payload obsahuje 514 unikátnych obrazov: 314 v epizódach
  01–06 vrátane samostatne obnoveného obrazu 04/40 a 200 v epizódach 07–10
  (51 + 47 + 51 + 51). Staré JSON/extracted-script súbory nie sú produkčný vstup.
- Epizódy 07–10 používajú výhradne PDF
  `SC_01_07_ČK_1.8_MK._KC_FINAL.pdf`, `SC_01_08_ČK_2.2_NJ_SG_FINAL.pdf`,
  `SC_01_09_ČK_1.4_MV_KC_FINALdocx .pdf` a
  `SC_01_10_ČK_1.7_MV_KC_FINALdocx.pdf`. V epizóde 08 existuje
  `08/07FLASH`, nie samostatný `08/07`.
- Popis obrazovej karty zachováva referenčnú štruktúru 01/16: názov obrazu,
  `REKVIZITY V KONTEXTE`, `NADVAZNOSŤ`, `ODKAZY`, `KONTINUITA PRIESTORU`,
  `KONTINUITA POSTÁV`, `RUČNÉ DOPLNENIA`, kompletná `AKCIA A DIALÓGY`
  a metadata na konci.
- Checklisty sú v poradí `REKVIZITY`, `SET`, `INFO Z PORADY`,
  `INFO Z NATÁČANIA`, `OTÁZKY NA PORADU`.
- Používateľ môže do `REKVIZITY` zapísať prirodzený názov. Automatizácia
  zachová jeho text doslova a smie iba pripojiť alebo opraviť strojový suffix
  ` | KARTA: https://trello.com/c/...`.
- **Každá položka v checkliste `REKVIZITY`, vrátane jednorazovej rekvizity,
  musí mať presne jednu master kartu v `REGISTRI REKVIZÍT`.** Staršie pravidlo,
  podľa ktorého sa jednorazové rekvizity do registra nedávali, je zrušené.
- Stabilná identita sa určuje z konkrétneho predmetu, vlastníka/dejovej väzby
  a trvalého rozlíšenia. Všeobecné slovo ako mobil, auto alebo taška nie je
  dôkazom totožnosti. Nejasná položka dostane bezpečne oddelenú kontextovú
  identitu a konkrétnu otázku v `OTÁZKY NA PORADU`.
- `<n>` znamená iba potvrdený rovnaký fyzický kus v kontinuite. Dialógová
  zmienka ani opakovaný názov nestačia.
- Registry-linked položka `REKVIZITY` používa Markdown tvar
  `<n> **Kanonický názov** — *kontext | TU: stav | → obraz* | KARTA: URL`.
  `<n>` a technický suffix zostávajú mimo zvýraznenia; bez kontextu sa použije
  `**Kanonický názov** | KARTA: URL`. Automatizácia smie vložiť iba Markdown
  hviezdičky, nesmie meniť pôvodné znaky, stav ani poradie položky. Hranica
  identity sa overuje podľa skutočnej master karty, nie podľa prvej pomlčky.
  Companion a nejednoznačné ručné položky sa neformátujú naslepo.
- Master karta obsahuje ohraničený automatický blok s kanonickým názvom,
  aliasmi, kategóriami a úplným zoznamom pomenovaných odkazov na obrazy.
  Manuálny obsah mimo bloku sa nikdy neprepisuje.
- Odkazy sú obojsmerné cez checklist URL a Trello attachments; existujúca
  príloha s rovnakým URL sa nepridáva znova.
- Registry karty môžu kombinovať labely `Auto`, `Osobná rekvizita`,
  `Dokument`, `Screen`, `Nadväzná rekvizita`. Hardware a konkrétny obsah
  zobrazený na displeji sú samostatné identity.
- Ak kanonický názov rekvizity jednoznačne určuje vlastníka, jej jediná master
  karta patrí do zoznamu `MENO – OS. REKVIZITY`. Zoznam sa vytvorí pre každého
  takto identifikovaného vlastníka; nerozhoduje frekvencia ani zoznam hlavných
  postáv. Spoločné, odovzdávané a nejednoznačné predmety zostávajú v
  `REGISTRI REKVIZÍT`. Presun zachováva card ID/URL a nikdy nevytvára kópiu.
- Karty v `NADVÄZNÝCH SETOCH` majú label `Nadväzný priestor`. Bežná karta v
  `REGISTRI PRIESTOROV` ani obrazová karta ho nedostane iba kvôli lokácii.
- Pred každou dávkou sa načíta aktuálny stav. Hash jadra položky a snapshot
  popisov, checklistov/stavov, príloh, komentárov a existujúcich labelov chránia
  súbežné ručné úpravy. Pri konflikte sa karta preskočí a nič sa nemaže.
- Každá migrácia ide cez audit, dry-run, malú vzorku, idempotentné dávky a
  read-back audit. Jednorazový endpoint sa po overení vypne.

Schvalene nastavenie pre dalsi vyvoj:

- Zo scenara sa vytvori presne jedna karta na obraz so stabilnym ID `diel/obraz`.
- Pri parovani sa cisla obrazov normalizuju: `08/05`, `8/5` a `08 / 005` znamenaju rovnaky obraz `08/5`; pismena sa zachovavaju, napriklad `09/016A` sa paruje ako `09/16A`.
- Popis obrazovej karty Riverdale pouziva rovnaku textovu strukturu ako DOK 4: volitelne metadata planu, samostatny riadok `EXT./INT. LOKACIA, DEN/NOC`, `POSTAVY`, nadpis deja vo formate `#### **...**`, akcne odseky kurzivou a dialogy ako citacie s tucnym menom postavy aj textom. Za hlavnym textom sa bez zmeny zachovavaju rekvizity v kontexte, kontinuita, odkazy, rucne doplnenia a sekcia `ORIGINALNY SCENAR` s kompletnym textom obrazu vratane dialogov. Rovnaky format sa pouzije pri kazdej novej karte vytvorenej z dalsieho scenara.
- Checklisty obrazu: `REKVIZITY`, `Poznamky z porady`, `Info z natacania`.
- Samostatne ToDo karty sa vytvaraju iba pre rekvizity, ktore treba zohnat, kupit, pozicat, vyrobit, vytlacit, upravit alebo schvalit.
- Jedna rekvizita ma jednu ToDo kartu so vsetkymi suvisiacimi obrazmi; ToDo karta a obrazy maju vzajomne odkazy.
- Synchronizacia po porade aktualizuje obraz aj ToDo kartu bez straty rucnych poznamok.
- Import natacacieho planu podla `diel/obraz` doplni datum, den, unit a poradie a presunie povodnu kartu do zoznamu daneho natacacieho dna.
- Datum natacania sa zaroven nastavi do Trello `due date` funkcionality. Technicky cas terminu je 12:00 v casovej zone Europe/Bratislava, aby sa datum pri zobrazeni neposunul.
- Synchronizacia due date nemeni `dueComplete`; stav dokoncenia sa riadi samostatne podla skutocneho natocenia obrazu.
- Zoznamy jednotlivych natacacich dni a presuny kariet sa vytvaraju pre najblizsich 7 natacacich dni podla planu, nie pre 7 kalendarnych dni.
- Dni volna sa do limitu nepocitaju. Obrazy naplanovane po siedmom najblizsom natacacom dni maju datum a metadata v popise, ale zostavaju vo svojom aktualnom zozname.
- Po potvrdeni natocenia sa tato ista karta presunie do `NATOCENE OBRAZY`; nevytvara sa kopia.
- Ak novy plan obsahuje variant obrazu s pismenom, ale existuje iba zakladna karta bez pismena, system moze pouzit fallback, napriklad `04/43B -> 04/43` alebo `09/16A -> 09/16`; taketo parovanie musi byt viditelne v dry-rune.
- Obraz v `NATOCENE OBRAZY` nie je definitivne zamknuty. Ak sa v novom plane objavi na prekrucanie, povodna karta sa presunie spat do prislusneho natacacieho dna, dostane novy due date a `dueComplete` sa nastavi na `false`.

## Labely a kategoricke zoznamy podla DOK 4

- Label na karte obrazu je zaroven automatizacny spustac a urcuje kategoriu rekvizity.
- Ku kazdemu podporovanemu labelu existuje zoznam s rovnakym nazvom, napriklad `MOBILY`, `AUTA`, `DOKUMENTY / SCREENS`, `OSOBNE REKVIZITY` alebo `NADVÄZNE REKVIZITY`.
- Ked spracovanie obrazu prida label, system v zozname rovnakeho nazvu vytvori kartu konkretnej rekvizity.
- Karta rekvizity obsahuje nazov, kontext pouzitia, suvisiace obrazy, kontinuitu, stav zabezpecenia a neskor termin podla natacacieho planu.
- Karta obrazu a karta rekvizity sa vzajomne prelinkuju cez Trello attachments.
- Pred vytvorenim system hlada existujucu kartu rovnakej rekvizity. Ak existuje, nevytvori duplikat, ale doplni novy obraz, kontext a spatny odkaz.
- Odstranenie alebo zmena labelu nesmie automaticky zmazat kartu rekvizity; oznaci vztah na kontrolu, aby sa nestratili rucne poznamky.
- ToDo stav je vlastnost karty rekvizity. Nie je potrebne vytvarat dalsiu kopiu tej istej rekvizity v samostatnom ToDo zozname.

## Pravidelna aktualizacia natacacich planov

Tento postup sa pouziva pre projekty Dunaj, DOK 4 a Riverdale:

- Kazdy novy plan sa najprv spracuje v rezime dry-run bez zapisov do Trella.
- Pred zapisom sa overi spravna nastenka, pocet riadkov planu, zhodne karty, chybajuce obrazy, duplicity a zoznamy cielovych dni.
- Metadata planu sa zapisu do ohraniceneho bloku v popise a nesmu prepisat povodny dej, rekvizity, kontinuitu, dialogy ani rucne poznamky.
- Karta dostane Trello due date podla datumu natacania; aktualizacia datumu sama neoznaci kartu ako dokoncenu.
- Pri chybajucom variante s koncovym pismenom sa moze pouzit jednoznacna zakladna karta bez pismena, napriklad `23/35F -> 23/35`. Fallback musi byt viditelny v dry-rune.
- Ak neexistuje ani zakladna karta, karta sa nevytvara naslepo. Chybajuci obraz sa oznami a po doplneni karty sa synchronizacia zopakuje.
- Pripravuju sa iba zoznamy pre najblizsich 7 natacacich dni. Dni volna sa do limitu nepocitaju a prazdny zoznam sa pre ne nevytvara.
- Karty sa presunu do datovych zoznamov a zoradia podla poradia dna. Retake sa moze vratit aj zo zoznamu natocenych a vtedy sa `dueComplete` nastavi na `false`.
- Datove zoznamy sa zoradia chronologicky hned za hlavnym zoznamom serialu.
- Zaverecna kontrola musi potvrdit pocet najdenych kariet, nulove duplicity a nulovy pocet zostavajucich presunov; vsetky jednorazove endpointy sa potom vypnu.
- Po kazdej uspesnej aktualizacii planu sa rekvizitove karty povinne synchronizuju do Microsoft To Do podla pravidiel v casti `Microsoft To Do`.

### ToDo rekvizity oznacene `[z]`

- Jedna fyzicka rekvizita ma v zozname `ToDo` presne jednu aktivnu kartu, aj ked sa objavuje vo viacerych obrazoch.
- Nazov zachovava format `nazov rekvizity - karta najskorsieho obrazu`.
- Technicke znacky `[z]`, `[H]`, `[S]`, cisla kontinuity a text `nadv.` nie su sucastou identity rekvizity; zostavaju ako kontext v popise.
- Popis obsahuje klikatelne odkazy na vsetky najdene obrazove karty, povodny text polozky ako akciu/kontext a zoznam kontinuity.
- Due date je datum najskorsieho naplanovaneho obrazu, v ktorom rekvizita hra. Ak obraz este nema datum, karta ostane bez due date do dalsej aktualizacie planu.
- Webhook pri novom `[z]` najprv hlada existujucu kartu podla normalizovaneho nazvu. Ak ju najde, doplni obraz a podla potreby posunie due date na skorsi termin; nevytvori novu kartu.
- Pri cisteni sa archivuju iba overene automaticke duplicity. Rucne karty a rucne poznamky sa zachovavaju.

### Poznamky z porady

- Checklist `POZNÁMKY Z PORADY` sa pripravuje iba na aktivnych obrazovych kartach projektov Dunaj, DOK 4 a Riverdale; karty v zoznamoch natocenych sa vynechavaju.
- Checklist `POZNÁMKY Z PORADY` zostava bez predpripravenych poloziek; poznamky sa zapisuju volnym sposobom ako v povodnom workflowe.
- Aktualizacia po porade nespracovava iba `POZNÁMKY Z PORADY`. Prejde vsetky checklisty obrazovej karty, vratane `REKVIZITY`, `SET`, `POZNÁMKY Z PORADY`, `INFO Z NATÁČANIA`, `LEKÁRSKA PRÍPRAVA` a dalsich projektovych checklistov.
- Kazda polozka sa interpretuje podla nazvu checklistu, textu, stavu zaskrtnutia a konkretnej obrazovej karty. Zmeny sa porovnaju s existujucim stavom, aby sa uz spracovane polozky nevykonali druhykrat.
- Synchronizacia po porade najprv zobrazi dry-run po jednotlivych checklistoch; nejednoznacne volne poznamky oznaci na potvrdenie.
- Zmeny sa zapisu do obrazovej karty, registra kontinuity a podla potreby do Trello ToDo a Microsoft To Do. Checklisty a rucne poznamky sa pri synchronizacii neprepisuju ani nemazu.
- Po zapracovani porady sa najprv aktualizuju zlucene Trello ToDo karty a potom Microsoft To Do.

### Microsoft To Do

- Dunaj, DOK 4 a Riverdale pouzivaju jeden existujuci spolocny Microsoft To Do zoznam. Synchronizacia nesmie vytvarat dalsie Microsoft zoznamy.
- Jedna aktivna Trello karta rekvizity zodpoveda jednej Microsoft ulohe; stabilna identita je odkaz na Trello kartu, nie iba nazov.
- Synchronizuje sa nazov, kontextovy popis, Trello odkaz a due date podla najskorsieho naplanovaneho obrazu.
- Ak Trello karta ani napojeny obraz nema datum, Microsoft termin sa nevymysla.
- Synchronizacia sa spusta na konci aktualizacie planu aj aktualizacie po porade.
- Zaverecny dry-run musi pre prislusny projekt potvrdit `to_create=0`, `to_update=0` a `duplicate_exact_titles=0`.

Nastenky:

- Dunaj: `Dunaj - Rekvizity` - `https://trello.com/b/qCPeWA3e/dunaj-rekvizity`
- DOK 4: `DOK 4` - `https://trello.com/b/lzNy4AtY/dok-4`
- Riverdale: `Riverdale` - `https://trello.com/b/CzuD55PR/riverdale`
