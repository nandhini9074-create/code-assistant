import asyncio

from app.modules.llm.providers.ollama_provider import OllamaProvider
from app.modules.llm.service.llm_service import LLMService


async def main():
    print("Testing OllamaProvider initialization...")
    provider = OllamaProvider()
    print(f"Provider initialized. Model: {provider.settings.ollama_model}, Base URL: {provider.settings.ollama_base_url}")

    print("Testing text completion...")
    result = await provider.complete("Say hello in one sentence.")
    print(f"Completion Result: {result.text}")
    print(f"Usage: {result.usage}")

    print("\nTesting structured JSON completion...")
    json_result = await provider.complete_json(
        prompt="List 2 programming languages with 'name' and 'year' fields.",
        schema={
            "type": "object",
            "properties": {
                "languages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "year": {"type": "integer"},
                        },
                        "required": ["name", "year"],
                    },
                }
            },
            "required": ["languages"],
        },
    )
    print(f"JSON Result: {json_result}")

    print("\nTesting LLMService with active Ollama provider...")
    llm_service = LLMService()
    print(f"LLMService provider type: {type(llm_service.provider).__name__}")
    intent = await llm_service.classify_intent("Add a new login endpoint with JWT authentication")
    print(f"Intent Classification Result: {intent}")


if __name__ == "__main__":
    asyncio.run(main())
