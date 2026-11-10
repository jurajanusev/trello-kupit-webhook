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

### Ranný prehľad na päť dní

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
