# Data handling

ATLAS has no telemetry, scheduled monitoring or hidden background searches. Queries are sent to enabled compatible providers only when research is requested. Providers receive the query, request metadata and, where configured, their own API credential. Website metadata requests use HTTPS only, refuse private/local targets and do not follow redirects.

GitHub ingestion explicitly excludes email and location. RDAP ingestion excludes registrant entities and contact vCards. Raw responses are not persisted. Text minimization removes common email, phone and street-address patterns. This is a defense in depth measure, **not** a guarantee that arbitrary prose contains no sensitive information. Researchers must avoid entering sensitive personal content and review evidence and reports before sharing. Technical source URLs, record identifiers and retrieval dates remain intact for provenance.

Notes and investigations are local plaintext SQLite data. Backups and exports are also unencrypted; use OS disk encryption and restrict file access. Deletion removes logical records and dependent relationships; it is not forensic secure erasure and does not remove previous backups or exported files. No secrets are written to SQLite, settings JSON, logs or reports. OS Credential Manager/keyring handles API keys. Diagnostics log provider name and error class, never headers or response bodies.

AI is disabled by default. Enabling AI alone sends nothing. Each summary request shows the exact payload (up to 50 records: IDs, titles, summaries, URLs and verification status) and destination/model. Cancel sends nothing. Model responses must cite existing IDs; citation existence does not establish factual support. All AI output remains labeled unverified. Untrusted evidence is quoted as data in the AI prompt, and model output cannot invoke tools or mutate the evidence graph.

Use only sources and APIs you are authorized to access. Respect provider terms and applicable laws. ATLAS does not circumvent authentication, CAPTCHAs or privacy settings.
