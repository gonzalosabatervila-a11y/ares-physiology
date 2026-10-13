# ARES Physiology

Aplicación personal de fisiología, recuperación y entrenamiento. **WHOOP** es el
proveedor fisiológico activo; **Intervals.icu** aporta bienestar y carga y
**Tredict** aporta actividades. Los datos se guardan localmente, separados
del código y de los secretos.

## Estado actual · migración WHOOP v0.7

- API WHOOP v2: cliente OAuth, renovación protegida del token, paginación,
  ingestión en bruto de recuperación, sueño, ciclos y entrenos.
- Adaptador `PhysiologyProvider`: vincula recuperación y sueño, distingue
  siestas y zona horaria, y entrega noches normalizadas.
- Motor nocturno: rMSSD medido, ln(rMSSD) calculado, FC en reposo, duración
  de sueño, calidad y procedencia. Los valores ausentes no se inventan.
- Reconstrucción transaccional e idempotente de métricas; históricos de
  proveedor conservados en la base sin usarlos como fuente activa.
- App web local: Inicio, Progreso y Laboratorio; pruebas automatizadas.

**Validación inicial con cuenta real (13/10/2026):** WHOOP OAuth y
`ares doctor` con HTTP 200, 608 registros reales y 90 noches reconstruidas
en una carga de 90 días (informado desde el Mac). Falta validar la renovación
automática de tokens y la fiabilidad de sincronización sostenida.

## Medias comparadas COROS + WHOOP (exploratorias)

El origen declarado del bienestar de Intervals.icu es el reloj **COROS**:
`INTERVALS_WELLNESS_DEVICE=COROS` (puede cambiarse en `.env`). El JSON
`wellness` de Intervals.icu **no certifica cuál fue el dispositivo que midió**
cada valor. Antes de atribuir científicamente diferencias a un sensor, confirmar
en Intervals.icu que esos campos proceden realmente de COROS, no de WHOOP
sincronizado también con Intervals.

En Inicio, ARES combina WHOOP directo con los valores de Intervals.icu
**solo en la misma fecha local de sueño** y cuando WHOOP marca una noche
`high` o `fair`. La media es aritmética, con peso 50/50; si falta un
valor, la casilla de media queda vacía. Las series originales no cambian.

- Sueño: minutos efectivos WHOOP y `wellness.sleepSecs`, convertidos a minutos.
- Pulso en reposo: `daily_metrics.rhr` y `wellness.restingHR`.
- VFC: rMSSD WHOOP y `wellness.hrv`; se muestra como **EXP** porque distintos
  dispositivos pueden registrar ventanas de tiempo o metodologías no equivalentes.
  No usar su media para prescribir intensidad ni inferir recuperación clínica.
- Recovery WHOOP y CTL/ATL de Intervals permanecen **independientes**.
  Los indicadores ARES que usan valores pareados muestran CALC o EXP y la
  procedencia explícita. No sustituir días faltantes por valores de otras fechas.

La línea base estadística (21 noches) y la activación de recomendaciones son
dos hitos distintos: una línea base completa **no** valida aún el motor de
decisiones deportivas.

## ARES Intelligence · primera extensión del laboratorio (rama experimental)

El plan integral de fisiología, entrenamiento y recomendaciones validadas está en
[docs/ARES_INTELLIGENCE_ROADMAP.md](docs/ARES_INTELLIGENCE_ROADMAP.md).

Esta rama incorpora una pestaña **Fisiología** con 28/90/365 días de WHOOP,
media de 7/28 días y referencia histórica sin solapamiento. También introduce
**Entrenos**, un explorador de sesiones completas (resumen, laps, ritmo, FC,
potencia y curvas disponibles).

El catálogo de Tredict existente contiene principalmente el listado de
actividades, por lo que es necesario importar detalles para activar
el explorador. Con la aplicación y el servicio de ARES detenidos:

```bash
uv run ares tredict-details --days 30 --limit 5
uv run ares app
```

