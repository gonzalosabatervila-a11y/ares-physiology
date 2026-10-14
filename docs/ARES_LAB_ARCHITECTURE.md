# ARES LAB · Arquitectura v0.1 y ruta de investigación personal

**Estado de entrega:** PR #4 en borrador sobre `whoop-migration`.
Desarrollo Mac; sin despliegue a HP ni cambios en Drive. Requiere pruebas
`uv run --frozen pytest -q` sobre el Mac antes de activarlo.

## Auditoría técnica (14/10/2026)

| Componente | Estado antes de LAB | Estado con LAB v0.1 |
|---|---|---|
| WHOOP | OAuth, backfill 90 d y normalización nocturna en `daily_metrics` | Se lee sin modificarlo |
| COROS/Tredict | Resúmenes, detalle opcional y Marathon Lab prescrito / observado | Se conserva sin escribir |
| Intervals.icu | Bienestar, carga con tolerancia 503 | Se conserva |
| DuckDB | esquema 004 + fuente bruta y derivadas | nueva migración ADITIVA 005, `lab_events` |
| UI móvil | Inicio, Entrenos, Plan, Fisiología; Lab técnico oculto | nueva pestaña LAB; diagnóstico técnico se mantiene en `#/lab` |
| PWA | Instalación orientada a Inicio | inicio LAB en instalaciones nuevas |
| Sincronización Drive | snapshot manual plan v9 | no se modifica |
| IA externa | no implementada | no se envía ningún dato a IA |

### Modelo de dato temporal y trazabilidad

La tabla `lab_events` es independiente de `raw_payload`. Cada evento
contiene UUID, tipo, `occurred_at` con zona, zona de usuario, dosis de
cafeína en mg (solo si aplica), base de estimación, nota corta, fuente
manual, clave de idempotencia única y fechas de creación, última revisión
y anulación lógica. La anulación excluye el registro de los análisis sin
reescribir ni borrar el histórico previo.

Primera taxonomía intencionadamente mínima:
`coffee`, `dinner_end`, `bedtime`. No fingir que medir
`bedtime` equivale a detectar el inicio de sueño WHOOP.
Dosis rápida café = **100 mg estimados y editables**, nunca medición
individual ni supuesto sobre el volumen consumido.

