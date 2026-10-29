import json
import sqlite3
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QSettings
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QStackedWidget,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QFormLayout, QDialog, QDialogButtonBox, QMessageBox, QInputDialog, QFileDialog,
    QCheckBox, QSpinBox, QDoubleSpinBox, QProgressBar, QHeaderView, QScrollArea)
from app.core.settings import Settings, secret, save_secret
from app.core.types import Request, Kind, Finding, ENTITY_TYPES, STATUSES, public_url
from app.database.store import Store, validate_backup
from app.research.providers import providers
from app.research.coordinator import Coordinator
from app.research.matching import suggest
from app.research.ai import transmission, summarize
from app.reports.export import export
from app.ui.worker import AsyncWorker
from app.visualization.graph import Graph

DARK = '''
QWidget { background: #101827; color: #e2e8f0; }
QMainWindow, QDialog { background: #101827; }
QListWidget { background: #0b1220; border: none; padding: 12px; }
QListWidget::item { padding: 12px 8px; border-radius: 6px; }
QListWidget::item:selected { background: #173b53; color: #67e8f9; }
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #1a2638; border: 1px solid #334155; padding: 7px; border-radius: 5px; }
QPushButton { background: #164e63; padding: 8px 14px; border: 1px solid #25647a; border-radius: 5px; }
QPushButton:hover { background: #155e75; } QPushButton:disabled { color: #64748b; background: #1e293b; }
QTableWidget { background: #111d2e; alternate-background-color: #172438; gridline-color: #25334a; border: 1px solid #334155; }
QHeaderView::section { background: #1e293b; color: #94a3b8; padding: 8px; border: none; }
QProgressBar { border: 1px solid #334155; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #0891b2; }
QLabel#heading { font-size: 25px; font-weight: 600; color: #67e8f9; }
'''


def button(text, callback, layout):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    layout.addWidget(widget)
    return widget


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    widget.setSelectionBehavior(QTableWidget.SelectRows)
    widget.setSelectionMode(QTableWidget.SingleSelection)
    widget.setEditTriggers(QTableWidget.NoEditTriggers)
    widget.setAlternatingRowColors(True)
    widget.setSortingEnabled(True)
    return widget


def populate(widget, rows, columns):
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, key in enumerate(columns):
            item = QTableWidgetItem(str(row.get(key, '')))
            item.setData(Qt.UserRole, row)
            widget.setItem(i, j, item)
    widget.setSortingEnabled(True)


def selected(widget):
    item = widget.item(widget.currentRow(), 0)
    return item.data(Qt.UserRole) if item else None


