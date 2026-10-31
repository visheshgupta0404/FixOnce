"""First thing to run with a real key: proves the Meko connection and shows real response shapes.

    fixonce check   (or: python -m fixonce.meko_check)

It lists Meko's tools, saves one test memory, searches for it, and prints the raw responses,
so we can adjust `memory/backends.py` parsing if Meko's shapes differ from what we expect.
Then it deletes the test memory again.
"""
import asyncio
import json

from .config import settings
from .memory.backends import RealMeko, _walk_items


async def main() -> None:
    if not settings.meko_api_key:
        raise SystemExit("Set MEKO_API_KEY (and MEKO_DATAPACK_ID) in .env first.")
    meko = RealMeko(settings.meko_url, settings.meko_api_key, settings.meko_datapack_id)
    tools = await meko.client.list_tools()
    print(f"{len(tools)} tools:", ", ".join(t["name"] for t in tools))

    cid = await meko._cid(None)
    print("conversation_id:", cid)

    added = await meko.client.call("memory_add", meko._dp(
        text="FixOnce connection test: the checkout export job runs at 2 AM.", agent_id="scribe",
        metadata=json.dumps({"kind": "test"}), conversation_id=cid))
    print("\nmemory_add raw:", json.dumps(added, indent=2)[:1500])

    found = await meko.client.call("context_search", meko._dp(
        query="when does the checkout export job run", agent_id="recall", limit=3, conversation_id=cid))
    print("\ncontext_search raw:", json.dumps(found, indent=2)[:2500])
    print("\nparsed items:", [i.model_dump() for i in _walk_items(found, "memory")])

    for item in _walk_items(added, "stored"):
        if item.id:
            await meko.delete(item.id, "scribe")
            print("deleted test memory", item.id)


if __name__ == "__main__":
    asyncio.run(main())
