# ATLAS

A local Python/Qt desktop workspace for source-backed public research on organizations, domains and public professional profiles. ATLAS stores independent investigations in SQLite, preserves evidence provenance, keeps possible identities separate, and exports cited reports.

## Download and run on Windows 11 (no Python needed)

1. Open [ATLAS on GitHub](https://github.com/OwenCisbest/ATLAS), select **Actions**, then **Build ATLAS for Windows**.
2. Select a successful run for the version/commit you want. To create one yourself, choose **Run workflow**, select **main**, and click **Run workflow**. The workflow must be present on the default branch for this button to appear. Pushes to `main` and pull requests also build automatically.
3. Wait for **Test, package and launch on Windows** to succeed. At the bottom of the run's summary, under **Artifacts**, click **ATLAS-Windows-x64**. You must be signed into GitHub; artifacts are retained for 30 days. If expired, run the workflow again.
4. Use Windows **Extract All** on the downloaded artifact archive. Inside it, find `ATLAS-Windows-x64.zip` and its SHA-256 checksum file. **Extract All again** on that inner ZIP to a writable folder such as `Documents\ATLAS`.
5. Open the extracted `ATLAS` folder and double-click **ATLAS.exe**. Keep the entire folder, including **_internal**, together. Do not launch from inside a ZIP or move the EXE alone. Python, pip, Qt and developer tools are **not** required on your computer.
6. The dashboard opens without any API keys. Create an investigation and use local evidence, graphs and reports immediately. In **Settings**, configure only the providers you want:

   | Feature | Configuration |
   |---|---|
   | GitHub public profiles/organizations | No key required for basic public requests; optional token improves limits |
   | Wikidata and passive domain research | No key; Internet access to the public sources required |
   | Brave Search / advanced web filters | Enable provider and supply a Brave Search subscription key |
   | AI summaries | Disabled by default; set HTTPS endpoint, model and key, then approve each exact payload before transmission |

Keys entered in Settings use Windows Credential Manager. Missing optional keys do not prevent launch, local investigation work or other providers. The application makes no research requests until you request research.

The ZIP is an unsigned portable application, not an installer. Windows may show a SmartScreen reputation prompt; verify the repository, run and checksum before deciding whether you trust the download. Updates are a fresh extracted folder; investigations remain in your per-user application data directory. Back up your data before updating.

**Verification:** the workflow uploads the application only after tests and an actual launch of the extracted EXE on a Windows runner succeed. That launch checks SQLite, bundled fonts/PDF, graph export, and local Qt WebEngine content with no API keys and Python removed from PATH. See the run logs and **ATLAS-Windows-validation** artifact (`smoke-result.json`, test results, sample graph/PDF) for evidence. Configuration of this workflow alone is not a claim that a Windows build has passed; Windows 11 hardware and live provider acceptance still require separate testing.

## Run from source

Python 3.12 is recommended. On Windows, from the repository directory:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements-windows.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
.venv\Scripts\python -m app.main
```

On Linux (desktop dependencies are included in this cloud image):

```bash
python3.12 -m venv .venv
uv pip sync --python .venv/bin/python --require-hashes requirements.lock
uv pip install --python .venv/bin/python --no-deps --no-build-isolation -e .
.venv/bin/python -m app.main
```

The default data directory is the OS application-data directory (`%LOCALAPPDATA%\ATLAS` on Windows). Override with `--data-dir PATH`. Credentials are held separately by the OS keyring. There is no plaintext fallback. An unavailable Linux keyring does not prevent credential-free providers or local work.

## Working with ATLAS

1. Create an investigation with a title, description and public-research scope.
2. Open Settings and choose providers. GitHub, Wikidata and Domain require no key for basic public requests. GitHub optionally accepts a token. Brave Search requires a subscription key and must be enabled explicitly.
3. Choose profile, organization or domain research, enter a query, then Run. The global search starts public web research. Exact phrases, domain restriction and date filters require Brave; unsupported providers are not silently used for these filters.
4. Results appear incrementally and persist immediately. Cancel retains collected evidence. Open Evidence Library to filter, tag, annotate, inspect sources, verify or delete a record. Manual public-source records support all seven entity types.
5. Add sourced relationships or ask for conservative suggestions. Suggestions never merge records. Matching grades are rule strengths, not probabilities. Select an edge to review its evidence and confirm or reject it.
6. Drag graph nodes, use the mouse wheel to zoom, drag the background to pan, filter, collapse neighbors, save the layout, or export PNG/SVG.
7. Review the Reports preview and export PDF, CSV or JSON. PDF contains sources, timestamps, status, methodology, notes and relationships. CSV is the evidence table; JSON is the structured report.
8. Optional AI requires an API key, HTTPS OpenAI-compatible endpoint and model. Every request presents the exact transmitted records and requires consent. The returned summary is labeled unverified and saved in history. Citation IDs are validated; entailment is **not** automatically verified. AI output does not create entities or relationships.

Ctrl+N creates an investigation; Ctrl+S saves notes; Ctrl+F focuses global search. Notes and graph positions are also saved on clean exit. History contains searches, exports and approved AI summaries. Saved investigations can be renamed, duplicated, archived, opened or deleted. Settings includes backup/restore, themes, fonts, scale, request controls and diagnostics.

## Validate and package

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check app tests scripts
QT_QPA_PLATFORM=offscreen .venv/bin/python -m app.main --data-dir /tmp/atlas-smoke --smoke-test
.venv/bin/python scripts/live_check.py
```

The live check makes real requests and reports failures; it is separate from offline tests. See [validation](docs/VALIDATION.md), [architecture](docs/ARCHITECTURE.md), [privacy](docs/PRIVACY.md), and [Windows distribution](docs/WINDOWS.md).

Build on Windows with `./scripts/build-windows.ps1`. The included GitHub Actions workflow runs the same build and uploads a standalone ZIP. A green workflow run and its validation artifact are the authority for Windows launch verification.
