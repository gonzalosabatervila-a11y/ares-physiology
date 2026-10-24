# GonzaloOS private proxy contract

ARES is served at `/ares/` only through Caddy. Caddy first asks GonzaloOS to validate the current cookie, MFA state and (for unsafe methods) CSRF token, then strips the prefix and proxies to the single `ares serve` process. Client-supplied `X-Ares-*` headers are deleted. ARES compares the copied assertion and CSRF headers and requires same-host HTTPS Origin before any LAB write.

Browser asset, API and manifest paths are relative, preserving both root development and prefixed deployment. `/api/healthz` checks DuckDB availability without requiring provider data. The container runs non-root and reads optional connector secrets from files in `/run/secrets/ares` before falling back to desktop keyring.
