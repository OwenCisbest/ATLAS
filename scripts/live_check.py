"""Optional live integration check. Makes public API requests; never substitutes sample results."""
import asyncio
from app.core.settings import Settings
from app.core.types import Request, Kind
from app.research.providers import GitHub, Wikidata, Domain
from app.research.coordinator import Coordinator


async def main():
    for provider, kind, query in [(GitHub(), Kind.ORGANIZATION, 'microsoft'),
                                  (GitHub(), Kind.PROFILE, 'torvalds'),
                                  (Wikidata(), Kind.ORGANIZATION, 'Microsoft'),
                                  (Domain(), Kind.DOMAIN, 'example.com')]:
        results = []
        coordinator = Coordinator([provider], Settings(timeout=10, enabled=[provider.name]))
        await coordinator.run(Request(query=query, kind=kind), results.append,
                              lambda p, s: print(p, s, flush=True))
        print(f'{provider.name}: {len(results)} source-backed records', flush=True)
        for result in results[:2]:
            print(result.source_url, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
