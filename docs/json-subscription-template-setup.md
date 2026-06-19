# Настройка JSON-шаблона подписки

> **Статус: отложено** — справочник на будущее, в проде не используется.

## Файлы в репозитории

| Файл | Назначение |
|------|------------|
| [templates/balancer-vless-ws.template.json](../templates/balancer-vless-ws.template.json) | Обезличенный пример (2 ноды, WS) |
| [scripts/dev/dump_inbound_for_json_template.py](../scripts/dev/dump_inbound_for_json_template.py) | Параметры инбаундов с панели |
| [scripts/dev/render_json_template_preview.py](../scripts/dev/render_json_template_preview.py) | Сборка тестового JSON |

## Шаг 1. Параметры нод с панели

```bash
python scripts/dev/dump_inbound_for_json_template.py
```

Сверьте `externalProxy[].dest`, `wsSettings.path`, порт — подставьте в шаблон вместо `__NODE1_HOST__`, `__NODE1_WS_PATH__` и т.д.

## Шаг 2. UUID тестового клиента

В панели 3x-ui → Clients → клиент `tg…` → скопируйте **ID (UUID)**. Это не `subId`.

## Шаг 3. Тестовый JSON

Сначала замените в копии шаблона `__NODE*__` на реальные хосты и path, затем:

```bash
python scripts/dev/render_json_template_preview.py \
  --uuid "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  --remarks "Test VPN" \
  --template templates/balancer-vless-ws.template.json \
  --out test-sub.json
```

Импортируйте `test-sub.json` в Happ и проверьте подключение.

## Шаг 4. Nginx (когда будете включать)

```bash
sudo mkdir -p /var/lib/vpn-bot/json-subs
sudo cp test-sub.json /var/lib/vpn-bot/json-subs/test.json
```

```nginx
location /api/v4/JSON/ {
    alias /var/lib/vpn-bot/json-subs/;
    default_type application/json;
    add_header Content-Disposition 'attachment; filename="subscription.json"';
}
```

Пример URL: `https://sub.example.com/api/v4/JSON/test.json`

## Кастомизация

- Больше нод — скопируйте блок `srv_node*`, добавьте tag в `routing.balancers[0].selector`
- Без балансера — `outboundTag` вместо `balancerTag` в rules
- Reality / TCP — другая структура `streamSettings`; собирайте по dump-скрипту и доке Happ