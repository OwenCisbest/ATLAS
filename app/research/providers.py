import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit
import httpx
from app.core.types import Finding, Kind, Request, domain_name, public_url
from app.security.privacy import minimize


class ProviderError(Exception):
    pass


class Transport:
    def __init__(self, client: httpx.AsyncClient, interval: float = 1):
        self.client = client
        self.interval = interval
        self.locks = {}
        self.next_request = {}
        self.requests = 0

    async def get(self, url: str, **kwargs) -> httpx.Response:
        host = urlsplit(url).netloc
        lock = self.locks.setdefault(host, asyncio.Lock())
        for attempt in range(3):
            async with lock:
                loop = asyncio.get_running_loop()
                await asyncio.sleep(max(0, self.next_request.get(host, 0) - loop.time()))
                self.requests += 1
                try:
                    # Bound response size and never follow redirects to arbitrary/private destinations.
                    async with self.client.stream('GET', url, follow_redirects=False, **kwargs) as response:
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 5_000_000:
                                raise ProviderError('Response exceeded the 5 MB safety limit')
                        response._content = bytes(data)
                finally:
                    self.next_request[host] = loop.time() + self.interval
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                retry = response.headers.get('retry-after', '')
                delay = min(float(retry), 30) if retry.isdigit() else 2 ** attempt
                await asyncio.sleep(max(delay, self.interval))
                continue
            if response.status_code == 429:
                raise ProviderError('Rate limit reached; try again later')
            if response.status_code in (401, 403):
                raise ProviderError(f'Access denied ({response.status_code}); check API credentials or network policy')
            if 300 <= response.status_code < 400:
                raise ProviderError('Source redirects; use its canonical HTTPS address')
            response.raise_for_status()
            return response
        raise ProviderError('Request failed')


@dataclass
class Provider:
    name: str
    kinds: tuple[Kind, ...]
    credential: str = ''
    description: str = ''

    async def search(self, request: Request, transport: Transport, key: str):
        raise NotImplementedError


