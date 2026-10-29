"""Versioned SQLite persistence. One short-lived session per operation; GUI owns writes."""
import json
import sqlite3
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine, event, select, String, Text, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from app.core.types import Finding, now, STATUSES


class Base(DeclarativeBase):
    pass


class Investigation(Base):
    __tablename__ = 'investigations'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default='')
    scope: Mapped[str] = mapped_column(Text, default='Public, source-backed research')
    notes: Mapped[str] = mapped_column(Text, default='')
    created: Mapped[str] = mapped_column(default=now)
    modified: Mapped[str] = mapped_column(default=now)
    archived: Mapped[bool] = mapped_column(default=False)
    layout: Mapped[str] = mapped_column(Text, default='{}')


class Evidence(Base):
    __tablename__ = 'evidence'
    __table_args__ = (UniqueConstraint('investigation_id', 'provider', 'source_url'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey('investigations.id', ondelete='CASCADE'))
    provider: Mapped[str]
    source_url: Mapped[str]
    title: Mapped[str]
    entity_type: Mapped[str]
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text, default='{}')
    retrieved_at: Mapped[str]
    notes: Mapped[str] = mapped_column(Text, default='')
    tags: Mapped[str] = mapped_column(default='')
    status: Mapped[str] = mapped_column(default='unverified')


class Relationship(Base):
    __tablename__ = 'relationships'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey('investigations.id', ondelete='CASCADE'))
    source_id: Mapped[str] = mapped_column(ForeignKey('evidence.id', ondelete='CASCADE'))
    target_id: Mapped[str] = mapped_column(ForeignKey('evidence.id', ondelete='CASCADE'))
    evidence_id: Mapped[str] = mapped_column(ForeignKey('evidence.id', ondelete='CASCADE'))
    label: Mapped[str]
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[int] = mapped_column(Integer, default=25)
    status: Mapped[str] = mapped_column(default='unverified')
    annotation: Mapped[bool] = mapped_column(default=False)
    discovered: Mapped[str] = mapped_column(default=now)


class History(Base):
    __tablename__ = 'history'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey('investigations.id', ondelete='CASCADE'))
    category: Mapped[str]
    text: Mapped[str] = mapped_column(Text)
    created: Mapped[str] = mapped_column(default=now)


