#!/usr/bin/env bash
set -euo pipefail
cd /workspace/ATLAS
export UV_CACHE_DIR=/workspace/.uv-cache
uv venv --allow-existing .venv
uv pip sync --python .venv/bin/python --require-hashes requirements.lock
uv pip install --python .venv/bin/python --no-deps --no-build-isolation -e .
QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME=/tmp/atlas-test-config .venv/bin/python -m pytest -q
.venv/bin/ruff check app tests scripts
