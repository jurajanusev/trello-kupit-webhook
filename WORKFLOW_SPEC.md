# Riverdale Trello workflow

Schvalene nastavenie pre dalsi vyvoj:

- Zo scenara sa vytvori presne jedna karta na obraz so stabilnym ID `diel/obraz`.
- Pri parovani sa cisla obrazov normalizuju: `08/05`, `8/5` a `08 / 005` znamenaju rovnaky obraz `08/5`; pismena sa zachovavaju, napriklad `09/016A` sa paruje ako `09/16A`.
- Popis karty obsahuje metadata, dej, rekvizity v kontexte, kontinuitu a hned pod nou sekciu `ORIGINALNY SCENAR` s kompletnym textom obrazu vratane dialogov.
- Checklisty obrazu: `REKVIZITY`, `Poznamky z porady`, `Info z natacania`.
- Samostatne ToDo karty sa vytvaraju iba pre rekvizity, ktore treba zohnat, kupit, pozicat, vyrobit, vytlacit, upravit alebo schvalit.
- Jedna rekvizita ma jednu ToDo kartu so vsetkymi suvisiacimi obrazmi; ToDo karta a obrazy maju vzajomne odkazy.
- Synchronizacia po porade aktualizuje obraz aj ToDo kartu bez straty rucnych poznamok.
- Import natacacieho planu podla `diel/obraz` doplni datum, den, unit a poradie a presunie povodnu kartu do zoznamu daneho natacacieho dna.
- Datum natacania sa zaroven nastavi do Trello `due date` funkcionality. Technicky cas terminu je 12:00 v casovej zone Europe/Bratislava, aby sa datum pri zobrazeni neposunul.
- Synchronizacia due date nemeni `dueComplete`; stav dokoncenia sa riadi samostatne podla skutocneho natocenia obrazu.
- Zoznamy jednotlivych natacacich dni a presuny kariet sa vytvaraju najviac 7 kalendarnych dni dopredu, aby na nastenke nevznikalo prilis vela buducich zoznamov.
- Obrazy naplanovane dalej ako 7 dni maju datum a metadata v popise, ale zostavaju vo svojom aktualnom zozname.
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
- Pripravuju sa iba zoznamy pre nasledujucich 7 kalendarnych dni. Pre dni bez natacania sa prazdny zoznam nevytvara.
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
- Predpripravene polozky su `[ZMENA]`, `[ZRUŠENÉ]`, `[PRIDANÉ]`, `[POŽIADAVKY]` a `[PODĽA LOKÁCIE]`.
- Pouzivatel pocas porady dopise text za prislusnu znacku. Synchronizacia po porade interpretuje iba tieto strukturovane polozky a pred zapisom ukaze dry-run.
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
