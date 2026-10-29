from datetime import datetime, timezone
from enum import StrEnum
from urllib.parse import urlsplit
import ipaddress
import re
from pydantic import BaseModel, Field, field_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Kind(StrEnum):
    PROFILE = 'profile'
    ORGANIZATION = 'organization'
    DOMAIN = 'domain'
    WEB = 'web'


ENTITY_TYPES = ('person', 'organization', 'website', 'domain', 'public profile', 'publication', 'project')
STATUSES = ('unverified', 'confirmed', 'rejected')


def public_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public HTTPS URL without credentials')
    host = parsed.hostname.lower()
    if host == 'localhost' or '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
        raise ValueError('Local and private destinations are not supported')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('Private IP destinations are not supported')
    if parsed.port not in (None, 443):
        raise ValueError('Only the standard HTTPS port is supported')
    return value


def domain_name(value: str) -> str:
    value = value.strip().lower().rstrip('.')
    if '://' in value:
        public_url(value)
        value = urlsplit(value).hostname or ''
    value = value.encode('idna').decode('ascii')
    if len(value) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', value):
        raise ValueError('Enter a public domain such as example.com')
    public_url('https://' + value)
    return value


class Request(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    kind: Kind
    exact: bool = False
    site: str = ''
    freshness: str = ''

    @field_validator('query')
    @classmethod
    def trim_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Query cannot be blank')
        return value.strip()

    @field_validator('site')
    @classmethod
    def validate_site(cls, value: str) -> str:
        return domain_name(value) if value else ''

    @field_validator('freshness')
    @classmethod
    def validate_freshness(cls, value: str) -> str:
        if value not in ('', 'pd', 'pw', 'pm', 'py'):
            raise ValueError('Unsupported date filter')
        return value


class Finding(BaseModel):
    provider: str
    source_url: str
    title: str = Field(max_length=1000)
    entity_type: str
    summary: str = Field(default='', max_length=12000)
    retrieved_at: str = Field(default_factory=now)
    details: dict = Field(default_factory=dict)

    @field_validator('source_url')
    @classmethod
    def validate_url(cls, value: str) -> str:
        return public_url(value)

    @field_validator('entity_type')
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in ENTITY_TYPES:
            raise ValueError('Unknown entity type')
        return value
