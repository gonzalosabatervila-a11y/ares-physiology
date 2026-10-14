# ARES Intelligence · arquitectura del laboratorio personal

**Dirección del producto:** superar la experiencia analítica de WHOOP al unir
sueño, fisiología, sesiones segundo a segundo, periodización, nutrición,
composición corporal y decisiones deportivas verificables. ARES no es un
dispositivo médico ni debe prometer entrenamientos infalibles.

## Contrato de veracidad

1. Ninguna cifra se muestra como medida si es calculada o estimada:
   **MED / CALC / EST / EXP** y origen acompañan cada resultado.
2. No se promedian dispositivos por defecto si no comparten fecha local,
   unidad y metodología. La fusión de VFC COROS–WHOOP sigue experimental.
3. Una fecha sin datos no equivale a descanso, cero estrés o cero actividad.
   Las gráficas conservan huecos y las medias exigen cobertura mínima.
4. Datos fisiológicos privados se guardan en la base local, fuera de Git;
   jamás credenciales, archivos FIT, tracks GPS ni payloads reales en commits.
5. Recomendaciones de intensidad y posibles avisos de salud requieren
   umbrales personalizados, evidencia, comprobaciones y confirmación humana.
   No atribuir causalidad a correlaciones aisladas.
6. Cada fuente, método, calibración, versión y cambio de hardware es
   reproducible. El HP solo recibe versiones revisadas.

## Fase 1 · Entregada como propuesta de desarrollo

**Tu fisiología**: visualización 28/90/365 días de WHOOP directo:
rMSSD, FC en reposo, sueño efectivo, frecuencia respiratoria, SpO₂,
temperatura cutánea y recovery del fabricante. Calidad, faltantes y
anomalías visibles. Media de 7 días, de 28 días y comparación con
los 28 días previos a la semana reciente, sin solapamiento.
Ni tendencias ni desviaciones son diagnósticos.

**Tus entrenamientos**: desde Tredict Personal API, sesión completa
`GET /activity/{id}?extraValues=1&allSeries=1&withLaps=1`, guardada
en bruto localmente, con resumen, vueltas e historial temporal.
Primero importar voluntariamente como máximo 5–10 sesiones
(`ares tredict-details --days 30 --limit 5`) y comprobar esquema.
Una conexión ChatGPT–COROS NO es acceso directo de ARES al mismo origen.

**Validación**: fixtures sintéticos, pruebas de aislamiento del dispositivo,
fuentes, ausencia de datos, privacidad y coherencia de fechas. Esta rama
es de desarrollo y **no** está fusionada con producción. Antes de
entregarla, ejecutar pruebas Python y validación sintáctica JS en el Mac.

## Execution Intelligence · evidencia de ejecución y fisiología temporal

**Implementado en PR #4 (rama Mac, octubre 2026):**
- `src/ares/app/plan_execution.py` recupera registros Tredict de cada
  semana sin límite engañoso de «50 sesiones recientes»; deduplica por
  ID, prefiere `activity_detail` y convierte UTC a Europe/Madrid.
- Estados diarios `future`, `no_record_found`,
  `observed_unverified` y `rest_day_activity`. No existen estados
  de cumplimiento confirmados automáticamente; medir la duración
  completa no garantiza cumplir bloques ni zonas.
- Una única actividad permite contextualizarse mediante la última
  noche WHOOP válida previa y primera posterior (por intervalos reales
  de sueño, no solo fechas). Se excluyen noches no puntuadas,
  en calibración o de mala calidad. Con varias carreras diarias,
  la atribución fisiológica por sesión se deja sin dato.
- Panel resumen distingue minutos observados de planificados, muestra
  los eventos con enlace al detalle y la fecha de última sincronización
  correcta de Tredict. No expone GPS ni notas privadas.

**Actualización auditada del Excel sin OAuth Drive local:**
- Comando `ares plan-check archivo.xlsx` muestra por defecto
  diferencias por fecha/campo, valida 9 semanas (63 fechas) y SHA-256
  sin escribir. El archivo se obtiene manualmente de Drive.