class GitHub(Provider):
    def __init__(self):
        super().__init__('GitHub', (Kind.PROFILE, Kind.ORGANIZATION), '', 'Public GitHub profiles; token optional')

    async def search(self, request, transport, key):
        headers = {'Accept': 'application/vnd.github+json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        query = request.query
        if query.startswith('https://github.com/'):
            query = urlsplit(query).path.strip('/').split('/')[0]
        query += ' type:org' if request.kind == Kind.ORGANIZATION else ' type:user'
        response = await transport.get('https://api.github.com/search/users',
            params={'q': query, 'per_page': 8}, headers=headers)
        for item in response.json().get('items', [])[:8]:
            login = item.get('login', '')
            if not re.fullmatch(r'[A-Za-z0-9-]{1,100}', login):
                continue
            detail = await transport.get('https://api.github.com/users/' + login, headers=headers)
            profile = detail.json()
            # Explicit allowlist: never retain email, location, contact fields or raw API responses.
            is_org = profile.get('type') == 'Organization'
            yield Finding(provider=self.name, source_url=profile['html_url'],
                title=minimize(profile.get('name') or login),
                entity_type='organization' if is_org else 'public profile',
                summary=minimize(profile.get('bio') or ''),
                details={'username': login, 'affiliation': minimize(profile.get('company') or ''),
                         'public_repositories': profile.get('public_repos', 0),
                         'match': 'Search candidate only; identity has not been verified.'})


class Wikidata(Provider):
    def __init__(self):
        super().__init__('Wikidata', (Kind.ORGANIZATION, Kind.WEB), '', 'Wikidata public knowledge search')

    async def search(self, request, transport, key):
        response = await transport.get('https://www.wikidata.org/w/api.php', params={
            'action': 'wbsearchentities', 'search': request.query, 'language': 'en', 'format': 'json', 'limit': 10})
        for row in response.json().get('search', []):
            if not re.fullmatch(r'Q\d+', row.get('id', '')):
                continue
            yield Finding(provider=self.name, source_url='https://www.wikidata.org/wiki/' + row['id'],
                title=minimize(row.get('label', row['id'])), entity_type='organization' if request.kind == Kind.ORGANIZATION else 'publication',
                summary=minimize(row.get('description', '')),
                details={'match': 'Candidate search result; organization classification requires review.', 'wikidata_id': row['id']})


class Brave(Provider):
    def __init__(self):
        super().__init__('Brave Search', tuple(Kind), 'brave', 'Official Brave Search API; subscription key required')

    async def search(self, request, transport, key):
        query = '"' + request.query.replace('"', '') + '"' if request.exact else request.query
        if request.site:
            query += ' site:' + request.site
        params = {'q': query, 'count': 10}
        if request.freshness:
            params['freshness'] = request.freshness
        response = await transport.get('https://api.search.brave.com/res/v1/web/search', params=params,
                                       headers={'X-Subscription-Token': key})
        for row in response.json().get('web', {}).get('results', []):
            try:
                url = public_url(row['url'])
            except ValueError:
                continue
            yield Finding(provider=self.name, source_url=url, title=minimize(row.get('title', url)),
                entity_type='website', summary=minimize(row.get('description', '')))


class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


async def ensure_public_host(host: str):
    addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ProviderError('Website resolves to a private or reserved address')


class Domain(Provider):
    def __init__(self):
        super().__init__('Domain', (Kind.DOMAIN,), '', 'Passive DNS, RDAP, certificate transparency and HTTPS metadata')

    async def search(self, request, transport, key):
        domain = domain_name(request.query)
        errors = []
        for record_type in ('A', 'AAAA', 'MX', 'NS', 'TXT', 'CAA'):
            url = 'https://dns.google/resolve'
            try:
                response = await transport.get(url, params={'name': domain, 'type': record_type})
                data = response.json()
                answers = [minimize(r.get('data', '')) for r in data.get('Answer', [])]
                yield Finding(provider=self.name, source_url=f'{url}?name={domain}&type={record_type}',
                    title=f'{domain} · DNS {record_type}', entity_type='domain',
                    summary='; '.join(answers) or f'No answer (DNS status {data.get("Status")})',
                    details={'record_type': record_type, 'dns_status': data.get('Status')})
            except (httpx.HTTPError, ProviderError, ValueError) as exc:
                errors.append(f'DNS {record_type}: {safe_error(exc)}')
        try:
            # IANA's bootstrap avoids forwarding to an unvalidated redirect target.
            bootstrap = (await transport.get('https://data.iana.org/rdap/dns.json')).json()
            tld = domain.rsplit('.', 1)[1]
            bases = [urls[0] for tlds, urls in bootstrap['services'] if tld in tlds and urls]
            if not bases:
                raise ProviderError('No RDAP service for this top-level domain')
            url = public_url(bases[0].rstrip('/') + '/domain/' + domain)
            data = (await transport.get(url)).json()
            safe = {'domain': data.get('ldhName', domain), 'status': data.get('status', []),
                    'events': [{'action': e.get('eventAction'), 'date': e.get('eventDate')} for e in data.get('events', [])],
                    'nameservers': [n.get('ldhName', '') for n in data.get('nameservers', [])]}
            yield Finding(provider=self.name, source_url=url, title=domain + ' · RDAP', entity_type='domain',
                          summary='Public registration metadata; registrant/contact data excluded.', details=safe)
        except (httpx.HTTPError, ProviderError, ValueError, KeyError) as exc:
            errors.append('RDAP: ' + safe_error(exc))
        try:
            url = 'https://crt.sh/'
            data = (await transport.get(url, params={'q': domain, 'output': 'json'})).json()
            # Do not imply certificate coverage establishes common ownership.
            names = sorted({name for row in data[:500] for name in row.get('name_value', '').splitlines()
                            if name == domain or name.endswith('.' + domain)})[:100]
            yield Finding(provider=self.name, source_url=f'https://crt.sh/?q={domain}',
                title=domain + ' · Certificate transparency', entity_type='domain',
                summary='Certificate names are not proof of ownership.', details={'certificate_names': names})
        except (httpx.HTTPError, ProviderError, ValueError) as exc:
            errors.append('Certificate transparency: ' + safe_error(exc))
        try:
            await ensure_public_host(domain)
            url = 'https://' + domain
            response = await transport.get(url)
            parser = TitleParser()
            parser.feed(response.text[:200_000])
            headers = {k: minimize(response.headers[k]) for k in
                       ('content-type', 'server', 'strict-transport-security', 'x-powered-by') if k in response.headers}
            yield Finding(provider=self.name, source_url=url, title=domain + ' · HTTPS metadata', entity_type='website',
                summary=minimize(parser.title[:1000]), details={'headers': headers, 'status': response.status_code,
                'limitations': 'Server headers are self-reported; no technology or ownership inference.'})
        except (httpx.HTTPError, ProviderError, ValueError, OSError) as exc:
            errors.append('Website: ' + safe_error(exc))
        if errors:
            raise ProviderError('Partial results. ' + ' | '.join(errors))


def safe_error(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return f'HTTP {exc.response.status_code}'
    if isinstance(exc, httpx.TimeoutException):
        return 'Request timed out'
    if isinstance(exc, httpx.HTTPError):
        return 'Network request failed; check connectivity and allowed destinations'
    return 'Source unavailable or returned invalid data'


def providers() -> list[Provider]:
    return [GitHub(), Wikidata(), Domain(), Brave()]
