import asyncio
import logging
import httpx
from app.core.types import Request
from app.core.settings import Settings
from app.research.providers import Transport, ProviderError, safe_error

logger = logging.getLogger('atlas.research')


class Coordinator:
    def __init__(self, providers, settings: Settings, credentials=None, client=None):
        self.providers = providers
        self.settings = settings
        self.credentials = credentials or {}
        self.client = client
        self.health = {}
        self.requests = 0

    async def run(self, request: Request, on_result, on_status):
        selected = [p for p in self.providers if p.name in self.settings.enabled and request.kind in p.kinds]
        # Advanced web filters are implemented only by the search API.
        if request.exact or request.site or request.freshness:
            selected = [p for p in selected if p.name == 'Brave Search']
        if not selected:
            on_status('Research', 'No compatible enabled provider. Advanced filters require Brave Search.')
            return
        semaphore = asyncio.Semaphore(self.settings.concurrency)
        seen = set()
        client = self.client or httpx.AsyncClient(timeout=self.settings.timeout,
            headers={'User-Agent': 'ATLAS/0.1 (public research desktop)'}, follow_redirects=False)
        transport = Transport(client, self.settings.request_interval)

        async def execute(provider):
            try:
                if provider.credential and not self.credentials.get(provider.credential):
                    raise ProviderError('Missing API key; configure it in Settings')
                async with semaphore:
                    on_status(provider.name, 'Running')
                    async with asyncio.timeout(self.settings.timeout * 15):
                        async for finding in provider.search(request, transport,
                                self.credentials.get(provider.credential or provider.name.lower(), '')):
                            key = (finding.provider, finding.source_url)
                            if key not in seen:
                                seen.add(key)
                                on_result(finding)
                self.health[provider.name] = 'Complete'
                on_status(provider.name, 'Complete')
            except asyncio.CancelledError:
                self.health[provider.name] = 'Cancelled; collected results retained'
                on_status(provider.name, self.health[provider.name])
                raise
            except Exception as exc:
                message = 'Provider operation timed out' if isinstance(exc, TimeoutError) else safe_error(exc)
                self.health[provider.name] = message
                logger.warning('provider_failed provider=%s error_type=%s', provider.name, type(exc).__name__)
                on_status(provider.name, message)

        try:
            await asyncio.gather(*(execute(p) for p in selected))
        finally:
            self.requests = transport.requests
            if self.client is None:
                await client.aclose()