def record(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine('sqlite:///' + str(self.path))

        @event.listens_for(self.engine, 'connect')
        def configure(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA busy_timeout=5000')

        # Sequential migration 1. Future changes must introduce a new versioned migration.
        with self.engine.begin() as conn:
            version = conn.exec_driver_sql('PRAGMA user_version').scalar()
            if version > 1:
                raise ValueError('Database is newer than this ATLAS version')
            if version == 0:
                Base.metadata.create_all(conn)
                conn.exec_driver_sql('PRAGMA user_version=1')
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create(self, title: str, description: str = '', scope: str = '') -> str:
        if not title.strip():
            raise ValueError('A title is required')
        identifier = str(uuid4())
        with self.sessions.begin() as session:
            session.add(Investigation(id=identifier, title=title.strip(), description=description, scope=scope))
        return identifier

    def investigations(self) -> list[dict]:
        with self.sessions() as session:
            return [record(v) for v in session.scalars(select(Investigation).order_by(Investigation.modified.desc()))]

    def update(self, identifier: str, **fields):
        if not fields.keys() <= {'title', 'description', 'scope', 'notes', 'archived', 'layout'}:
            raise ValueError('Invalid investigation fields')
        if 'title' in fields and not fields['title'].strip():
            raise ValueError('A title is required')
        with self.sessions.begin() as session:
            row = session.get(Investigation, identifier)
            if row is None:
                raise ValueError('Investigation no longer exists')
            for key, value in fields.items():
                setattr(row, key, value)
            row.modified = now()

    def snapshot(self, identifier: str) -> dict:
        with self.sessions() as session:
            inv = session.get(Investigation, identifier)
            if inv is None:
                raise ValueError('Select an investigation')
            result = {'investigation': record(inv)}
            for name, model in [('evidence', Evidence), ('relationships', Relationship), ('history', History)]:
                result[name] = [record(v) for v in session.scalars(select(model).where(model.investigation_id == identifier))]
            return result

    def add(self, identifier: str, finding: Finding) -> str:
        with self.sessions.begin() as session:
            old = session.scalar(select(Evidence).where(Evidence.investigation_id == identifier,
                                 Evidence.provider == finding.provider, Evidence.source_url == finding.source_url))
            if old:
                return old.id
            data = finding.model_dump()
            data['details'] = json.dumps(data['details'], ensure_ascii=False)
            row = Evidence(id=str(uuid4()), investigation_id=identifier, **data)
            session.add(row)
            session.get(Investigation, identifier).modified = now()
            return row.id

    def evidence_update(self, identifier: str, **fields):
        if not fields.keys() <= {'notes', 'tags', 'status'}:
            raise ValueError('Invalid evidence fields')
        if 'status' in fields and fields['status'] not in STATUSES:
            raise ValueError('Invalid verification status')
        with self.sessions.begin() as session:
            row = session.get(Evidence, identifier)
            if row is None:
                raise ValueError('Evidence no longer exists')
            for key, value in fields.items():
                setattr(row, key, value)

    def relate(self, identifier: str, source: str, target: str, evidence: str, label: str,
               explanation: str, confidence: int = 25, annotation: bool = False) -> str:
        if source == target or not explanation.strip() or not 0 <= confidence <= 100:
            raise ValueError('Choose distinct entities, an explanation, and confidence from 0 to 100')
        with self.sessions.begin() as session:
            for key in (source, target, evidence):
                row = session.get(Evidence, key)
                if row is None or row.investigation_id != identifier:
                    raise ValueError('Entities and evidence must belong to this investigation')
            existing = session.scalar(select(Relationship).where(Relationship.investigation_id == identifier,
                Relationship.source_id == source, Relationship.target_id == target, Relationship.label == label))
            if existing:
                return existing.id
            row = Relationship(id=str(uuid4()), investigation_id=identifier, source_id=source,
                target_id=target, evidence_id=evidence, label=label, explanation=explanation,
                confidence=confidence, annotation=annotation)
            session.add(row)
            return row.id

    def relationship_status(self, identifier: str, status: str):
        if status not in STATUSES:
            raise ValueError('Invalid status')
        with self.sessions.begin() as session:
            session.get(Relationship, identifier).status = status

    def history(self, identifier: str, category: str, text: str):
        with self.sessions.begin() as session:
            session.add(History(id=str(uuid4()), investigation_id=identifier, category=category, text=text))

    def delete(self, identifier: str, evidence: bool = False):
        with self.sessions.begin() as session:
            row = session.get(Evidence if evidence else Investigation, identifier)
            if row:
                session.delete(row)

    def duplicate(self, identifier: str) -> str:
        data = self.snapshot(identifier)
        inv = data['investigation']
        new_id = self.create(inv['title'] + ' (copy)', inv['description'], inv['scope'])
        self.update(new_id, notes=inv['notes'])
        mapping = {}
        with self.sessions.begin() as session:
            for item in data['evidence']:
                row = dict(item)
                mapping[row['id']] = str(uuid4())
                row.update(id=mapping[row['id']], investigation_id=new_id)
                session.add(Evidence(**row))
            session.flush()
            for item in data['relationships']:
                row = dict(item)
                row.update(id=str(uuid4()), investigation_id=new_id)
                for key in ('source_id', 'target_id', 'evidence_id'):
                    row[key] = mapping[row[key]]
                session.add(Relationship(**row))
            for item in data['history']:
                session.add(History(**{**item, 'id': str(uuid4()), 'investigation_id': new_id}))
        layout = json.loads(inv['layout'])
        self.update(new_id, layout=json.dumps({mapping[k]: v for k, v in layout.items() if k in mapping}))
        return new_id

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise ValueError('Choose a different backup path')
        with sqlite3.connect(self.path) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)

    def close(self):
        self.engine.dispose()


def validate_backup(path: Path):
    """Treat an external backup as untrusted data before replacing the current database."""
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.row_factory = sqlite3.Row
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Backup failed integrity check')
        if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Unsupported backup version')
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Backup has broken evidence references')
        if conn.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchone():
            raise ValueError('Backup contains unexpected executable schema objects')
        for row in conn.execute('SELECT * FROM evidence'):
            Finding(provider=row['provider'], source_url=row['source_url'], title=row['title'],
                    entity_type=row['entity_type'], summary=row['summary'],
                    retrieved_at=row['retrieved_at'], details=json.loads(row['details']))
            if row['status'] not in STATUSES:
                raise ValueError('Invalid evidence verification status')
        for row in conn.execute('SELECT * FROM relationships'):
            if row['status'] not in STATUSES or not 0 <= row['confidence'] <= 100:
                raise ValueError('Invalid relationship')
            for key in ('source_id', 'target_id', 'evidence_id'):
                linked = conn.execute('SELECT investigation_id FROM evidence WHERE id=?', (row[key],)).fetchone()
                if not linked or linked[0] != row['investigation_id']:
                    raise ValueError('Cross-workspace relationship in backup')
        for row in conn.execute('SELECT layout FROM investigations'):
            layout = json.loads(row['layout'])
            if not isinstance(layout, dict):
                raise ValueError('Invalid graph layout')
            for position in layout.values():
                if not isinstance(position, list) or len(position) != 2:
                    raise ValueError('Invalid node position')
                import math
                if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in position):
                    raise ValueError('Invalid node coordinates')
