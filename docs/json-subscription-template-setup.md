# Настройка JSON-шаблона подписки (VPN Bot)

> **Статус: отложено** — справочник на будущее, в проде не используется.

Пошаговая инструкция до внедрения автогенерации в боте.

## Что уже есть в репозитории

| Файл | Назначение |
|------|------------|
| [templates/balancer-vless-ws.template.json](../templates/balancer-vless-ws.template.json) | Шаблон под **ваши** инбаунды `1` (NL) и `16` (US) |
| [scripts/dev/dump_inbound_for_json_template.py](../scripts/dev/dump_inbound_for_json_template.py) | Сверка параметров с панели |
| [scripts/dev/render_json_template_preview.py](../scripts/dev/render_json_template_preview.py) | Сборка тестового JSON для Happ |

Шаблон собран по данным панели (июнь 2026):

- Протокол: **VLESS + WebSocket**
- Путь WS: `/httptunnel`
- NL: `cdn.example.com:443` (inbound #1)
- US: `mirror2.example.com:443` (inbound #16)
- Балансер `random` между `srv_nl` и `srv_us`

Если добавите третью ноду — скопируйте блок `srv_*` в `outbounds`, добавьте tag в `routing.balancers[0].selector`.

---

## Шаг 1. Взять UUID тестового клиента

1. Откройте панель 3x-ui → Clients.
2. Выберите любого активного клиента `tg…` (или создайте тестового).
3. Скопируйте поле **ID** (UUID, формат `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).

Это **не** `subId` из подписки — именно UUID клиента VLESS.

---

## Шаг 2. Собрать тестовый JSON

```bash
cd ~/vpn-platega-bot   # или локально
python scripts/dev/render_json_template_preview.py \
  --uuid "ВАШ-UUID-С-ПАНЕЛИ" \
  --remarks "🇳🇱 Тест JSON" \
  --out /tmp/test-sub.json
```

Или вручную: откройте `templates/balancer-vless-ws.template.json`, замените все `__UUID__` на реальный UUID, `__REMARKS__` на любое имя, уберите остальные плейсхолдеры `__…__` (или подставьте тестовые значения).

---

## Шаг 3. Проверить в Happ (без nginx)

1. Отправьте себе файл `test-sub.json` в Telegram.
2. Откройте в Happ: импорт конфигурации / JSON.
3. Должно появиться подключение с именем из `remarks`.
4. Проверьте подключение и IP (несколько раз — балансер может переключать NL/US).

**Не работает?** Запустите сверку с панелью:

```bash
python scripts/dev/dump_inbound_for_json_template.py
```

Сравните `wsSettings.path`, `externalProxy[].dest` и порт с полями в шаблоне.

---

## Шаг 4. Nginx + URL подписки

На VPS (домен `example.com`):

```bash
sudo mkdir -p /var/lib/vpn-bot/json-subs
sudo chown <user_бота>:<group> /var/lib/vpn-bot/json-subs
sudo cp /tmp/test-sub.json /var/lib/vpn-bot/json-subs/test.json
```

В конфиг nginx сайта `example.com`:

```nginx
location /api/v4/JSON/ {
    alias /var/lib/vpn-bot/json-subs/;
    default_type application/json;
    add_header Content-Disposition 'attachment; filename="subscription.json"';
}
```

Проверка:

```bash
curl -sS https://example.com/api/v4/JSON/test.json | head
```

В Happ добавьте URL: `https://example.com/api/v4/JSON/test.json`

После включения crypt3/crypt5 в боте шифруется именно этот URL.

---

## Шаг 5. Кастомизация шаблона

### Несколько балансеров

Добавьте второй объект в `routing.balancers` и правила `balancerTag` — Happ покажет одно подключение (`remarks`), внутри Xray решит по routing.

### Прямое подключение без балансера

Уберите `balancers`, в `rules` укажите `"outboundTag": "srv_nl"` вместо `balancerTag`.

### Смешанная схема

Пример: NL+US через балансер, отдельный outbound `srv_de` с прямым rule для определённых доменов — всё в одном JSON, редактируется в шаблоне.

### Когда менять шаблон

| Изменение на панели | Действие |
|---------------------|----------|
| Новый CDN-домен / path WS | Правка `address`, `serverName`, `wsSettings.path` |
| Новая нода | Новый блок `srv_*` + tag в balancer |
| Смена flow (Reality и т.д.) | Полная пересборка outbound по dump-скрипту |

---

## Шаг 6. После реализации в боте

1. Вставить проверенный шаблон (с плейсхолдерами `__UUID__` и т.д.) в админку.
2. `JSON_SUBSCRIPTIONS_ENABLED=true` в `.env`.
3. Тестовая покупка → файл `{sub_id}.json` появится в `/var/lib/vpn-bot/json-subs/`.
4. «Перегенерировать все» для активных клиентов.

---

## Частые ошибки

| Симптом | Причина |
|---------|---------|
| Happ не подключается | Подставлен `subId` вместо VLESS UUID |
| Только одна нода работает | UUID не создан на второй ноде (проверьте клиента в панели на обеих) |
| TLS error | Неверный `serverName` — должен совпадать с CDN-доменом |
| 404 по URL | Файл не создан или nginx `alias` без завершающего слэша в location |