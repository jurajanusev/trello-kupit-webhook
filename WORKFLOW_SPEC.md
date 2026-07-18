# Riverdale Trello workflow

Schvalene nastavenie pre dalsi vyvoj:

- Zo scenara sa vytvori presne jedna karta na obraz so stabilnym ID `diel/obraz`.
- Popis karty obsahuje metadata, dej, rekvizity v kontexte, kontinuitu a hned pod nou sekciu `ORIGINALNY SCENAR` s kompletnym textom obrazu vratane dialogov.
- Checklisty obrazu: `REKVIZITY`, `Poznamky z porady`, `Info z natacania`.
- Samostatne ToDo karty sa vytvaraju iba pre rekvizity, ktore treba zohnat, kupit, pozicat, vyrobit, vytlacit, upravit alebo schvalit.
- Jedna rekvizita ma jednu ToDo kartu so vsetkymi suvisiacimi obrazmi; ToDo karta a obrazy maju vzajomne odkazy.
- Synchronizacia po porade aktualizuje obraz aj ToDo kartu bez straty rucnych poznamok.
- Import natacacieho planu podla `diel/obraz` doplni datum, den, unit a poradie a presunie povodnu kartu do zoznamu daneho natacacieho dna.
- Po potvrdeni natocenia sa tato ista karta presunie do `NATOCENE OBRAZY`; nevytvara sa kopia.
