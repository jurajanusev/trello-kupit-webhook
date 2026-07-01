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

## Trello list mapping

Source listy a ich cielove listy na kopirovanie kariet sa daju nastavit cez env:

```env
SOURCE_TARGET_LISTS=source_list_id:target_list_id,source_list_id:target_list_id
```

Ak `SOURCE_TARGET_LISTS` nie je nastavene, pouzije sa povodna konfiguracia v kode.
