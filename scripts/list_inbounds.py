import asyncio
import sys

sys.path.insert(0, ".")

from services.xui import get_api


async def main() -> None:
    api = await get_api()
    inbounds = await api.inbound.get_list()
    for ib in sorted(inbounds, key=lambda x: x.id):
        proto = getattr(ib, "protocol", "?")
        port = getattr(ib, "port", "?")
        remark = getattr(ib, "remark", "") or ""
        clients = len(ib.settings.clients or [])
        print(f"id={ib.id:3d} port={port} proto={proto} clients={clients} remark={remark[:40]}")


if __name__ == "__main__":
    asyncio.run(main())