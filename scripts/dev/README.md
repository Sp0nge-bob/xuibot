# Скрипты разработки

Не используются в продакшене. Запускайте из корня проекта:

```bash
python scripts/dev/smoke_python314.py     # offline smoke (3.11–3.14), без панели
python scripts/dev/test_admin_diagnostics.py
python scripts/dev/test_pending_flow.py   # нужен TEST_MODE=true
python scripts/dev/test_api_flow.py
```

`smoke_python314.py` — compileall, импорт всех модулей, SQLite init/CRUD, QR, pricing, FastAPI routes. Не стартует polling и не ходит в 3x-ui.

Для эксплуатации достаточно `scripts/list_inbounds.py` и `scripts/dedupe_nodes.py`.