class Window(QMainWindow):
    def __init__(self, store: Store, settings: Settings, settings_path: Path):
        super().__init__()
        self.store, self.config, self.settings_path = store, settings, settings_path
        self.current = None
        self.worker = None
        self.ai_worker = None
        self.health = {}
        self.request_count = 0
        self.prefs = QSettings('ATLAS', 'Desktop')
        self.setWindowTitle('ATLAS — Public Research Workspace')
        self.resize(1400, 900)
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        self.nav = QListWidget()
        self.nav.setFixedWidth(225)
        self.nav.addItems(['Dashboard', 'New Investigation', 'Saved Investigations', 'Public Profile Research',
                          'Organization Research', 'Domain Intelligence', 'Relationship Graph',
                          'Evidence Library', 'Reports', 'Settings'])
        shell.addWidget(self.nav)
        main = QVBoxLayout()
        shell.addLayout(main, 1)
        top = QHBoxLayout()
        self.global_search = QLineEdit(placeholderText='Search public web with configured providers…')
        self.global_search.returnPressed.connect(self.global_research)
        self.current_label = QLabel('No investigation selected')
        self.current_label.setTextFormat(Qt.PlainText)
        self.status_label = QLabel('● Ready')
        top.addWidget(self.global_search, 2)
        top.addWidget(self.current_label, 1)
        top.addWidget(self.status_label)
        button('History', self.show_history, top)
        button('Notifications', self.show_notifications, top)
        main.addLayout(top)
        self.pages = QStackedWidget()
        main.addWidget(self.pages)
        self.dashboard = self.make_dashboard()
        self.saved = self.make_saved()
        self.research = self.make_research()
        self.graph_page = self.make_graph()
        self.evidence_page = self.make_evidence()
        self.reports_page = self.make_reports()
        self.settings_page = self.make_settings()
        for page in (self.dashboard, self.saved, self.research, self.graph_page,
                     self.evidence_page, self.reports_page, self.settings_page):
            self.pages.addWidget(page)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(160)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.statusBar().addPermanentWidget(self.progress)
        self.nav.currentRowChanged.connect(self.navigate)
        self.nav.setCurrentRow(0)
        for keys, action in [('Ctrl+N', self.new_investigation), ('Ctrl+S', self.save_notes), ('Ctrl+F', self.global_search.setFocus)]:
            shortcut = QAction(self)
            shortcut.setShortcut(keys)
            shortcut.triggered.connect(action)
            self.addAction(shortcut)
        geometry = self.prefs.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        self.apply_theme()
        self.refresh()
        last = self.prefs.value('investigation')
        if last and any(i['id'] == last for i in self.store.investigations()):
            self.open_investigation(last)

    def page(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        heading = QLabel(title)
        heading.setObjectName('heading')
        layout.addWidget(heading)
        label = QLabel(subtitle)
        label.setWordWrap(True)
        layout.addWidget(label)
        return widget, layout

    def notify(self, message):
        self.statusBar().showMessage(message, 15000)

    def error(self, message):
        QMessageBox.warning(self, 'ATLAS', str(message))

    def require(self):
        if not self.current:
            self.error('Create or open an investigation first.')
            return False
        return True

    def busy(self):
        return any(w and w.isRunning() for w in (self.worker, self.ai_worker))

    def make_dashboard(self):
        page, layout = self.page('ATLAS / Research overview', 'Public evidence. Explicit provenance. Conservative conclusions.')
        self.metrics = QLabel()
        self.metrics.setStyleSheet('font-size: 20px; padding: 20px;')
        layout.addWidget(self.metrics)
        self.scope_label = QLabel('Create an investigation to define its scope.')
        self.scope_label.setTextFormat(Qt.PlainText)
        self.scope_label.setWordWrap(True)
        layout.addWidget(self.scope_label)
        layout.addWidget(QLabel('Research notes — saved locally with Ctrl+S'))
        self.notes = QTextEdit()
        layout.addWidget(self.notes)
        actions = QHBoxLayout()
        button('Create investigation', self.new_investigation, actions)
        button('Save notes', self.save_notes, actions)
        button('Edit scope / description', self.edit_scope, actions)
        layout.addLayout(actions)
        layout.addWidget(QLabel('No telemetry. Research queries go only to enabled providers when you click Run.\n'
                                'Do not enter private contact details, home addresses, credentials, or sensitive personal information.'))
        return page

    def make_saved(self):
        page, layout = self.page('Saved investigations', 'Independent local workspaces, including archived investigations.')
        self.saved_filter = QLineEdit(placeholderText='Filter investigations…')
        self.saved_filter.textChanged.connect(self.refresh_saved)
        layout.addWidget(self.saved_filter)
        self.saved_table = table(['Title', 'Scope', 'Modified', 'Archived'])
        self.saved_table.doubleClicked.connect(self.open_selected)
        layout.addWidget(self.saved_table)
        actions = QHBoxLayout()
        for text, callback in [('Open', self.open_selected), ('Rename', self.rename), ('Duplicate', self.duplicate),
                               ('Archive / unarchive', self.archive), ('Delete', self.delete_investigation)]:
            button(text, callback, actions)
        layout.addLayout(actions)
        return page

    def make_research(self):
        page, layout = self.page('Research console', 'Results are candidates, not verified identities. Queries are transmitted to enabled providers.')
        controls = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems([k.value for k in Kind])
        self.query = QLineEdit(placeholderText='Name, public professional username, organization, or domain')
        self.query.returnPressed.connect(self.run_research)
        controls.addWidget(self.kind)
        controls.addWidget(self.query, 1)
        self.run_button = button('Run research', self.run_research, controls)
        self.cancel_button = button('Cancel', self.cancel, controls)
        self.cancel_button.setEnabled(False)
        layout.addLayout(controls)
        advanced = QHBoxLayout()
        self.exact = QCheckBox('Exact phrase (Brave)')
        self.site = QLineEdit(placeholderText='Restrict to domain (Brave)')
        self.freshness = QComboBox()
        self.freshness.addItems(['Any date', 'Past day', 'Past week', 'Past month', 'Past year'])
        for w in (self.exact, self.site, self.freshness):
            advanced.addWidget(w)
        layout.addLayout(advanced)
        self.research_log = QTextEdit()
        self.research_log.setReadOnly(True)
        self.research_log.setMaximumHeight(140)
        layout.addWidget(self.research_log)
        self.results = table(['Candidate / finding', 'Type', 'Provider', 'Status', 'Retrieved'])
        self.results.doubleClicked.connect(lambda: self.inspect(selected(self.results)))
        layout.addWidget(self.results)
        return page

    def make_graph(self):
        page, layout = self.page('Relationship graph', 'Evidence records are distinct nodes. Grades describe rule strength, not identity probabilities.')
        actions = QHBoxLayout()
        button('Suggest conservative matches', self.match, actions)
        button('Add sourced relationship / annotation', self.add_relationship, actions)
        button('Save layout', self.save_layout, actions)
        button('Export PNG / SVG', self.export_graph, actions)
        layout.addLayout(actions)
        self.graph = Graph()
        self.graph.inspect.connect(self.inspect_graph)
        layout.addWidget(self.graph)
        return page

    def make_evidence(self):
        page, layout = self.page('Evidence library', 'Inspect sources, tag records, add notes, and confirm or reject findings.')
        controls = QHBoxLayout()
        self.evidence_filter = QLineEdit(placeholderText='Filter title, provider, source, tags, or summary…')
        self.provider_filter = QComboBox()
        self.provider_filter.addItems(['All providers', 'Manual', *[p.name for p in providers()]])
        controls.addWidget(self.evidence_filter)
        controls.addWidget(self.provider_filter)
        layout.addLayout(controls)
        self.evidence_filter.textChanged.connect(self.refresh_evidence)
        self.provider_filter.currentTextChanged.connect(self.refresh_evidence)
        self.evidence_table = table(['Title', 'Type', 'Provider', 'Status', 'Tags', 'Retrieved'])
        self.evidence_table.doubleClicked.connect(lambda: self.inspect(selected(self.evidence_table)))
        layout.addWidget(self.evidence_table)
        actions = QHBoxLayout()
        button('Add sourced evidence', self.add_evidence, actions)
        button('Inspect / edit', lambda: self.inspect(selected(self.evidence_table)), actions)
        button('Delete record', self.delete_evidence, actions)
        layout.addLayout(actions)
        return page

    def make_reports(self):
        page, layout = self.page('Reports & analysis', 'Review evidence before export. AI is optional and requires approval for each transmission.')
        actions = QHBoxLayout()
        for fmt in ('pdf', 'csv', 'json'):
            button('Export ' + fmt.upper(), lambda checked=False, f=fmt: self.export_report(f), actions)
        button('Refresh preview', self.preview_report, actions)
        self.ai_button = button('AI summary…', self.ai_summary, actions)
        button('Cancel analysis', self.cancel, actions)
        layout.addLayout(actions)
        self.report_preview = QTextEdit()
        self.report_preview.setReadOnly(True)
        layout.addWidget(self.report_preview)
        return page

    def make_settings(self):
        page, layout = self.page('Settings', 'No API keys are needed to launch ATLAS. GitHub, Wikidata and Domain work without keys. '
            'Brave Search requires a subscription key; AI requires an endpoint, model and key. '
            'Credentials use the OS keyring; blank fields retain existing keys.')
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(['dark', 'light'])
        self.theme.setCurrentText(self.config.theme)
        self.font_size = QSpinBox()
        self.font_size.setRange(9, 20)
        self.font_size.setValue(self.config.font_size)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.75, 2)
        self.scale.setSingleStep(.25)
        self.scale.setValue(self.config.scale)
        self.timeout = QSpinBox()
        self.timeout.setRange(3, 120)
        self.timeout.setValue(self.config.timeout)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(self.config.concurrency)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(.5, 30)
        self.interval.setValue(self.config.request_interval)
        for label, widget in [('Theme', self.theme), ('Font size', self.font_size), ('Scale (restart)', self.scale),
                               ('Request timeout (seconds)', self.timeout), ('Concurrent providers', self.concurrency),
                               ('Minimum seconds between requests per host', self.interval)]:
            form.addRow(label, widget)
        self.provider_checks = {}
        for p in providers():
            check = QCheckBox(p.description)
            check.setChecked(p.name in self.config.enabled)
            self.provider_checks[p.name] = check
            form.addRow(p.name, check)
        self.key_fields = {}
        for name in ('github', 'brave', 'ai'):
            field = QLineEdit()
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText('Configured' if secret(name) else 'Not configured')
            self.key_fields[name] = field
            form.addRow(name.title() + ' API key', field)
        self.ai_enabled = QCheckBox('Enable optional AI (each transmission still requires consent)')
        self.ai_enabled.setChecked(self.config.ai_enabled)
        self.ai_endpoint = QLineEdit(self.config.ai_endpoint)
        self.ai_model = QLineEdit(self.config.ai_model)
        form.addRow(self.ai_enabled)
        form.addRow('AI HTTPS endpoint (OpenAI-compatible)', self.ai_endpoint)
        form.addRow('AI model', self.ai_model)
        self.db_location = QLineEdit(str(self.store.path))
        form.addRow('Database location (restart)', self.db_location)
        layout.addLayout(form)
        actions = QHBoxLayout()
        button('Save settings', self.save_settings, actions)
        button('Backup database', self.backup, actions)
        button('Restore backup', self.restore, actions)
        button('Diagnostics', self.show_notifications, actions)
        layout.addLayout(actions)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def navigate(self, index):
        if index == 1:
            self.new_investigation()
            self.nav.setCurrentRow(0)
            return
        mapping = {0: 0, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 4, 8: 5, 9: 6}
        if index in (3, 4, 5):
            self.kind.setCurrentText({3: 'profile', 4: 'organization', 5: 'domain'}[index])
        self.pages.setCurrentIndex(mapping.get(index, 0))
        if index == 6 and self.current:
            self.graph.load(self.store.snapshot(self.current))
        if index == 8:
            self.preview_report()

    def new_investigation(self):
        if self.busy():
            self.error('Cancel or finish the current operation before switching investigations.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('New investigation')
        form = QFormLayout(dialog)
        title, description, scope = QLineEdit(), QTextEdit(), QLineEdit('Public, source-backed research')
        form.addRow('Title', title)
        form.addRow('Description', description)
        form.addRow('Scope', scope)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        form.addRow(actions)
        if dialog.exec():
            try:
                identifier = self.store.create(title.text(), description.toPlainText(), scope.text())
                self.open_investigation(identifier)
            except ValueError as exc:
                self.error(exc)

    def open_investigation(self, identifier):
        if self.busy():
            self.error('Cancel or finish the current operation before switching investigations.')
            return
        self.save_notes()
        self.current = identifier
        data = self.store.snapshot(identifier)
        self.notes.setPlainText(data['investigation']['notes'])
        self.current_label.setText(data['investigation']['title'])
        self.graph.load(data)
        self.refresh()

    def open_selected(self, *_):
        row = selected(self.saved_table)
        if row:
            self.open_investigation(row['id'])
            self.nav.setCurrentRow(0)

    def refresh(self):
        self.refresh_saved()
        self.refresh_evidence()
        data = self.store.snapshot(self.current) if self.current else None
        self.metrics.setText(f"{len(self.store.investigations())} investigations    /    "
            f"{len(data['evidence']) if data else 0} evidence records    /    {len(data['relationships']) if data else 0} relationships")
        if data:
            self.scope_label.setText('Scope: ' + data['investigation']['scope'])
            self.current_label.setText(data['investigation']['title'])

    def refresh_saved(self, *_):
        query = self.saved_filter.text().casefold()
        rows = [r for r in self.store.investigations() if query in (r['title'] + ' ' + r['scope']).casefold()]
        populate(self.saved_table, rows, ['title', 'scope', 'modified', 'archived'])

    def refresh_evidence(self, *_):
        rows = self.store.snapshot(self.current)['evidence'] if self.current else []
        populate(self.results, rows, ['title', 'entity_type', 'provider', 'status', 'retrieved_at'])
        query = self.evidence_filter.text().casefold()
        filtered = [r for r in rows if query in ' '.join(str(v) for v in r.values()).casefold()
                    and (self.provider_filter.currentIndex() == 0 or r['provider'] == self.provider_filter.currentText())]
        populate(self.evidence_table, filtered, ['title', 'entity_type', 'provider', 'status', 'tags', 'retrieved_at'])

    def save_notes(self):
        if self.current:
            self.store.update(self.current, notes=self.notes.toPlainText())
            self.notify('Notes saved locally')

    def edit_scope(self):
        if not self.require():
            return
        inv = self.store.snapshot(self.current)['investigation']
        scope, ok = QInputDialog.getText(self, 'Research scope', 'Scope', text=inv['scope'])
        if ok:
            description, accepted = QInputDialog.getMultiLineText(self, 'Description', 'Description', inv['description'])
            if accepted:
                self.store.update(self.current, scope=scope, description=description)
                self.refresh()

    def rename(self):
        row = selected(self.saved_table)
        if row:
            name, ok = QInputDialog.getText(self, 'Rename', 'Title', text=row['title'])
            if ok and name.strip():
                self.store.update(row['id'], title=name)
                self.refresh()

    def duplicate(self):
        row = selected(self.saved_table)
        if row and not self.busy():
            self.save_notes()
            self.open_investigation(self.store.duplicate(row['id']))

    def archive(self):
        row = selected(self.saved_table)
        if row:
            self.store.update(row['id'], archived=not row['archived'])
            self.refresh()

    def delete_investigation(self):
        row = selected(self.saved_table)
        if not row or self.busy():
            return
        if QMessageBox.question(self, 'Delete investigation', f"Permanently delete {row['title']} and all its evidence?") == QMessageBox.Yes:
            if row['id'] == self.current:
                self.current = None
                self.notes.clear()
                self.current_label.setText('No investigation selected')
                self.graph.scene.clear()
                self.graph.nodes, self.graph.edges = {}, []
            self.store.delete(row['id'])
            self.refresh()

    def global_research(self):
        self.pages.setCurrentWidget(self.research)
        self.kind.setCurrentText('web')
        self.query.setText(self.global_search.text())
        self.run_research()

    def run_research(self):
        if not self.require() or self.busy():
            return
        try:
            request = Request(query=self.query.text(), kind=self.kind.currentText(), exact=self.exact.isChecked(),
                site=self.site.text(), freshness=['', 'pd', 'pw', 'pm', 'py'][self.freshness.currentIndex()])
        except ValueError as exc:
            self.error(exc)
            return
        identifier = self.current
        self.store.history(identifier, 'search', request.model_dump_json())
        coordinator = Coordinator(providers(), self.config, {k: secret(k) for k in ('github', 'brave')})
        async def operation(result, status):
            await coordinator.run(request, result, status)
            return coordinator.requests
        self.worker = AsyncWorker(operation, self)
        self.worker.result.connect(lambda finding: self.receive(identifier, finding))
        self.worker.status.connect(self.provider_status)
        self.worker.failed.connect(self.error)
        self.worker.completed.connect(self.count_requests)
        self.worker.finished.connect(self.research_finished)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.status_label.setText('● Research running')
        self.research_log.clear()
        self.worker.start()

    def receive(self, identifier, finding):
        try:
            self.store.add(identifier, finding)
            self.refresh()
        except Exception as exc:
            self.error('Could not save finding: ' + type(exc).__name__)

    def provider_status(self, provider, message):
        self.health[provider] = message
        self.research_log.append('')
        self.research_log.insertPlainText(provider + ': ' + message)
        self.notify(provider + ': ' + message)

    def count_requests(self, count):
        self.request_count += count or 0

    def research_finished(self):
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status_label.setText(f'● Idle · {self.request_count} API requests')
        if self.current:
            self.graph.load(self.store.snapshot(self.current))

    def cancel(self):
        for worker in (self.worker, self.ai_worker):
            if worker and worker.isRunning():
                worker.cancel()

    def inspect(self, row):
        if not row:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Evidence · ' + row['title'])
        dialog.resize(760, 650)
        form = QFormLayout(dialog)
        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(f"{row['title']}\n{row['provider']} · {row['retrieved_at']}\n{row['source_url']}\n\n"
                             f"{row['summary']}\n\n{json.dumps(json.loads(row['details']), indent=2, ensure_ascii=False)}")
        form.addRow(details)
        notes, tags, status = QTextEdit(row['notes']), QLineEdit(row['tags']), QComboBox()
        notes.setAcceptRichText(False)
        notes.setPlainText(row['notes'])
        status.addItems(STATUSES)
        status.setCurrentText(row['status'])
        form.addRow('Researcher notes', notes)
        form.addRow('Tags (comma separated)', tags)
        form.addRow('Verification', status)
        source = QPushButton('Open source in system browser')
        source.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(public_url(row['source_url']))))
        form.addRow(source)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        form.addRow(actions)
        if dialog.exec():
            self.store.evidence_update(row['id'], notes=notes.toPlainText(), tags=tags.text(), status=status.currentText())
            self.refresh()

    def add_evidence(self):
        if not self.require():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Add manually reviewed public evidence')
        form = QFormLayout(dialog)
        title, url, kind, summary = QLineEdit(), QLineEdit(), QComboBox(), QTextEdit()
        kind.addItems(ENTITY_TYPES)
        for label, widget in [('Title', title), ('Public HTTPS source', url), ('Entity type', kind),
                              ('Relevant public information (no private contact details)', summary)]:
            form.addRow(label, widget)
        form.addRow(QLabel('This creates an unverified researcher record. ATLAS does not fetch or verify this source.'))
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        form.addRow(actions)
        if dialog.exec():
            try:
                from app.security.privacy import minimize
                finding = Finding(provider='Manual', source_url=url.text(), title=minimize(title.text()),
                    entity_type=kind.currentText(), summary=minimize(summary.toPlainText()),
                    details={'provenance': 'Researcher-supplied public evidence; timestamp is entry time, not a verified fetch.'})
                self.store.add(self.current, finding)
                self.refresh()
            except ValueError as exc:
                self.error(exc)

    def delete_evidence(self):
        row = selected(self.evidence_table)
        if row and QMessageBox.question(self, 'Delete evidence', 'Delete this record and its relationships?') == QMessageBox.Yes:
            self.store.delete(row['id'], evidence=True)
            self.refresh()
            self.graph.load(self.store.snapshot(self.current))

    def match(self):
        if self.require():
            count = suggest(self.store, self.current)
            self.graph.load(self.store.snapshot(self.current))
            self.notify(f'{count} suggestions added. No identities were merged.')

    def add_relationship(self):
        if not self.require():
            return
        rows = self.store.snapshot(self.current)['evidence']
        if len(rows) < 2:
            self.error('Collect at least two source records first.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Source-backed relationship')
        form = QFormLayout(dialog)
        choices = []
        for label in ('From entity', 'To entity', 'Supporting evidence'):
            combo = QComboBox()
            for row in rows:
                combo.addItem(row['title'] + ' · ' + row['provider'], row['id'])
            choices.append(combo)
            form.addRow(label, combo)
        choices[1].setCurrentIndex(1)
        label, explanation = QLineEdit('publicly references'), QTextEdit()
        grade = QSpinBox()
        grade.setRange(0, 100)
        grade.setValue(25)
        annotation = QCheckBox('User annotation (visually distinguished)')
        form.addRow('Relationship', label)
        form.addRow('Evidence explanation', explanation)
        form.addRow('Heuristic grade (not probability)', grade)
        form.addRow(annotation)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        form.addRow(actions)
        if dialog.exec():
            try:
                self.store.relate(self.current, *(c.currentData() for c in choices), label.text(),
                                  explanation.toPlainText(), grade.value(), annotation.isChecked())
                self.graph.load(self.store.snapshot(self.current))
            except ValueError as exc:
                self.error(exc)

    def inspect_graph(self, row):
        if 'source_url' in row:
            self.inspect(row)
            return
        evidence = next((e for e in self.store.snapshot(self.current)['evidence'] if e['id'] == row['evidence_id']), None)
        message = row['explanation'] + f"\nGrade: {row['confidence']} (not a probability)\nSource: " + (evidence['source_url'] if evidence else '')
        status, ok = QInputDialog.getItem(self, row['label'], message, STATUSES, STATUSES.index(row['status']), False)
        if ok:
            self.store.relationship_status(row['id'], status)
            self.graph.load(self.store.snapshot(self.current))

    def save_layout(self):
        if self.require():
            self.store.update(self.current, layout=self.graph.positions())
            self.notify('Graph layout saved')

    def export_graph(self):
        if not self.require():
            return
        name, _ = QFileDialog.getSaveFileName(self, 'Export graph', 'atlas-graph.svg', 'SVG (*.svg);;PNG (*.png)')
        if name:
            try:
                self.graph.export(Path(name))
                self.store.history(self.current, 'export', 'Graph: ' + name)
            except Exception as exc:
                self.error(exc)

    def preview_report(self):
        if not self.current:
            self.report_preview.setPlainText('Open an investigation to preview its report.')
            return
        data = self.store.snapshot(self.current)
        lines = [data['investigation']['title'], 'Scope: ' + data['investigation']['scope'],
                 'Confidence grades are heuristic. Unverified records are candidate findings.']
        for row in data['evidence']:
            lines.extend([f"\n[{row['status']}] {row['title']}", row['summary'], row['source_url'], row['retrieved_at']])
        self.report_preview.setPlainText('\n'.join(lines))

    def export_report(self, fmt):
        if not self.require():
            return
        self.save_notes()
        name, _ = QFileDialog.getSaveFileName(self, 'Export report', 'atlas-report.' + fmt, f'{fmt.upper()} (*.{fmt})')
        if name:
            try:
                export(self.store.snapshot(self.current), Path(name), fmt)
                self.store.history(self.current, 'export', fmt.upper() + ': ' + name)
                self.notify('Report exported: ' + name)
            except Exception as exc:
                self.error('Export failed: ' + str(exc))

    def ai_summary(self):
        if not self.require() or self.busy():
            return
        if not self.config.ai_enabled or not secret('ai'):
            self.error('Enable AI and configure an API key in Settings first.')
            return
        records = transmission(self.store.snapshot(self.current))
        if not records:
            self.error('Collect evidence before requesting a summary.')
            return
        dialog = QDialog(self)
        dialog.resize(760, 600)
        dialog.setWindowTitle('Authorize this AI transmission')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('These exact records will be sent to ' + self.config.ai_endpoint + '\nModel: ' + self.config.ai_model))
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(json.dumps(records, indent=2, ensure_ascii=False))
        layout.addWidget(preview)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Ok).setText('Send these records')
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if not dialog.exec():
            return
        async def operation(result, status):
            return await summarize(records, self.config.ai_endpoint, self.config.ai_model, secret('ai'))
        self.ai_worker = AsyncWorker(operation, self)
        self.ai_worker.completed.connect(self.ai_complete)
        self.ai_worker.failed.connect(self.error)
        self.ai_worker.finished.connect(lambda: self.ai_button.setEnabled(True))
        self.ai_button.setEnabled(False)
        self.ai_worker.start()

    def ai_complete(self, claims):
        text = 'AI-GENERATED · UNVERIFIED\nCitation IDs validated; factual support requires human review.\n\n'
        text += '\n\n'.join(c['text'] + '\nEvidence: ' + ', '.join(c['citations']) for c in claims or [])
        self.report_preview.setPlainText(text)
        self.store.history(self.current, 'ai summary', text)

    def save_settings(self):
        try:
            public_url(self.ai_endpoint.text())
            config = Settings(theme=self.theme.currentText(), font_size=self.font_size.value(), scale=self.scale.value(),
                timeout=self.timeout.value(), concurrency=self.concurrency.value(), request_interval=self.interval.value(),
                enabled=[name for name, check in self.provider_checks.items() if check.isChecked()],
                ai_enabled=self.ai_enabled.isChecked(), ai_endpoint=self.ai_endpoint.text(), ai_model=self.ai_model.text(),
                database=self.db_location.text())
            for name, field in self.key_fields.items():
                save_secret(name, field.text())
                field.clear()
            config.save(self.settings_path)
            self.config = config
            self.apply_theme()
            self.notify('Settings saved. Database path and scaling changes take effect after restart.')
        except Exception as exc:
            self.error('Could not save settings or OS credentials: ' + type(exc).__name__)

    def apply_theme(self):
        self.setStyleSheet(DARK if self.config.theme == 'dark' else '')
        self.setFont(QFont('Segoe UI', self.config.font_size))

    def backup(self):
        self.save_notes()
        name, _ = QFileDialog.getSaveFileName(self, 'Backup database', 'atlas-backup.db', 'SQLite (*.db)')
        if name:
            try:
                self.store.backup(Path(name))
                self.notify('Database backup created')
            except Exception as exc:
                self.error(exc)

    def restore(self):
        if self.busy():
            self.error('Finish or cancel research before restoring.')
            return
        name, _ = QFileDialog.getOpenFileName(self, 'Restore ATLAS database', '', 'SQLite (*.db)')
        if not name:
            return
        try:
            validate_backup(Path(name))
            # Validate without executing SQL supplied by the file or touching the current DB.
            with sqlite3.connect(f'file:{Path(name).as_posix()}?mode=ro', uri=True) as source:
                if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup failed integrity check')
                if source.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise ValueError('Unsupported backup schema')
                names = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'investigations', 'evidence', 'relationships', 'history'} <= names:
                    raise ValueError('Not an ATLAS backup')
            if QMessageBox.question(self, 'Restore backup', 'Replace current data? A safety backup will be created first.') != QMessageBox.Yes:
                return
            safety = self.store.path.with_suffix('.before-restore.db')
            if safety.exists():
                from uuid import uuid4
                safety = self.store.path.with_name('before-restore-' + str(uuid4()) + '.db')
            self.store.backup(safety)
            destination = self.store.path
            self.store.close()
            with sqlite3.connect(name) as source, sqlite3.connect(destination) as target:
                source.backup(target)
            self.store = Store(destination)
            self.current = None
            self.notes.clear()
            self.graph.scene.clear()
            self.graph.nodes, self.graph.edges = {}, []
            self.current_label.setText('No investigation selected')
            self.refresh()
            self.notify('Backup restored; open a saved investigation.')
        except Exception as exc:
            self.error('Restore failed: ' + str(exc))

    def show_history(self):
        if self.require():
            rows = self.store.snapshot(self.current)['history']
            self.text_dialog('Search & export timeline', '\n\n'.join(r['created'] + ' · ' + r['category'] + '\n' + r['text'] for r in rows))

    def show_notifications(self):
        import importlib.metadata
        versions = '\n'.join(name + ': ' + importlib.metadata.version(name) for name in ('PySide6', 'SQLAlchemy', 'httpx', 'reportlab'))
        self.text_dialog('Diagnostics / provider status', 'ATLAS 0.1.0\n' + versions + '\n\n' +
            '\n'.join(k + ': ' + v for k, v in self.health.items()) + f'\nAPI requests this session: {self.request_count}\n'
            + 'Log: ' + str(self.settings_path.parent / 'atlas.log'))

    def text_dialog(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        content = QTextEdit()
        content.setReadOnly(True)
        content.setPlainText(text)
        layout.addWidget(content)
        dialog.exec()

    def closeEvent(self, event):
        if self.busy():
            self.cancel()
            self.notify('Cancelling background operations. Close again once they finish.')
            event.ignore()
            return
        self.save_notes()
        if self.current and self.graph.nodes:
            self.store.update(self.current, layout=self.graph.positions())
        self.prefs.setValue('geometry', self.saveGeometry())
        self.prefs.setValue('investigation', self.current or '')
        self.store.close()
        event.accept()
