"""Explicit --smoke-test only: exercise the packaged GUI with no credentials/network."""
import json
import platform
import sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from app.core.paths import asset_path
from app.core.types import Finding
from app.reports.export import export


def start_smoke(window, directory):
    application = QApplication.instance()
    result_path = directory / 'smoke-result.json'
    result_path.unlink(missing_ok=True)
    browser = QWebEngineView(window)
    browser.resize(400, 200)
    browser.show()
    timer = QTimer(window)
    timer.setSingleShot(True)
    completed = False

    def finish(error=None):
        nonlocal completed
        if completed:
            return
        completed = True
        timer.stop()
        outcome = {'ok': error is None, 'error': error, 'platform': platform.system(),
                   'qt_platform': application.platformName(), 'frozen': bool(getattr(sys, 'frozen', False)),
                   'webengine_local_asset': error is None}
        result_path.write_text(json.dumps(outcome, indent=2), encoding='utf-8')
        browser.close()
        window.close()
        application.exit(0 if error is None else 1)

    def check_javascript(value):
        if value != 'atlas-local-assets-ok':
            finish('Local WebEngine JavaScript did not execute')
            return
        try:
            identifier = window.store.create('Packaging validation (test data)')
            window.open_investigation(identifier)
            window.store.add(identifier, Finding(provider='Packaging test', source_url='https://example.com',
                title='Packaging test record', entity_type='organization', summary='Synthetic packaging check only.'))
            data = window.store.snapshot(identifier)
            window.graph.load(data)
            window.graph.export(directory / 'smoke-graph.png')
            export(data, directory / 'smoke-report.pdf', 'pdf')
            if not (directory / 'smoke-graph.png').is_file() or not (directory / 'smoke-report.pdf').is_file():
                raise RuntimeError('Missing exported resources')
            finish()
        except Exception as exc:
            finish(type(exc).__name__ + ': ' + str(exc))

    def loaded(ok):
        if not ok:
            finish('WebEngine could not load its bundled local HTML asset')
        else:
            browser.page().runJavaScript('window.atlasPackagingCheck', check_javascript)

    browser.loadFinished.connect(loaded)
    timer.timeout.connect(lambda: finish('Packaging validation timed out'))
    timer.start(20000)
    browser.load(QUrl.fromLocalFile(str(asset_path('packaging-check.html'))))
    # Keep Python wrappers alive until all asynchronous callbacks finish.
    window._smoke_objects = (browser, timer)
