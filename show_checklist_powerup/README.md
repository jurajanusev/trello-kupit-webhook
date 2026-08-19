# Dunaj Show Checklist Power-Up

Vlastný čítací Trello Power-Up, ktorý zobrazuje stav checklistov na prednej
strane karty a celý prehľad v samostatnom okne.

## Prečo zvládne veľa checklistov

Konektor najprv volá úzky dotaz `t.card("id", "checklists")`. Keď Trello v
tomto výsledku neposkytne položky checklistov, bezpečne skúsi `t.card("all")`.
Ak ani ten položky nevráti, používateľ môže Power‑Upu udeliť oficiálne Trello
povolenie iba na čítanie a položky sa načítajú cez REST API. Používateľský
token ukladá Trello v súkromných plugin dátach a neposiela sa nášmu serveru.
Predná strana má konfigurovateľný limit odznakov a ďalšie checklisty sa
spočítajú do jedného odznaku.

Power-Up nepotrebuje Trello API token ani serverovú databázu. Používateľské
nastavenia ukladá Trello do súkromných plugin dát danej nástenky.

## Lokálne spustenie

Spusť koreňovú Flask aplikáciu a otvor:

```text
http://localhost:8000/powerup/
```

Trello vyžaduje verejnú HTTPS adresu, preto sa do Trella pripája až nasadená
verzia.

## Konfigurácia v Trello Power-Up administrácii

Pre nasadenie na `https://example.onrender.com` nastav:

- názov: `Dunaj Show Checklist`,
- iframe connector URL: `https://example.onrender.com/powerup/`,
- ikona: `https://example.onrender.com/powerup/icon.svg`,
- povolený pôvod: `https://example.onrender.com`,
- capabilities: `card-badges`, `card-buttons`, `show-settings`.

Potom Power-Up povoľ na vybranej nástenke. Nastavenia sa otvárajú cez
`Power-Ups → Dunaj Show Checklist → Settings`.

## Testy

```powershell
node --test show_checklist_powerup/test_core.cjs
python -m unittest test_show_checklist_powerup.py
```
