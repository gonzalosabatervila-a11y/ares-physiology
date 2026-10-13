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
