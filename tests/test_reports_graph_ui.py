import json
from pypdf import PdfReader
from PySide6.QtCore import QTimer
from app.core.types import Finding
from app.core.settings import Settings
from app.database.store import Store
from app.reports.export import export
from app.research.matching import suggest
from app.ui.window import Window
from app.ui.worker import AsyncWorker
from app.visualization.graph import Graph
import asyncio


def fixture_data(tmp_path):
    store = Store(tmp_path / 'atlas.db')
    inv = store.create('Evidence report', scope='Public organization research')
    a = store.add(inv, Finding(provider='A', source_url='https://example.com', title='=Candidate',
        entity_type='organization', summary='Public description', details={'username': 'same'}))
    b = store.add(inv, Finding(provider='B', source_url='https://example.org', title='Candidate 2',
        entity_type='public profile', details={'username': 'same'}))
    store.relate(inv, a, b, a, 'references', 'Explicit public source reference', 50)
    return store, inv


def test_exports(tmp_path):
    store, inv = fixture_data(tmp_path)
    data = store.snapshot(inv)
    for fmt in ('pdf', 'json', 'csv'):
        export(data, tmp_path / ('report.' + fmt), fmt)
    text = '\n'.join(p.extract_text() for p in PdfReader(tmp_path / 'report.pdf').pages)
    assert 'https://example.com' in text
    assert 'UNVERIFIED' in text
    assert 'Public description' in text
    assert len(json.loads((tmp_path / 'report.json').read_text())['evidence']) == 2
    assert "'=Candidate" in (tmp_path / 'report.csv').read_text('utf-8-sig')
    store.close()


def test_graph_filter_layout_export_and_matching(qtbot, tmp_path):
    store, inv = fixture_data(tmp_path)
    assert suggest(store, inv) == 1
    assert suggest(store, inv) == 0
    data = store.snapshot(inv)
    assert all(r['status'] == 'unverified' for r in data['relationships'])
    graph = Graph()
    qtbot.addWidget(graph)
    graph.resize(900, 600)
    graph.show()
    graph.load(data)
    assert len(graph.nodes) == 2
    graph.kind.setCurrentText('organization')
    assert sum(n.isVisible() for n in graph.nodes.values()) == 1
    graph.kind.setCurrentText('All types')
    graph.confidence.setValue(60)
    assert not any(e.isVisible() for e, _ in graph.edges)
    graph.confidence.setValue(0)
    node = next(iter(graph.nodes.values()))
    node.setPos(100, 150)
    assert json.loads(graph.positions())[node.row['id']] == [100, 150]
    graph.export(tmp_path / 'graph.svg')
    graph.export(tmp_path / 'graph.png')
    assert '<svg' in (tmp_path / 'graph.svg').read_text()
    assert (tmp_path / 'graph.png').read_bytes().startswith(b'\x89PNG')
    store.close()


def test_first_launch_navigation_and_notes(qtbot, tmp_path):
    store = Store(tmp_path / 'first.db')
    window = Window(store, Settings(), tmp_path / 'settings.json')
    qtbot.addWidget(window)
    window.show()
    assert window.pages.currentWidget() is window.dashboard
    inv = store.create('UI persistence')
    window.open_investigation(inv)
    window.notes.setPlainText('Saved from GUI')
    for index in (2, 3, 4, 5, 6, 7, 8, 9, 0):
        window.nav.setCurrentRow(index)
    window.close()
    reopened = Store(tmp_path / 'first.db')
    assert reopened.snapshot(inv)['investigation']['notes'] == 'Saved from GUI'
    reopened.close()


def test_worker_does_not_block_gui_and_cancels(qtbot):
    async def operation(result, status):
        result('first')
        await asyncio.sleep(100)
    worker = AsyncWorker(operation)
    results, ticks = [], []
    worker.result.connect(results.append)
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(10)
    worker.start()
    qtbot.waitUntil(lambda: len(ticks) >= 5 and bool(results), timeout=3000)
    worker.cancel()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=3000)
    timer.stop()
    assert results == ['first']


def test_exports_preserve_provenance_and_dates(tmp_path):
    store, inv = fixture_data(tmp_path)
    data = store.snapshot(inv)
    export(data, tmp_path / 'report.json', 'json')
    exported = json.loads((tmp_path / 'report.json').read_text())
    assert exported['evidence'][0]['retrieved_at'] == data['evidence'][0]['retrieved_at']
    assert exported['evidence'][0]['id'] == data['evidence'][0]['id']
    store.close()


def test_launch_without_optional_credentials(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr('app.ui.window.secret', lambda name: '')
    store = Store(tmp_path / 'no-keys.db')
    window = Window(store, Settings(), tmp_path / 'settings.json')
    qtbot.addWidget(window)
    window.show()
    assert window.pages.currentWidget() is window.dashboard
    assert not window.config.ai_enabled
    assert 'Brave Search' not in window.config.enabled
    assert all(field.placeholderText() == 'Not configured' for field in window.key_fields.values())
    window.close()


def test_bundled_asset_resolution(tmp_path, monkeypatch):
    import sys
    from app.core.paths import asset_path
    assert asset_path('packaging-check.html').is_file()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert asset_path('packaging-check.html') == tmp_path / 'assets' / 'packaging-check.html'
