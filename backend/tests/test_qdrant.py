query = "Find the function that uses language translation"

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