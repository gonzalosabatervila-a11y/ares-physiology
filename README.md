# ARES Semana 0 — Bootstrap v0.1

Objetivo: **repo → DuckDB → migraciones → keyring → intervals.icu real ✅**

No completa la semana 0: faltan el HP con el servicio, Tailscale en el HP, el cliente de Polar y Tredict
(Bootstrap v0.2). Referencia: *ARES Physiology — Implementation Plan v0.2 FINAL — FROZEN*.

## Los cinco comandos (MacBook Air)

**1. Herramientas.** git viene con las herramientas de desarrollo de Apple; uv instala Python 3.12 solo.

```bash
xcode-select --install          # solo si `git --version` falla
curl -LsSf https://astral.sh/uv/install.sh | sh    # o: brew install uv
```

Cierra y abre la Terminal después de instalar uv.

**2. Repositorio.**

```bash
cd ~ && unzip ~/Downloads/ares-semana0.zip && cd ~/ares
git init -q && git add -A && git commit -qm "ARES Semana 0 — Bootstrap v0.1"
```

**3. Entorno y tests.**

```bash
uv sync
uv run pytest -q                # debe decir: 14 passed
```

**4. Clave de intervals.icu en el Llavero** (intervals.icu → Settings → Developer Settings → API key).

```bash
uv run ares secret set intervals_api_key
```

Pega la clave (no se ve al escribir). macOS puede pedir permiso para el Llavero: «Permitir siempre».
Después, borra el fichero de texto donde la tenías guardada.

**5. Base, diagnóstico y datos reales.**

```bash
uv run ares init-db
uv run ares doctor              # debe decir: 7/7 comprobaciones correctas
uv run ares sync intervals --days 30
uv run ares stats
```

Resultado esperado: `intervals/wellness: N filas` con tus últimos 30 días. Repetir el `sync` no duplica nada.

## Comandos disponibles

| Comando | Qué hace |
|---|---|
| `ares init-db` | Crea `~/ares-data/ares.duckdb` y aplica las migraciones pendientes |
| `ares secret set|check <clave>` | Guarda o comprueba un secreto en el almacén del sistema; nunca lo muestra |
| `ares sync intervals --days N` | Descarga el bienestar de intervals.icu a la capa bruta (solo añadir) |
| `ares doctor [--offline]` | Python, zona horaria, carpeta de datos, schema_version, secretos y red |
| `ares stats` | Filas de la capa bruta por fuente y últimas ejecuciones |

## Qué hay dentro

- `migrations/001–003`: esquema del plan v0.2 FINAL (con `source_status.device_id NOT NULL DEFAULT 'global'`
  y `decisions_recomputed` con `recompute_id`). `schema_version` registra cada migración con su hash;
  editar una migración ya aplicada se detecta y bloquea.
- `src/ares/`: configuración, secretos (keyring), logs JSON en `~/ares-data/logs/ares.jsonl`,
  base de datos, reintentos 2/8/30 s, capa bruta con hash, conector de intervals.icu, `job_runs`
  con commit, versión y host.
- `tests/`: migraciones y `schema_version`, contrato de intervals.icu, idempotencia, reintentos y doctor.

Datos en el Mac: `~/ares-data` (desarrollo). En el HP de producción: `ARES_DATA_DIR=C:\ares-data` en `.env`.
