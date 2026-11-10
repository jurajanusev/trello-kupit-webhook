# trello-kupit-webhook
Trello webhook na kopirovanie poloziek s [kupit]

## Microsoft To Do

Volitelne env pre kopirovanie rovnakej checklist polozky aj do Microsoft To Do:

```env
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_REFRESH_TOKEN=
MICROSOFT_AUTHORITY=consumers
TODO_LIST_ID=
TODO_TASK_TITLE_TEMPLATE={item} - {card}
```

Ak tieto hodnoty nie su nastavene, povodne Trello kopirovanie funguje dalej a To Do cast sa preskoci.

### Súhrn rekvizít na naplánované natáčanie (hlavný ranný systém)

`POST /api/shooting-props-brief/<project>?mode=dry-run&days=5` číta dátumové
stĺpce, obrazové karty a všetky ich checklisty, nie zoznam Trello ToDo.
Projekty: `dunaj`, `dok4`, `riverdale`; existujúca hlavička `X-Microsoft-Sync-Key`.
Predvolené okno je dnešok a štyri ďalšie dni v Europe/Bratislava. Voliteľné
`as_of=YYYY-MM-DD` umožňuje začať napríklad zajtrajškom pri večernej príprave.

Súhrn obsahuje spoločný zoznam presne zhodných názvov rekvizít s výskytmi
v obrazoch, podrobnosti podľa obrazov, SET, kontinuitu, porady, otázky,
ručné doplnenia a denné prípravné poznámky. Zaškrtnuté rekvizity zostávajú
viditeľné. Prázdne REKVIZITY znamenajú potrebu kontroly scenára. Systém
neodvodzuje nové predmety zo samotných dialógov a nesčítava množstvá naslepo.

`mode=apply&limit=2` vytvorí alebo aktualizuje najviac dva denné súhrny
v samostatnom Microsoft zozname **Natáčanie – rekvizity**. Volanie opakovať,
kým `remaining=0`, a overiť dry-run bez zmien. Stabilná identita je projekt,
dátum a časť; dlhé dni sa rozdelia bez straty textu. Dokončené úlohy sa
neotvárajú, ručné poznámky mimo automatického bloku sa zachovajú. Trello sa
týmto systémom nemení. Staré denné súhrny zostávajú ako história.

### Pôvodná synchronizácia Trello ToDo podľa termínov

Existujúci endpoint `POST /api/sync-<project>-microsoft-todo` podporuje
voliteľný parameter `days=5` pre projekty `dunaj`, `dok4`, `riverdale`.
Vyberá otvorené nedokončené karty zo zoznamu Trello `ToDo`, ktorých termín
je od dneška do dneška + 4 kalendárne dni podľa `Europe/Bratislava`.
Karty bez termínu sa do tohto prehľadu nezaraďujú. Nejde o automatické
odvodzovanie nových úloh zo scenárov; prípravné úlohy musia byť v Trello ToDo.

Najprv použite `?mode=dry-run&days=5` s existujúcou autentifikačnou hlavičkou.
Odpoveď obsahuje dátumové okno, počty a vzorku úloh s odkazmi.
`?mode=apply&days=5&limit=15` vykoná jednu dávku. Opakujte vždy so `start=0`,
pretože po každom zápise sa zoznam zostávajúcich zmien zmenší, a overte
`remaining=0` bez chýb a druhý dry-run bez ďalších zmien.
Dokončené úlohy Microsoft To Do zostávajú dokončené. Úlohy mimo okna sa
nemažú. Bez parametra `days` zostáva pôvodná synchronizácia celého zoznamu.

Pravidelné spúšťanie sa nastavuje samostatne po overení živého testu.

## Trello list mapping

Source listy a ich cielove listy na kopirovanie kariet sa daju nastavit cez env:

```env
SOURCE_TARGET_LISTS=source_list_id:target_list_id,source_list_id:target_list_id
```

Ak `SOURCE_TARGET_LISTS` nie je nastavene, pouzije sa povodna konfiguracia v kode.