- `--apply` autoriza reemplazar solo el archivo
  `~/ares-data/training_plan.json` de forma atómica, con backup de
  la versión previa. El servidor vuelve a leer la copia en cada petición.
- Si esta copia se estropea, el backend recurre a la versión validada
  incluida en la app y muestra una advertencia explícita.
- **No se afirma sincronización en vivo con Google Drive** ni
  autenticidad remota automática del archivo descargado.
- No se han tocado los documentos originales, DuckDB, HP Windows
  ni la pauta de entrenamiento.

**Siguientes validaciones:** ejecutar pruebas pytest en Mac,
comparar el importador con el XLSX original, comprobar S32/S37
con entrenamientos reales y noches disponibles. Posteriormente,
implementar comparación objetiva de vueltas, HR de cada intervalo,
carga por zona y adherencia por tipo de sesión, con aceptación
manual antes de cambiar el plan.

## Plan de maratón conectado a Drive y Fueling ARES · octubre 2026

**Fuentes consultadas en la carpeta de trabajo (FUERA de Old):**

- `000 / ARES / 01 RUNNING / MARATÓN / Plan_Maraton_Gonzalo_MAESTRO_v9.xlsx`
  ([original](https://docs.google.com/spreadsheets/d/10FyPnvsvkEf2_0sHbix8KoeFmF2KECVV/edit)),
  versión 08/10/2026, alineada con el plan maestro v3.4 y mesociclos 5-8/9-12 v10.
- `000 / ARES / 06 NUTRITION / Endurance Fueling /
  Fueling ARES — Sistema Maestro de Nutrición v1.0`
  ([original](https://docs.google.com/document/d/1iF-YMdZDY-KRlRnIzktdqTuoaCFu-WmL-x6eyCI09jE/edit)),
  19/09/2026.
- Protocolo de hidratación v4, julio 2026, usado como contexto secundario,
  nunca en contra de la prescripción semanal vigente.

**Integración actual:** archivo legible `src/ares/app/plan_oct_dec_2026.json`,
generado desde el Excel vigente el 14/10/2026. Contiene **S32–S40**
(12/10–13/12/2026), siete días por semana, 63 fechas distintas,
sesiones, duración, detalles, kilómetros cuando constan, calzado, fuerza y
fuelling específico. La ruta `GET /api/plan?week=S32` presenta
calendario + nutrición. Inicio incluye la sesión de hoy.

**IMPORTANTE:** el servidor local NO tiene conectada la API de Google Drive:
es un **snapshot manual**, con enlace de origen y fecha. Si se modifica el
Excel maestro en Drive, el snapshot debe regenerarse y revisarse antes de
desplegar. Ningún dato nuevo de planificación se inventa al agotar las semanas
importadas, ni se usan ficheros del subdirectorio Old.

**Filosofía operacional:**
- FC manda sobre velocidad/ritmo. Ergo 21/09/2026: Z2 133–152,
  Z3 153–162, Z4 163–172 ppm.
- Martes calidad por la mañana y fuerza 14:20 (según maestro).
- No compensar volumen de entrenamientos perdidos ni alterar prescripciones
  por una única medición de HRV.
- Carrera registrada por Tredict = **observación**, NO prueba de haber
  completado la sesión correspondiente; se muestra separada.

**Fueling diario:** bandas extraídas de v1.0:
LOW 3–4; MEDIUM 4–5; HIGH 5–6; VERY HIGH 6–7 g CH/kg/día.
La banda se asigna por carga de hoy y *preparación de mañana*;
proteína orientativa 1,8 g/kg/día y grasas iniciales 60–75 g/día.
Se aplica primero la pauta `g/h` ESPECÍFICA de la semana
(v. gr. S32 largo 135′ 45 g/h; S33 largo 145′ 50 g/h) y solo si falta
se muestra la banda general de Fueling v1.0, claramente etiquetada.
La progresión intestinal no se acelera automáticamente.
Cenas no voluminosas, última ingesta habitual a las 18:00;
desayuno post-entreno y comida principal como ventanas de recuperación
y precarga. Mostrar también agua/sodio por contexto y no fomentar
beber por obligación.

**Peso:** no se almacena en el código ni en Git. Si se configura
`ARES_NUTRITION_WEIGHT_KG` en `.env` LOCAL, se convierten los objetivos
por kg a gramos; de lo contrario la UI solo muestra los rangos g/kg.
El documento v1.0 (19/09/2026) registra un peso de trabajo de 70,5 kg,
pero NO se considera medición actual sin validarlo. Requiere calibración
de 7 días de ingestas, rendimiento, GI, sueño y sudoración para afinar.

**Siguientes hitos:** sincronizador de Drive con credenciales autorizadas
y revisión de versiones; comparación de plan prescrito vs ejecutado
por tipo de sesión y cumplimiento de zonas, no solo fecha; vistas de
mesociclo, carga semanal, preparación Valencia y curva rendimiento;
ingesta real frente a previsionada, sin crear diagnósticos clínicos.

## Inicio · línea base visible, no una presentación

Cuando existen al menos 21 noches válidas anteriores a la última de WHOOP,
Inicio muestra la **línea base personal real**, sin exigir decisiones del
entrenador todavía no validado. La referencia es provisional con 21–59
noches y establecida a partir de 60 noches aptas.

El cálculo utiliza hasta las **60 últimas noches puntuadas y válidas previas
a la noche actual**, con control del estado de calibración, calidad y
`night_check`. Para cada señal (rMSSD, pulso en reposo, sueño y frecuencia
respiratoria) calcula la mediana y percentiles 25 y 75; cada una exige 21
observaciones no nulas. En la misma tarjeta se muestra el valor de la
última noche y su diferencia absoluta frente a la mediana, pero ese valor
**no forma parte de la mediana**.

El rango central no constituye un rango clínico, zona segura ni semáforo de
entrenamiento. ARES Coach aún no prescribe intensidades de forma autónoma.
La portada sustituye el antiguo mensaje gigante «Línea base disponible»
y el aviso de sincronización se reduce a una fila discreta.

## ARES Atelier · identidad visual, Entrenos y frescura (rama de desarrollo)

- **Diseño:** grafito cálido, champán y salvia, eliminando el cian de UI,
  gráficos y botones; navegación legible en móvil y escritorio.
- **Entrenos / Correr:** catálogo COROS declarado vía Tredict. Incluye
  actividades con resumen aunque todavía no se hayan descargado sus series,
  y permite abrir el detalle completo cuando esté disponible. Se omiten las
  carreras de WHOOP para no contarlas dos veces.
- **Entrenos / Otros:** WHOOP como fuente principal para caminar, senderismo,
  rucking explícito, fuerza y demás deportes distintos de correr. Un registro
  llamado walking **no implica** que se llevase una mochila de rucking.
  Puede haber actividades solo en Tredict: se usan como respaldo, sin
  eliminar sesiones distintas ocurridas a horas parecidas.
- **Duplicados:** una coincidencia temporal de ±15 minutos solo se considera
  duplicada cuando el deporte pertenece a la misma familia.
  No se afirma que sea la misma sesión sin identificador compartido.
- **Degradación de Intervals.icu:** si wellness devuelve HTTP 503,
  ARES conserva los datos previos y registra el error por separado.
  El planificador aplaza solo Intervals durante 30 minutos, sin pausar
  WHOOP ni Tredict. Una consulta manual explícita puede reintentar antes.
  El HTTP cliente ya realiza tres reintentos (2, 8 y 30 s con variación).
- **Estado de datos:** `ares app` = solo lectura: el botón circular **recarga
  la pantalla**, nunca descarga del proveedor. `ares serve` = mismo servidor
  web + sincronización al arrancar y planificador posterior; en la ventana
  diurna WHOOP descarga ciclos y entrenamientos terminados. La pantalla
  se recarga cada cinco minutos mientras está visible.
- **Datos recientes:** se enseña la última fecha de registro para la fuente;
  no confundirla con el momento de última sincronización.
- **Fuente declarada:** la etiqueta COROS en los entrenamientos de Tredict
  es configuración de origen, no una certificación individual de hardware.

### Cómo activarlo en Mac, sin dos propietarios de DuckDB

Detener `ares app` con Ctrl+C. En la rama de desarrollo, ejecutar
`uv run --frozen pytest -q` y `node --check src/ares/app/static/app.js`.
Con ambos comandos correctos:

```bash
uv run ares serve
```

Abrir http://127.0.0.1:8443/#/entrenos?tipo=correr
o http://127.0.0.1:8443/#/entrenos?tipo=otros

**No** ejecutar `ares app` a la vez que `ares serve`; ambos abrirían
la base de DuckDB desde procesos diferentes. Para importar detalles
de Tredict manualmente, detener primero el servicio y usar
`uv run ares tredict-details --days 30 --limit 5`.

El servidor de desarrollo Mac deja de sincronizar cuando se cierra el
proceso. Las tareas Windows del HP no se han modificado ni activado.

## Fase 1.5 · Training Intelligence y respuesta fisiológica (en revisión)

La rama de desarrollo implementa, sin modificar los registros originales:

- **Calidad por sensor**: cobertura de pulso, velocidad y parejas simultáneas.
  Nulos y valores implausibles no se convierten en ceros.
- **Deriva FC/velocidad (EXP)**: cambio descriptivo del cociente FC/velocidad
  entre mitades de un tramo de carrera. NO es la deriva aeróbica validada.
  Solo aparece con ≥40 minutos, menos de 3 % de pausas,
  cobertura de pares ≥80 %, velocidad CV ≤10 % en cada mitad y
  velocidades medias semejantes (diferencia ≤5 %).
  El método descarta los primeros 10 minutos y los últimos 5.
  La altimetría, el clima y el error de sensor siguen siendo factores de confusión.
- **Consistencia de vueltas (CALC)**: coeficiente de variación del ritmo
  de al menos tres vueltas de distancia comparable (±5 %).
  No confundir vueltas de calentamiento con intervalos por defecto.
- **Comparador (EXP)**: parejas de carrera de 3 a 50 km cuya distancia
  difiere ≤10 % y FC media ≤5 lpm, mostrando variación de velocidad;
  no garantiza mismo recorrido ni estado ambiental.
- **Zonas históricas**: distribución de segundos en las zonas de FC y
  límites que Tredict adjunta a esa sesión; no aplicar zonas actuales
  a un entrenamiento anterior.
- **Fisiología alrededor del entreno**: última noche WHOOP que terminó
  realmente ANTES del ejercicio y primera que empezó DESPUÉS del ejercicio,
  por instantes UTC, con ventana de 72 horas. Muestra diferencias
  descriptivas HRV/RHR/sueño/Recovery, sin atribución causal.

Se ha contrastado la **estructura**, no copiado el contenido, de una
actividad real de Tredict: `summary` contiene duración, distancia,
ritmo, FC, potencia y cadencia; `laps` son vueltas cronológicas;
`seriesSampled` tiene `sampleSize`, `endOffset` y `data` con
los sensores; `currentZones` conserva umbrales históricos y
`summary.zonesDistribution` los segundos clasificados.
Cada actividad puede diferir: campos opcionales ausentes permanecen
sin dato. No se han subido archivos, coordenadas ni valores privados.

**Estado:** código + pruebas sintéticas en la rama experimental.
Todavía hay que ejecutar todas las pruebas en el Mac, importar un pequeño
lote de sesiones completas, comprobar sus unidades y la presentación
móvil. No afirmar precisión, resultados individuales o validación de
métodos antes de hacerlo.

## Fase 2 · Entreno de nivel analista

- **Biblioteca de sesiones**: filtrar carrera, fuerza, ciclismo; comparar
  sesiones similares por distancia, desnivel, duración, condiciones y fase.
- **Capa 1 (medido)**: curvas de velocidad/ritmo, FC, potencia, cadencia,
  altimetría, dinámica (solo si COROS/Tredict entregan series).
- **Capa 2 (calculado)**: laps, intervalos y recuperaciones automáticos
  contrastados con laps reales; ritmo a FC fija, deriva aeróbica y
  eficiencia, con protocolos y sesgos explícitos.
- **Capa 3 (estimado)**: umbral, velocidad crítica, VO₂ y predicción de
  rendimiento SOLO cuando haya suficientes esfuerzos representativos
  y métodos calibrados; intervalos de incertidumbre, nunca una cifra
  supuestamente exacta.
- **Durabilidad**: relación de ritmo, FC y potencia durante tiradas largas,
  separando calentamiento, pausas, subida/bajada y terreno.
- FIT original opcional y exportación de entrenamientos desde COROS/Tredict,
  preservando la fuente y la integridad del archivo.

## Fase 3 · Fisiología y adaptación

- Curvas 7/28/90/365 noches con estadísticas robustas y líneas base por
  dispositivo; HRV (rMSSD/lnRMSSD), pulso, sueño, frecuencia respiratoria
  y tendencias de temperatura. Rotura de línea base si cambia unidad.
- Relación descriptiva sueño/carga/entrenamiento con ventanas y
  retardos explícitos; evitar comparaciones causales.
- Entrenamiento en zonas individualizadas por pruebas recientes y
  condiciones, no por fórmulas genéricas; sesiones con Polar H10 cuando
  exista traza y contraste con la FC del reloj.
- Conexiones entre composición corporal, nutrición, sueño y rendimiento
  solo si el usuario aporta fuentes/mediciones suficientemente fiables.

## Fase 4 · ARES Coach y planificador

- Plan anual y por bloques hacia los objetivos deportivos; semanas
  de carga, descarga, entrenamiento clave y competición.
- Cada sesión futura tendrá propósito, intervalo de intensidad/duración,
  carga estimada, criterios de modificación y de abandono.
- Comparar **prescrito** vs **realizado** sin castigar variaciones
  justificadas; propuestas de ajuste revisables, nunca automatizadas
  unilateralmente.
- Proyección probabilística de 5K/10K/media/maratón calibrada con carreras
  reales, densidad de entrenamiento y perfil de carrera.
- Backtest prospectivo de recomendaciones: registrar qué se recomendó,
  por qué, qué ocurrió después y si el método necesita recalibrarse.

## Fase 5 · Plataforma integral

- Nutrición, hidratación, aporte de carbohidratos, ingesta en largos,
  composición corporal y recuperación; sin convertir la app en contador
  de calorías obligatorio.
- App móvil/desktop rápida, local-first con sincronización controlada,
  exportación y auditoría; diseño accesible, legible, compatible con
  múltiples pantallas.
- Integración con planificación y archivos de Google Calendar/Tredict/COROS
  donde exista permiso, con resolución de duplicados entre fuentes.
- Backup/restauración automática ensayada, cifrado y control de acceso;
  despliegue remoto al HP únicamente después de pruebas.

## Bloqueadores reales antes de prometer resultados avanzados

La lista resumida de Tredict NO es suficiente para análisis segundo a
segundo. El primer paso es obtener y validar los objetos completos y
medir su cobertura (serie FC/ritmo/laps/altitud/cadencia/potencia).
No todas las actividades incluyen todos los sensores.

El bienestar de Intervals.icu no prueba por sí solo si los valores son
mediciones COROS o reenvíos desde WHOOP. Antes de usar la fusión para
inferencias deportivas, verificar la procedencia de cada campo.

**Definición de terminado:** una vista nueva debe tener datos realmente
disponibles, controles de calidad, pruebas, estados vacíos honestos,
documentación de fuente y límites, y validación en el Mac. No basta
con que la pantalla tenga gráficas atractivas.
