"""Показать vless-ссылки клиента с панели (для сверки JSON outbound)."""
import asyncio
import sys

sys.path.insert(0, ".")

from db import database as db
from services.xui import get_api, _fetch_sub_links


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/dev/dump_client_sub_links.py <tg_id>")
        raise SystemExit(1)
    tg_id = int(sys.argv[1])
    subs = await db.get_active_subscriptions(tg_id)
    if not subs:
        print(f"No active subs for tg_id={tg_id}")
        return
    sub = subs[0]
    email = sub["client_email"]
    sub_id = sub.get("sub_id") or ""
    print(f"email={email} sub_id={sub_id}")
    api = await get_api()
    links = await _fetch_sub_links(api, sub_id) if sub_id else []
    if not links:
        print("No sub links")
        return
    for i, link in enumerate(links, 1):
        print(f"{i}. {link}")


if __name__ == "__main__":
    asyncio.run(main())