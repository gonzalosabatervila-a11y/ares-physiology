# ARES container operations

- Start only with an empty synthetic `/data` during initial validation.
- Run one container and one `ares serve` process; never scale replicas against one DuckDB file.
- Mount static client credentials read-only under `/run/secrets/ares`; reserve `/data/secrets` for atomic persistence of rotating access/refresh/expiry values.
- Stop ARES before copying DuckDB. Hash the closed source and backup and restore into a new volume for testing.
- Keep `ARES_PROXY_AUTH_REQUIRED=1` and `APP_BIND=0.0.0.0:8443` only inside the private Docker network.
- Roll back the image and, when schema compatibility requires it, restore the pre-migration volume instead of attempting an in-place downgrade.
