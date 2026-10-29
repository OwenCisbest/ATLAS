# Validation record

Validated in this Linux cloud workspace with Python 3.12.14 and PySide6/Qt 6.12.0. This is not a Windows release certification.

## Passed

- 25 automated tests (`pytest -q`, no skips): database creation/reopen, notes persistence, duplicate investigations, cascade deletion, cross-workspace relationship rejection, SQLite backup, rejection of unsafe restored source URLs, URL validation, GitHub field minimization and separate candidates, Wikidata/Brave response normalization and filters, passive domain components with partial failure, authorization failures, retry/rate-limit exhaustion, timeout handling, deduplication, coordinator cancellation, AI citation acceptance/rejection, PDF/CSV/JSON exports and provenance, graph filtering/layout/SVG/PNG export, conservative matching, first-launch/navigation, and GUI heartbeat during background work and cancellation.
- Ruff checks for application, tests and scripts.
- Hash-checked dependency installation from `requirements.lock`, followed by editable package installation.
- Offscreen application launch with a newly initialized database and orderly exit through `--smoke-test`.
- Rendered dashboard and settings reviewed at 1400×900. Settings is scrollable; no browser/WebEngine is involved.

Tests use controlled HTTP responses. Test fixtures are not bundled as application research results. Live failures return errors and zero findings rather than sample data.

## Live checks blocked

Actual GitHub organization (`microsoft`) and public profile (`torvalds`), Wikidata (`Microsoft`), and domain (`example.com`) requests produced zero live findings in this environment. GitHub and Wikidata CONNECT attempts returned **HTTP 403 from the outbound proxy**. DNS/RDAP/CT requests also reported proxy failures. This is a live-access blocker, not proof of successful provider validation.

The environment draft now requests these explicit destinations while preserving its package-manager preset:

- `api.github.com`
- `www.wikidata.org`
- `dns.google`
- `data.iana.org`
- `rdap.verisign.com` (the .com registry used by the example.com check)
- `crt.sh`
- `example.com`
- `api.search.brave.com`

Other top-level domains use their IANA-listed RDAP service, and website metadata requires that specific public website to be permitted. Additional sites should be allowed deliberately, not by broadly disabling the outbound policy. Optional AI needs its user-selected HTTPS endpoint permitted separately.

Review and save the environment settings, then publish the environment when appropriate. Draft saving alone neither applies the network policy nor publishes a snapshot. After access is applied, rerun `scripts/live_check.py`; do not claim live integration acceptance before inspecting its results.

## Pending external validation

- Windows 10/11 build, executable launch, native display/scaling and Credential Manager. Reproducible script and CI workflow are supplied; neither ran on Windows here.
- Live Brave Search with a valid subscription and optional AI with a valid credential and per-request consent. No credentials were requested or embedded for local development.
- Human review of real-world entity matching and report content; rule grades are not calibrated probabilities.
- Full production-scale performance, accessibility and Unicode-font coverage. Bundled DejaVu handles common Latin/Greek/Cyrillic text; complete CJK coverage is not promised.

See `WINDOWS.md` for the manual release checklist and `ARCHITECTURE.md` for capability boundaries. The app is usable for local investigation, evidence, graph and report work now; live research in this cloud machine remains dependent on network-policy changes.
