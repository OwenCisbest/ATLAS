# Windows distribution

## Build

Use Windows 10/11 x64 with Python 3.12 x64 on PATH and PowerShell. Run `./scripts/build-windows.ps1` from the checkout. It installs the hash-pinned Windows lockfile into `.venv`, installs ATLAS locally, runs tests, builds a PyInstaller directory distribution, extracts the ZIP outside the checkout and smoke-tests its executable using the native Windows Qt platform with Python removed from PATH and a null keyring and creates `dist/ATLAS-Windows-x64.zip`.

Extract the entire ZIP and run `ATLAS/ATLAS.exe`. The directory contains Qt plugins, Python runtime, libraries, fonts and keyring backend; do not distribute only the executable. End users do not need Python. The build is unsigned; signing and installer creation are outside this repository's current distribution workflow. Pinning dependencies makes the dependency set repeatable, not the binary byte-for-byte reproducible across Windows SDK/toolchain versions.

The **Build ATLAS for Windows** workflow (`.github/workflows/windows.yml`) supports push, pull request and manual **Run workflow** runs. The downloadable artifact is **ATLAS-Windows-x64**; it contains `ATLAS-Windows-x64.zip` and a SHA-256 checksum. Extract the artifact archive and then the inner ZIP. The **ATLAS-Windows-validation** artifact contains unit test XML and packaged-launch evidence. Artifacts expire after 30 days.

`ATLAS.spec` uses PyInstaller's matching PySide6 hooks for Qt DLLs/plugins, WebEngineProcess, .pak resources, ICU data and locales, and explicitly includes local assets and report fonts. ATLAS retains its native Qt graph; a local HTML/JavaScript page tests the included WebEngine runtime without network access. The bundled smoke test must produce a successful frozen-Windows result before the downloadable artifact can be uploaded.

Changing the workflow from Linux does not verify a Windows binary. Inspect the specific successful Windows run and its validation evidence; physical Windows 11 checks below remain necessary.

## Required release checks on Windows 10 and 11

- Run the packaged executable on a clean machine without Python installed.
- Verify first launch/database creation, resize, light/dark theme, 100% and 150% scaling.
- Create an investigation, save notes, restart, reopen, duplicate, archive and delete it.
- Store a test API key in Windows Credential Manager; verify retrieval after restart and no plaintext credential files.
- Run real GitHub organization/profile, Wikidata and domain queries with permitted outbound access. Check 401/403/429 behavior and cancellation.
- Configure Brave and verify phrase, site and date filters against a valid subscription.
- Move/filter/select graph nodes and edges, inspect evidence, save/reopen layout, export SVG/PNG.
- Open PDF/CSV/JSON reports with normal Windows applications; inspect citations, dates, non-ASCII characters and verification labels.
- With explicit consent and an AI key, validate a summary, cancellation, invalid credentials and rejected unknown citations.
- Test database backup/restore and filesystem-permission failures.

## Troubleshooting

- Missing Python on build machine: install Python 3.12 x64 with the `py` launcher. This does not apply to packaged end users.
- Qt platform plugin errors: preserve the complete distribution directory; do not copy its EXE alone.
- Credential errors: use an interactive Windows user with Credential Manager available. ATLAS will not fall back to plaintext storage.
- Network/proxy errors: allow the destinations in `docs/VALIDATION.md`, preserve corporate CA trust and HTTPS proxy configuration. Do not disable TLS verification.
- Database permission failure: select a writable per-user location using `--data-dir` or Settings. Back up before moving data.
- No matches: check enabled providers, credentials and status. Advanced filters run only through Brave Search. No records are fabricated during outages.
- GUI close during research: cancellation is requested; close again after operations stop to preserve partial results safely.