Esta importación hace como máximo cinco consultas de detalles
(y guarda respuesta bruta únicamente en la base local). No modifica
WHOOP, no publica GPS ni notas de atleta, no sincroniza en segundo plano
y no inventa sensores inexistentes. La autorización Tredict requiere
`activityRead`; los tokens de Personal API pueden requerir uso
periódico de la propia aplicación Tredict para permanecer activos.

**Desarrollo:** antes de actualizar el Mac ejecuta `uv run --frozen pytest -q`
y `node --check src/ares/app/static/app.js`. El branch y la PR no se
fusionan ni se despliegan al HP hasta que estas pruebas y la importación
de algunas sesiones reales estén verificadas.

## Mac · desarrollo

```bash
cd ~/ares
git status --short --branch
uv sync --frozen --python 3.12
uv run pytest -q
uv run ares init-db
uv run ares doctor --offline
uv run ares app
```

Abrir http://127.0.0.1:8443. La app lee la base en modo de solo lectura;
no se debe ejecutar simultáneamente con `ares serve`, que mantiene abierta
la conexión de escritura de DuckDB. Detener con Ctrl+C.

Si todavía no está clonado, utilizar
`git clone https://github.com/gonzalosabatervila-a11y/ares-physiology.git ~/ares`.
No reinicializar ni borrar un repositorio existente.

Los datos locales viven en `~/ares-data`, fuera de Git, y las credenciales
se guardan en el Llavero de macOS, nunca en `.env` ni en los commits.

## Conectar las fuentes

**WHOOP.** Registrar el cliente en el portal oficial para desarrolladores
y definir la URL de retorno exacta que utiliza ARES
(`WHOOP_REDIRECT_URI=http://localhost:8765/callback` por defecto).
Después, en el Mac y con el servicio parado:

```bash
uv run ares whoop-auth
uv run ares doctor
uv run ares backfill whoop --days 90
uv run ares stats
```

El comando `whoop-auth` solicita las credenciales sin mostrarlas y
abre el navegador. No compartir Client Secret, access token ni refresh token
en la conversación o en GitHub. Un conector vinculado a ChatGPT **no**
autoriza automáticamente esta aplicación local.

**Intervals.icu y Tredict.** Configurar su API key/token en el Llavero:

```bash
uv run ares secret set intervals_api_key
uv run ares secret set tredict_token
uv run ares sync intervals --days 30
uv run ares sync tredict --days 30
```

En Tredict el token debe tener el permiso `activityRead`. Los comandos
`sync` y `backfill` no deben ejecutarse mientras `ares serve` mantiene
la base abierta.

## Comandos principales

| Comando | Descripción |
|---|---|
| `ares init-db` | Inicializa la base y aplica migraciones pendientes. |
| `ares doctor [--offline]` | Comprueba entorno, credenciales y conexión (si procede). |
| `ares whoop-auth [--new-client]` | Autoriza la API WHOOP. |
| `ares backfill whoop --days 90` | Carga histórico WHOOP en local. |
| `ares sync whoop\|intervals\|tredict` | Sincroniza una fuente. |
| `ares stats` | Estado de fuentes vigentes y últimas sincronizaciones. |
| `ares app` | Abre la interfaz local de solo lectura. |
| `ares serve` | Levanta app, sincronizador y planificador en un proceso. |

## Criterio de calidad y límites

El objetivo de UX es **como mínimo WHOOP**, con claridad de medida
(MED), cálculo (CALC), estimación (EST) y experimental (EXP).
Las métricas de entrenamiento, descanso y recuperación se deben distinguir
de recomendaciones clínicas. Antes de crear índices propios de
disponibilidad, validar líneas base individuales, continuidad y sesgos.

**Migraciones históricas inmutables.** No modificar archivos SQL
`migrations/001–004` ya aplicados: `schema_version` verifica sus hashes.
El proyecto puede conservar tablas/vistas heredadas exclusivamente para
compatibilidad y recuperación de datos; no son conectores activos ni se
incluyen en los paneles de fuentes actuales.

## Producción más adelante

Mac para desarrollar; GitHub para versionar y revisar; HP Windows del
despacho como servidor 24/7 solamente cuando se apruebe la versión.
Documentación de operación: `ops/windows/README.md`.
El despliegue automático remoto todavía no está validado.
