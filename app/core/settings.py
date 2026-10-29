import json
from pathlib import Path
import keyring
from pydantic import BaseModel, Field


class Settings(BaseModel):
    theme: str = 'dark'
    font_size: int = Field(default=11, ge=9, le=20)
    scale: float = Field(default=1.0, ge=0.75, le=2.0)
    timeout: int = Field(default=20, ge=3, le=120)
    concurrency: int = Field(default=3, ge=1, le=8)
    request_interval: float = Field(default=1.0, ge=0.5, le=30)
    enabled: list[str] = Field(default_factory=lambda: ['GitHub', 'Wikidata', 'Domain'])
    ai_enabled: bool = False
    ai_endpoint: str = 'https://api.openai.com/v1/chat/completions'
    ai_model: str = 'gpt-4.1-mini'
    database: str = ''

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text('utf-8')) if path.exists() else cls()

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2), 'utf-8')


def secret(name: str) -> str:
    try:
        return keyring.get_password('ATLAS', name) or ''
    except keyring.errors.KeyringError:
        return ''


def save_secret(name: str, value: str):
    # No plaintext fallback. Windows uses Credential Manager via keyring.
    if value:
        keyring.set_password('ATLAS', name, value)
