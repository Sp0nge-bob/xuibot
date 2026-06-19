# Шаблоны JSON-подписок

> **Отложено** — не подключено к боту; черновик под будущую задачу.

- **balancer-vless-ws.template.json** — пример: 2 ноды, VLESS/WebSocket/TLS, балансер `random`.

### Плейсхолдеры (бот)

| Плейсхолдер | Описание |
|-------------|----------|
| `__UUID__` | VLESS UUID клиента с панели |
| `__REMARKS__` | Название подключения в Happ |
| `__USER_ID__` | Telegram ID |
| `__CLIENT_EMAIL__` | Email клиента на панели |
| `__CREATED_AT__` | Время генерации |
| `__TEMPLATE_VERSION__` | Версия шаблона |

### Плейсхолдеры (инфраструктура — задаёт админ в шаблоне)

| Плейсхолдер | Описание |
|-------------|----------|
| `__NODE1_HOST__` | Домен/CDN первой ноды |
| `__NODE1_WS_PATH__` | WebSocket path первой ноды |
| `__NODE2_HOST__` | Домен/CDN второй ноды |
| `__NODE2_WS_PATH__` | WebSocket path второй ноды |

Перед тестом в Happ замените `__NODE*__` на реальные значения из панели (`scripts/dev/dump_inbound_for_json_template.py`).

Инструкция: [docs/json-subscription-template-setup.md](../docs/json-subscription-template-setup.md)

План: [docs/json-subscriptions-plan.md](../docs/json-subscriptions-plan.md)