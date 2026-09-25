"""
Скрипт сверки и восстановления истинных client_email в базе по sub_id с панели 3x-ui.
Запуск на сервере:
    python scripts/reconcile_subs.py
"""
import asyncio
import sys

sys.path.insert(0, ".")

from services.node_sync import reconcile_subscriptions_with_panel
from db import database as db


async def main() -> None:
    print("==================================================")
    print("  Запуск сверки подписок с панелью 3x-ui")
    print("==================================================")
    stats = await reconcile_subscriptions_with_panel()
    print(f"\n[OK] Результат сверки: проверено {stats['checked']}, исправлено {stats['reconciled']}, ошибок {stats['errors']}\n")

    print("--- Текущее состояние активных подписок в базе ---")
    subs = await db.get_all_active_subscriptions()
    for s in subs:
        print(f"ID #{s['id']:2d} | tg_id: {s.get('tg_id')} | Client: {s.get('client_email')} | Name: '{s.get('display_name')}' | sub_id: {s.get('sub_id')}")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
