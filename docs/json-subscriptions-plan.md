# JSON-подписки с балансировкой — план внедрения

> **Статус: отложено.** Код в боте не реализован. Текущий прод: text-подписки через `SUBSCRIPTION_BASE_URL` + `{sub_id}`.

См. также: [report/JSON_SUBSCRIPTIONS_DEEP_DIVE.md](../report/JSON_SUBSCRIPTIONS_DEEP_DIVE.md), [json-subscription-template-setup.md](json-subscription-template-setup.md).

## Цель

Персональные JSON-конфиги Xray вместо text-подписок 3x-ui: файл `{sub_id}.json` на диске, отдача через nginx, ссылка для Happ.

- Каждая подписка в БД = свой JSON-URL
- Шаблон в админке — произвольная топология (балансеры, прямые outbound)
- Бот подставляет `__UUID__`, `__REMARKS__`, …
- При истечении/удалении — файл удаляется

## Конфигурация (после реализации)

| Переменная | Пример |
|------------|--------|
| `JSON_SUBSCRIPTIONS_ENABLED` | `true` |
| `JSON_SUBSCRIPTION_BASE_URL` | `https://sub.example.com/api/v4/JSON/` |
| `JSON_SUBSCRIPTION_STORAGE_DIR` | `/var/lib/vpn-bot/json-subs/` |

Домен JSON может совпадать с доменом text-подписок, отдельный path (`/api/v4/JSON/`).

## Nginx

```nginx
location /api/v4/JSON/ {
    alias /var/lib/vpn-bot/json-subs/;
    default_type application/json;
}
```

## Порядок PR-ов (когда вернёмся к задаче)

1. infra — settings, `json_subscription.py`, `build_sub_link`, `vless_uuid`
2. provision — UUID + генерация при оплате
3. lifecycle — удаление файлов
4. admin-ui — редактор шаблона
5. migration script

## Todos

- [ ] infra
- [ ] provision
- [ ] lifecycle
- [ ] admin-ui
- [ ] migration