import asyncio

from app.infrastructure.qdrant.client import (
    init_qdrant,
    get_qdrant_client,
    close_qdrant,
)


async def main():
    try:
        await init_qdrant()

        client = get_qdrant_client()

        collections = await client.get_collections()

        print("\nQDRANT CONNECTION: SUCCESS")
        print("\nCollections:")

        for collection in collections.collections:
            print(" -", collection.name)

    except Exception as e:
        print("\nQDRANT CONNECTION: FAILED")
        print(e)

    finally:
        await close_qdrant()


if __name__ == "__main__":
    asyncio.run(main())