
import asyncio

from app.modules.llm.providers.groq_provider import GroqProvider


async def main():
    provider = GroqProvider()
    result = await provider.complete("Say hello")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

