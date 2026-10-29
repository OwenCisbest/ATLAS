from app.database.store import Store
from app.core.types import Finding


def test_persistence_duplicate_and_cascade(tmp_path):
    path = tmp_path / 'atlas.db'
    store = Store(path)
    inv = store.create('Research', scope='Public organizations')
    store.update(inv, notes='Persistent notes')
    f = Finding(provider='test', source_url='https://example.com/', title='Example', entity_type='organization')
    a = store.add(inv, f)
    assert store.add(inv, f) == a
    b = store.add(inv, f.model_copy(update={'source_url': 'https://example.org/'}))
    store.relate(inv, a, b, a, 'references', 'Source explicitly references the organization', 50)
    copy = store.duplicate(inv)
    assert len(store.snapshot(copy)['relationships']) == 1
    store.close()
    store = Store(path)
    assert store.snapshot(inv)['investigation']['notes'] == 'Persistent notes'
    store.delete(a, evidence=True)
    assert not store.snapshot(inv)['relationships']
    store.delete(inv)
    assert [i['id'] for i in store.investigations()] == [copy]
    store.close()


def test_backup_and_cross_workspace_relationship_rejection(tmp_path):
    import pytest
    store = Store(tmp_path / 'source.db')
    inv = store.create('One')
    other = store.create('Two')
    f = Finding(provider='test', source_url='https://example.com', title='A', entity_type='organization')
    a = store.add(inv, f)
    b = store.add(other, f)
    with pytest.raises(ValueError, match='belong'):
        store.relate(inv, a, b, a, 'references', 'Unsupported cross-workspace link')
    backup = tmp_path / 'backup.db'
    store.backup(backup)
    restored = Store(backup)
    assert len(restored.investigations()) == 2
    assert restored.snapshot(inv)['evidence'][0]['source_url'] == 'https://example.com'
    restored.close()
    store.close()


def test_restore_validation_rejects_untrusted_source_url(tmp_path):
    import sqlite3
    import pytest
    from app.database.store import validate_backup
    path = tmp_path / 'backup.db'
    store = Store(path)
    inv = store.create('Restore')
    store.add(inv, Finding(provider='test', source_url='https://example.com', title='A', entity_type='website'))
    store.close()
    validate_backup(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE evidence SET source_url='file:///etc/passwd'")
    with pytest.raises(ValueError):
        validate_backup(path)