### API y seguridad

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/lab/events` | Diario, resumen del día, grupos descriptivos, cronología |
| POST | `/api/lab/events` | Crear con UUID de idempotencia cliente |
| PATCH | `/api/lab/events/{uuid}` | Corregir instante, dosis, nota |
| DELETE | `/api/lab/events/{uuid}` | Anulación lógica |

El modo `ares app` es **SIEMPRE solo lectura**. La escritura existe
únicamente en `ares serve` (propietario único de DuckDB).
Protecciones: Host permitido loopback / nombre privado `.ts.net`;
Origin mismo sitio y cabecera `X-ARES-LAB`; para Tailnet solo HTTPS.
No abrir Funnel ni puerto público, ni instalar esta versión en máquinas
de terceros. Tailscale Serve debe protegerse mediante ACL de Tailnet
y acceso exclusivo de los dispositivos autorizados.

No hay sincronización con cuentas externas de IA, ni exportación de
notas, coordenadas o valores biométricos. Para iPhone la app web debe
ser accesible desde el mismo Tailnet por Tailscale Serve HTTPS, pues
`127.0.0.1` del Mac no sirve como URL desde el iPhone.

No se promete modo offline de datos en v0.1: sin conexión los registros
no se consideran guardados; no se usarán colas locales con datos
fisiológicos en texto sin una decisión explícita de privacidad.
El PWA abre LAB primero, pero el Mac debe estar encendido y accesible.

### Primera correlación reproducible

Para cada noche WHOOP con:
`quality` high/fair, `score_state=SCORED`, fuera de calibración,
`night_check=ok` y comienzo del sueño disponible, se toma la **última
cena manual dentro de las 12 horas anteriores al comienzo del sueño**.
Las franjas son: menos de 2h, 2–3h, 3–4h, 4–12h.
Se muestran `n` y medias de VFC (rMSSD), RHR y sueño efectivo,
solo si la franja tiene al menos 5 noches; comparación mínima: >=20
noches emparejadas y dos franjas con al menos 5 observaciones.
Son promedios exploratorios sin ajuste por entreno, estrés, alcohol,
horario, temperatura ni ciclo de carga. No aplicar inferencia causal ni
decisiones de entrenamiento.

En paralelo, el último intervalo manual `dinner_end → bedtime`
aparece inmediatamente, independiente de los dispositivos.
El total diario de cafeína indica lo que fue **anotado**, no
todo el consumo real.

La línea temporal de 7 días muestra eventos y marcas horarias del
**inicio de sueño WHOOP**; sin curva cardíaca segundo a segundo.

## Fases ejecutables

- **Fase 1 — entrega v0.1:** migración 005, captura 1 clic, dosis/horas
  editables, anulación, timeline, tiempo cena→cama, grupos con WHOOP y
  pruebas offline. Verificar Mac y UX móvil con registros reales.
- **Fase 2 — Hyperfast + funcionamiento móvil:** evaluar rendimiento
  real p50/p95 de captura; objetivos de diseño (aún NO medidos):
  respuesta de escritura local p95 < 300 ms, vista precargada < 1 s y
  registro habitual 1 toque después de entrar. Instalar PWA en iPhone,
  confirmar Tailscale Serve, considerar cola offline **cifrada** solo
  tras definir recuperación, autorización y resolución de duplicados.
- **Fase 3 — cafeína/dormir:** vinculación cafeína→inicio entrenamiento,
  cafeína→sueño posterior, diario de cansancio y medidas de confusión,
  con tamaño de muestra e intervalos de incertidumbre.
- **Fase 4 — ARES Discover:** hallazgos con hipótesis, n, magnitud,
  incertidumbre, faltantes, controles y corrección por pruebas múltiples.
  No convertir correlación en causalidad.
- **Fase 5 — ARES Experiments:** alternancia planificada N=1, resultados
  pre-registrados, adherencia y análisis de sensibilidad.
- **Fase 6 — IA conversacional local:** motor de consultas y estadísticas
  deterministas; IA interpreta salidas auditables sin inventar datos.
  Enviar datos personales a modelo remoto **solo previa autorización**.
- **Fase 7 — Gemelo estadístico:** modelos de referencia sencillos primero,
  validación temporal prospectiva, incertidumbre y detección de
  degradación. No diagnóstico clínico.
- **Fase 8 — Integraciones posteriores:** importación de nutrición precisa,
  parámetros COROS/WHOOP y experimentos multivariable según necesidad
  demostrada. Evitar recopilación indiscriminada.

## Checklist de aceptación del MVP

1. Backup de `ares.duckdb` con ARES parado antes de aplicar 005.
2. `uv run --frozen pytest -q` y `node --check` para los dos JS.
3. `uv run ares serve` aplica migración 005 y abre LAB.
4. Café una vez: una fila, con `100 mg · estimado`; repetir la
   misma petición no duplica. Editar a 60 mg y corregir hora funciona.
5. `Cena terminada` y `Me acuesto`: el panel calcula minutos exactos
   con zona Madrid, sin rellenar por inferencia noches anteriores.
6. Borrar lógicamente un registro lo excluye de los cálculos.
7. Sin cenas registradas, el panel reconoce que faltan emparejamientos
   aunque existan 90 noches WHOOP.
8. La escritura en `ares app` devuelve 403; origen web ajeno también.
9. El portal técnico Lab preexistente permanece accesible `#/lab`;
   Inicio, Entrenos, Plan y Fisiología siguen funcionando.
10. En iPhone, el servicio funciona por HTTPS de Tailscale Serve privado
    y la app de pantalla de inicio abre `#/laboratorio`.
11. El Mac y el iPhone están online durante las pruebas: todavía no hay
    garantías de funcionamiento sin conexión.
12. Sin merge ni despliegue HP sin revisión expresa.

