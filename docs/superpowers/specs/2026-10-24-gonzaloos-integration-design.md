# GonzaloOS integration design

ARES remains an independent single-writer service. GonzaloOS and Caddy authenticate every request before Caddy strips `/ares` and proxies to ARES. Browser-facing URLs are relative so root development and prefixed production share one build. ARES refuses proxied writes without the trusted authorization marker, origin and CSRF header. See the companion GonzaloOS design for the trust diagram and deployment boundary.

No real database, OAuth secret, provider call or production host is part of this change. The base is PR #4 head `f601a0c`; PR #3 remains an unmerged dependency.
