import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from platformdirs import user_data_path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
from app.core.settings import Settings
from app.database.store import Store
from app.ui.window import Window


def main():
    parser = argparse.ArgumentParser(description='ATLAS public research desktop')
    parser.add_argument('--data-dir', type=Path, default=user_data_path('ATLAS', appauthor=False))
    parser.add_argument('--smoke-test', action='store_true', help='Validate GUI, WebEngine, graph and PDF resources without network access')
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    settings_path = args.data_dir / 'settings.json'
    settings = Settings.load(settings_path)
    os.environ.setdefault('QT_SCALE_FACTOR', str(settings.scale))
    application = QApplication(sys.argv[:1])
    application.setApplicationName('ATLAS')
    handler = RotatingFileHandler(args.data_dir / 'atlas.log', maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.getLogger('atlas').addHandler(handler)
    logging.getLogger('atlas').setLevel(logging.INFO)
    try:
        store = Store(Path(settings.database) if settings.database else args.data_dir / 'atlas.db')
        window = Window(store, settings, settings_path)
    except Exception as exc:
        QMessageBox.critical(None, 'ATLAS startup failed', 'Check the database path and settings. Error: ' + type(exc).__name__)
        return 1
    window.show()
    if args.smoke_test:
        from app.ui.smoke import start_smoke
        QTimer.singleShot(0, lambda: start_smoke(window, args.data_dir))
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
