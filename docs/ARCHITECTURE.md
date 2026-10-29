# Architecture and scope

- `app/core`: Pydantic requests/results, URL validation, JSON settings, OS-keyring access.
- `app/database`: SQLAlchemy models and short-lived sessions. SQLite foreign keys cascade deletions. `PRAGMA user_version=1` is the first transactional migration; newer schema versions are rejected. Future schema edits must add sequential migrations before updating this version.
- `app/research`: provider metadata/interface, httpx transport, asyncio coordinator, conservative matching, optional AI. Async generators deliver partial records. Per-host locks enforce minimum intervals; provider concurrency is bounded. HTTP 429 and transient HTTP 5xx receive up to three attempts with exponential backoff/Retry-After. Individual and provider-total timeouts are bounded. Network failures produce provider health errors; other providers continue.
- `app/ui`: Qt widgets, application window and QThread worker. The worker owns its asyncio loop; Qt signals marshal updates to the GUI thread. A cancellation event and periodic check ensure bounded cancellation without blocking the UI. Database writes occur on the GUI thread.
- `app/visualization`: native QGraphicsScene nodes/edges. Native Qt was selected instead of WebEngine/Cytoscape to reduce package size and avoid embedded browser injection/navigation. Graph labels are plain text. Records remain separate; evidence IDs link relationships to sources.
- `app/reports`: PDF with bundled licensed DejaVu fonts, spreadsheet-safe CSV and structured JSON. No credentials or raw API payloads enter exports.

## Provider capabilities

| Provider | Implemented operations | Configuration / limits |
|---|---|---|
| GitHub | Public user/organization search and explicit profile-field allowlist | Optional token; 8 candidates per query; profiles are possible matches |
| Wikidata | Public entity search with source IDs/descriptions | No key; 10 candidates; organization classification requires review |
| Domain | DNS A/AAAA/MX/NS/TXT/CAA via Google DoH, IANA-bootstrapped RDAP, crt.sh CT names, HTTPS title/selected headers | Public domain only; individual components can fail independently; contacts excluded |
| Brave Search | Official search API, phrase/site/date filters | Subscription key; enable in Settings; 10 results |
| AI | User-approved evidence summaries with citation-ID validation | Disabled by default; OpenAI-compatible HTTPS API and key |

An evidence record is also a distinct entity observation/node. There is deliberately no automatic canonical-person merge. Identical provider+source URLs deduplicate within an investigation; different providers remain independently attributable. Rules suggest identical-URL matches (75/100) or same-username matches (25/100), never same-name-only matches. Neither score verifies identity. Researchers can link observations manually with source evidence and explanations.

## Limits and deliberate choices

No SEC, OpenCorporates, professional-directory scraping, private social-network scraping, intrusive scans, geolocation history, face recognition, breach data, or automated monitoring is implemented. No claim is made that those sources are searched. Domain registration excludes all RDAP entities/vCards. Hosting observations are limited to public DNS/headers; they do not prove ownership. CT names do not automatically create ownership edges.

Redirected websites return a clear error instead of following arbitrary redirects. DNS resolution is checked for private/reserved destinations before website requests; deploy behind an outbound policy if strong DNS-rebinding isolation is required. A local desktop application is not a hardened multi-tenant fetch service.

AI summaries are retained in history, separate from factual evidence. They are not automatically included as verified findings in reports. The report preview is textual rather than a pixel-identical PDF rendering. No general JSON import is supported; restore accepts an ATLAS SQLite backup. Large investigations may require additional performance work: graph layout and report generation run on the GUI thread. Tests cover small representative investigations, not production-scale datasets.
