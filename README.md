# ARES Bootstrap

## v0.1 — completado
repo → DuckDB → migraciones → keyring → intervals.icu real ✅

## v0.2 — completado
+ conector de Tredict (lista de actividades, paginada) → capa bruta ✅

## v0.3 — este paquete
+ `ares serve`: proceso único, propietario de DuckDB, con planificador interno
  (mañana 06:00–10:30 cada 30 min, día 11:00–23:00 cada hora) ✅
+ Lógica de sincronización compartida (`runner.py`) entre `ares sync` manual y el
  planificador, con decisión incremental/backfill automática ✅
+ `ares polar-auth`: autorización OAuth2 con Polar (servidor local en el
  `redirect_uri`, intercambio y renovación de tokens) ✅
+ `timeutil.py`: UTC interno + `local_sleep_date` en Europe/Madrid, probado contra
  la noche del cambio de hora (24→25 oct 2026) ✅
+ Paquete de servicio de Windows (`ops/windows/`, con NSSM) ✅

## v0.3.1 — sonda de Polar
+ `ares polar-probe`: primera llamada real a los ocho endpoints que ARES va a usar ✅
+ Gestor de token de Polar (`polar_tokens.py`): renueva antes de caducar y guarda el par nuevo ✅
+ Renovación robusta: si Polar no envía un refresh token nuevo, se conserva el anterior ✅

**El conector de Polar en sí (`polar.py`: PPI, Nightly Recharge, sueño → capa
bruta) no está en este paquete.** La forma exacta del JSON de `/ppi-samples` no
está confirmada contra una respuesta real; se escribe mañana, con el cliente ya
creado y la primera llamada real hecha contigo delante — no antes.

Referencia: *ARES Physiology — Implementation Plan v0.2 FINAL — FROZEN*.

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

**4. Claves en el Llavero.**

- intervals.icu → Settings → Developer Settings → API key.
- Tredict → Ajustes → Personal API → nuevo token, con el scope `activityRead` marcado.

```bash
uv run ares secret set intervals_api_key
uv run ares secret set tredict_token
```

Pega cada valor (no se ve al escribir). macOS puede pedir permiso para el Llavero: «Permitir siempre».
Después, borra cualquier fichero de texto donde tuvieras estas claves guardadas.

**5. Base, diagnóstico y datos reales.**

```bash
uv run ares init-db
uv run ares doctor              # debe decir: 9/9 comprobaciones correctas
uv run ares sync intervals --days 30
uv run ares sync tredict --days 30
uv run ares stats
```

Resultado esperado: `intervals/wellness` y `tredict/activity` con filas reales. Repetir un `sync`
no duplica nada.

## Comandos disponibles

| Comando | Qué hace |
|---|---|
| `ares init-db` | Crea `~/ares-data/ares.duckdb` y aplica las migraciones pendientes |
| `ares secret set|check <clave>` | Guarda o comprueba un secreto en el almacén del sistema; nunca lo muestra |
| `ares sync intervals --days N` | Descarga el bienestar de intervals.icu a la capa bruta (solo añadir) |
| `ares sync tredict --days N` | Descarga la lista de actividades de Tredict a la capa bruta (solo añadir) |
| `ares doctor [--offline]` | Python, zona horaria, carpeta de datos, schema_version, secretos y red (ambas fuentes) |
| `ares polar-auth` | Autorización OAuth2 inicial con Polar (una sola vez; abre el navegador) |
| `ares polar-probe [--day AAAA-MM-DD]` | Primera llamada real a Polar: enseña la estructura de lo que devuelve (claves, tipos, rangos, no valores) y guarda las respuestas en bruto en `<datos>/probe/`. Solo lectura |
| `ares serve [--once]` | Proceso único con el planificador interno; `--once` hace una pasada y sale (pruebas) |
| `ares stats` | Filas de la capa bruta por fuente y últimas ejecuciones |

## Qué hay dentro

- `migrations/001–003`: esquema del plan v0.2 FINAL (con `source_status.device_id NOT NULL DEFAULT 'global'`
  y `decisions_recomputed` con `recompute_id`). `schema_version` registra cada migración con su hash;
  editar una migración ya aplicada se detecta y bloquea.
- `src/ares/`: configuración, secretos (keyring), logs JSON en `~/ares-data/logs/ares.jsonl`,
  base de datos, reintentos 2/8/30 s, capa bruta con hash, conectores de intervals.icu y Tredict
  (endpoints verificados el 27/09/2026 en tredict.com/blog/oauth_docs), `job_runs` con commit,
  versión y host.
- `tests/`: migraciones y `schema_version`, contrato de intervals.icu, contrato de Tredict
  (incluida la paginación por `_links.next.href`), idempotencia, reintentos y doctor.

## Nota sobre Tredict

El token personal solo trae el scope `activityWrite` por defecto: hay que marcar `activityRead`
al crearlo, o el `sync` fallará con HTTP 403. La sincronización trae el resumen de cada actividad
(id, fecha, deporte); el detalle completo (métricas, series) es un endpoint aparte, pendiente de
incorporar cuando haga falta para la fase 2 (Performance).

Datos en el Mac: `~/ares-data` (desarrollo). En el HP de producción: `ARES_DATA_DIR=C:\ares-data` en `.env`.
