def main() -> None:
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Manual Qdrant exploration script
    query = "Find the function that uses language translation"

    try:
        from sentence_transformers import SentenceTransformer
        from qdrant_client import QdrantClient

        model = SentenceTransformer("all-MiniLM-L6-v2")
        client = QdrantClient(
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY"),
        )
        query_vector = model.encode(query).tolist()

        results = client.query_points(
            collection_name="repo_ashwathie_language_translator",
            query=query_vector,
            limit=5,
            with_payload=True,
        )

        for result in results.points:
            print("SCORE:", result.score)
            print("NAME:", result.payload.get("name"))
            print("TYPE:", result.payload.get("chunk_type"))
            print("HASH:", result.payload.get("chunk_hash"))
            print("CODE:", result.payload.get("code"))
    except Exception as exc:
        print(f"Failed to query Qdrant: {exc}")


if __name__ == "__main__":
    main()