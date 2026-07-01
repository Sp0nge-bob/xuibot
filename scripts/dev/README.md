# Скрипты разработки

Не используются в продакшене. Запускайте из корня проекта:

```bash
python scripts/dev/test_admin_diagnostics.py
python scripts/dev/test_pending_flow.py   # нужен TEST_MODE=true
python scripts/dev/test_api_flow.py
```

Для эксплуатации достаточно `scripts/list_inbounds.py` и `scripts/dedupe_nodes.py`.