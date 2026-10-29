import asyncio
import json
import httpx
import pytest
from app.core.settings import Settings
from app.core.types import Kind, Request, Finding, public_url, domain_name
from app.research.providers import GitHub, Wikidata, Domain, Brave, Transport
from app.research.coordinator import Coordinator
from app.research.ai import summarize


@pytest.mark.parametrize('value', ['http://example.com', 'https://localhost', 'https://127.0.0.1',
                                   'https://10.0.0.1', 'https://user:pass@example.com', 'https://example.com:8080'])
def test_reject_private_urls(value):
    with pytest.raises(ValueError):
        public_url(value)


def test_domain_validation():
    assert domain_name('https://Example.com/path') == 'example.com'
    with pytest.raises(ValueError):
        domain_name('example.com/../../etc')


async def test_github_allowlist_and_profile_candidates():
    def respond(request):
        if request.url.path == '/search/users':
            return httpx.Response(200, json={'items': [{'login': 'researcher'}, {'login': 'other'}]})
        login = request.url.path.split('/')[-1]
        return httpx.Response(200, json={'login': login, 'name': 'Same Display Name', 'type': 'User',
            'html_url': 'https://github.com/' + login, 'email': 'private@example.com', 'location': 'Private location',
            'bio': 'Contact private@example.com or +1 202 555 0123', 'company': 'Public Org'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        records = [r async for r in GitHub().search(Request(query='researcher', kind=Kind.PROFILE), Transport(client, 0), '')]
    assert len(records) == 2
    assert records[0].source_url != records[1].source_url
    serialized = json.dumps([r.model_dump() for r in records])
    assert 'private@example.com' not in serialized
    assert 'Private location' not in serialized
    assert '202 555' not in serialized


async def test_wikidata_and_brave_filters():
    def respond(request):
        if request.url.host == 'www.wikidata.org':
            return httpx.Response(200, json={'search': [{'id': 'Q95', 'label': 'Google', 'description': 'technology company'}]})
        assert request.url.params['q'] == '"example" site:example.com'
        assert request.url.params['freshness'] == 'pw'
        assert request.headers['X-Subscription-Token'] == 'test-key'
        return httpx.Response(200, json={'web': {'results': [{'url': 'https://example.com', 'title': 'Example', 'description': 'Public page'}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        transport = Transport(client, 0)
        wiki = [r async for r in Wikidata().search(Request(query='Google', kind=Kind.ORGANIZATION), transport, '')]
        web = [r async for r in Brave().search(Request(query='example', kind=Kind.WEB, exact=True, site='example.com', freshness='pw'), transport, 'test-key')]
    assert wiki[0].source_url == 'https://www.wikidata.org/wiki/Q95'
    assert web[0].source_url == 'https://example.com'


async def test_domain_minimizes_rdap_and_partial_failures(monkeypatch):
    async def public(_):
        pass
    monkeypatch.setattr('app.research.providers.ensure_public_host', public)
    def respond(request):
        host = request.url.host
        if host == 'dns.google':
            return httpx.Response(200, json={'Status': 0, 'Answer': [{'data': '203.0.113.1'}]})
        if host == 'data.iana.org':
            return httpx.Response(200, json={'services': [[['com'], ['https://rdap.example.net/']]]})
        if host == 'rdap.example.net':
            return httpx.Response(200, json={'ldhName': 'example.com', 'status': ['active'],
                'entities': [{'vcardArray': ['secret private contact']}], 'events': []})
        if host == 'crt.sh':
            return httpx.Response(403)
        return httpx.Response(200, text='<title>Example domain</title>', headers={'server': 'example', 'set-cookie': 'private'})
    records, status = [], []
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        coordinator = Coordinator([Domain()], Settings(enabled=['Domain'], request_interval=.5), client=client)
        await coordinator.run(Request(query='example.com', kind=Kind.DOMAIN), records.append, lambda p, s: status.append(s))
    assert len(records) == 8
    assert 'Partial results' in status[-1]
    serialized = json.dumps([r.model_dump() for r in records])
    assert 'secret private contact' not in serialized
    assert 'set-cookie' not in serialized
    assert any('RDAP' in r.title for r in records)


async def test_provider_failure_does_not_discard_other_results():
    def respond(request):
        if request.url.host == 'api.github.com':
            return httpx.Response(401)
        return httpx.Response(200, json={'search': [{'id': 'Q1', 'label': 'A'}]})
    records, states = [], []
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        coordinator = Coordinator([GitHub(), Wikidata()], Settings(), client=client)
        await coordinator.run(Request(query='A', kind=Kind.ORGANIZATION), records.append, lambda p, s: states.append((p, s)))
    assert len(records) == 1
    assert any('Access denied' in s for _, s in states)


async def test_retry_then_success():
    calls = 0
    def respond(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={'retry-after': '0'}) if calls == 1 else httpx.Response(200, json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        response = await Transport(client, 0).get('https://example.com')
    assert response.status_code == 200 and calls == 2


async def test_cancellation_keeps_partial_results():
    class Slow:
        name, kinds, credential = 'Slow', (Kind.WEB,), ''
        async def search(self, request, transport, key):
            yield Finding(provider='Slow', source_url='https://example.com', title='First', entity_type='website')
            await asyncio.sleep(100)
    records = []
    coordinator = Coordinator([Slow()], Settings(enabled=['Slow']))
    task = asyncio.create_task(coordinator.run(Request(query='test', kind=Kind.WEB), records.append, lambda *_: None))
    for _ in range(100):
        if records:
            break
        await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(records) == 1
    assert 'Cancelled' in coordinator.health['Slow']


async def test_ai_rejects_fabricated_citations():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': json.dumps({'claims': [{'text': 'Unsupported', 'citations': ['invented']}]})}}]}))) as client:
        with pytest.raises(ValueError, match='citations'):
            await summarize([{'id': 'real'}], 'https://api.example.com/v1', 'model', 'key', client)


async def test_exhausted_rate_limit_and_missing_credentials():
    states = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={'retry-after': '0'}))) as client:
        from app.research.providers import ProviderError
        with pytest.raises(ProviderError, match='Rate limit'):
            await Transport(client, 0).get('https://example.com')
        coordinator = Coordinator([Brave()], Settings(enabled=['Brave Search']), client=client)
        await coordinator.run(Request(query='example', kind=Kind.WEB), lambda _: None, lambda _, s: states.append(s))
    assert 'Missing API key' in states[-1]


async def test_timeouts_and_duplicate_results():
    class Duplicate:
        name, kinds, credential = 'Duplicate', (Kind.WEB,), ''
        async def search(self, request, transport, key):
            finding = Finding(provider=self.name, source_url='https://example.com', title='A', entity_type='website')
            yield finding
            yield finding
            raise httpx.ReadTimeout('test')
    records, states = [], []
    coordinator = Coordinator([Duplicate()], Settings(enabled=['Duplicate']))
    await coordinator.run(Request(query='a', kind=Kind.WEB), records.append, lambda p, s: states.append(s))
    assert len(records) == 1
    assert states[-1] == 'Request timed out'


async def test_ai_accepts_only_cited_claims():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': json.dumps({'claims': [{'text': 'Public evidence description', 'citations': ['real']}]})}}]}))) as client:
        claims = await summarize([{'id': 'real'}], 'https://api.example.com/v1', 'model', 'key', client)
    assert claims[0]['citations'] == ['real']
