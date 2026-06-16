"""Очистка дубликатов xui_nodes в bot.db."""
import asyncio
import sys

from db.database import init_db
from db import xui_nodes as nodes_db


async def main() -> None:
    await init_db()
    before = await nodes_db.count_nodes()
    print(f"Записей до очистки: {before}")
    stats = await nodes_db.dedupe_nodes()
    print(
        f"Готово: было {stats['before']}, удалено {stats['removed']}, "
        f"осталось {stats['after']}"
    )
    primary = await nodes_db.get_primary_node()
    if primary:
        print(f"Основная: id={primary['id']} name={primary['name']} host={primary['host']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)