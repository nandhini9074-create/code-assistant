import asyncio

from app.infrastructure.qdrant.client import (
    init_qdrant,
    get_qdrant_client,
    close_qdrant,
)


async def main():
    await init_qdrant()

    try:
        client = get_qdrant_client()

        collections = await client.get_collections()

        print("\n=== QDRANT COLLECTIONS ===")

        for collection in collections.collections:
            print(collection.name)

            info = await client.get_collection(collection.name)

            print("  Points:", info.points_count)
            print("  Status:", info.status)

    finally:
        await close_qdrant()


if __name__ == "__main__":
    asyncio.run(main())