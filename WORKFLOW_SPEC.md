# Riverdale Trello workflow

Schvalene nastavenie pre dalsi vyvoj:

- Zo scenara sa vytvori presne jedna karta na obraz so stabilnym ID `diel/obraz`.
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

## Labely a kategoricke zoznamy podla DOK 4

- Label na karte obrazu je zaroven automatizacny spustac a urcuje kategoriu rekvizity.
- Ku kazdemu podporovanemu labelu existuje zoznam s rovnakym nazvom, napriklad `MOBILY`, `AUTA`, `DOKUMENTY / SCREENS`, `OSOBNE REKVIZITY` alebo `NADVÄZNE REKVIZITY`.
- Ked spracovanie obrazu prida label, system v zozname rovnakeho nazvu vytvori kartu konkretnej rekvizity.
- Karta rekvizity obsahuje nazov, kontext pouzitia, suvisiace obrazy, kontinuitu, stav zabezpecenia a neskor termin podla natacacieho planu.
- Karta obrazu a karta rekvizity sa vzajomne prelinkuju cez Trello attachments.
- Pred vytvorenim system hlada existujucu kartu rovnakej rekvizity. Ak existuje, nevytvori duplikat, ale doplni novy obraz, kontext a spatny odkaz.
- Odstranenie alebo zmena labelu nesmie automaticky zmazat kartu rekvizity; oznaci vztah na kontrolu, aby sa nestratili rucne poznamky.
- ToDo stav je vlastnost karty rekvizity. Nie je potrebne vytvarat dalsiu kopiu tej istej rekvizity v samostatnom ToDo zozname.
