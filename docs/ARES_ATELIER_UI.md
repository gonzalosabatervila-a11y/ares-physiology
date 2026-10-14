# ARES Atelier v2 · interfaz móvil y escritorio

**Estado:** diseño e implementación frontend en rama experimental de PR #4.
No está fusionado, no está desplegado al HP ni comprobado visualmente en Safari
del iPhone. Mantiene la identidad grafito/champán/salvia y el cálculo de
indicadores existente; es una mejora de jerarquía y experiencia, no una
modificación de resultados fisiológicos.

## Estructura

| Sección | Función primaria | Primera interacción |
|---|---|---|
| Inicio | Acciones útiles + línea base fisiológica real | Un toque: café/cena/cama |
| Entrenos | Correr frente a Otros | Elegir familia de actividad |
| Plan | Prescrito/registrado/respuesta, fueling diario | Ver semana vigente |
| LAB → Diario | Registrar, consultar resumen y cronología | 1 toque, confirmación no invasiva |
| LAB → Análisis | Cena/sueño y cafeína/sueño con n, límites | Explorar cohortes y método |
| Fisiología | Histórico y referencias | Elegir periodo |
| Progreso (ruta directa) | Tendencias deportivas | Disponible en #/progreso |
| Diagnóstico (ruta directa) | Calidad, versiones y fuentes | Disponible en #/lab |

**Una acción, una intención.** Los botones de Inicio y LAB ejecutan
el mismo `labQuick`; mantienen claves UUID de idempotencia ante reintentos
de red. Un toque no debe crear un evento si se está en modo `ares app`
de solo lectura; se muestra explicación y el botón queda deshabilitado.

**Estado visible:** avisos de guardado/error globales de duración
aproximada de 4,4 s, legibles incluso si se guardó desde Inicio.
El mensaje de fallo dice «no se ha confirmado el guardado», para no
declarar inexistente una petición cuyo resultado desconoce la UI.

**Separación Diario/Análisis:** enlace `#/laboratorio` frente a
`#/laboratorio?ver=analisis`, cargando el mismo resumen sin otra
petición externa. En Diario se ven capturas, valores registrados,
historial y línea temporal. En Análisis aparecen las cohortes y
sus limitaciones. No se ocultan datos originales, simplemente se
evita que las estadísticas bloqueen la captura rápida.

**Escritorio:** ancho máximo de lectura de unos 760 px y
navegación lateral solo a partir de 1180 px; de otro modo
se conserva la navegación inferior para el pulgar.

## Fisiología · Atelier científico (iteración posterior)

Vista `#/fisiologia` rediseñada en esta rama como panel editorial,
sin modificar cálculos, `daily_metrics` ni API.

- Primero contexto: noches válidas/procesadas, cobertura entre registros
  existentes, periodo (28/90/365 días), procedencia WHOOP y calidad de origen.
  La barra expresa proporción de **registros procesados** utilizables,
  NO la cobertura de todos los días de calendario del periodo.
- Dos indicadores principales abiertos: rMSSD (VFC) y FC reposo.
  Sueño, respiración, SpO₂, temperatura y Recovery de WHOOP pasan a
  tarjetas desplegables, sin ocultar sus datos ni alterar su sentido.
- **Gráficos honestos:** la abscisa utiliza `Date.parse(date)`
  en lugar del índice del array. Fechas omitidas provocan huecos,
  no distorsión temporal ni interpolación. Valores explícitos `null`
  interrumpen el trazo.
- **Exploración:** cursor local sobre la serie que muestra fecha y medida;
  teclado flechas izquierda/derecha, inicio y fin; SVG accesible
  descriptivamente. No se envía información al exterior.
- **Fuentes:** Recovery = `MODELO · WHOOP`, no `CALC · ARES`.
  Cambios de 7 días frente a referencia previa se describen sin
  «mejor»/«peor» automáticos. El método se conserva en desplegable.
- Adaptación móvil del eje de fechas a vista SVG de 360 unidades,
  tamaños legibles y reglas de pantalla estrecha/anchas.
- Nuevas comprobaciones estáticas en `tests/test_ares_atelier_ui.py`
  y prueba dinámica sintética en el motor JS (dos trazos separados
  ante registros ausentes, gráfico vacío si n insuficiente).

**No aprobado todavía:** inspección real en Safari iPhone y Mac,
VoiceOver, contraste WCAG cuantificado, comprobación de gestos
táctiles, tamaños de letra con accesibilidad del sistema,
latencia real o screenshots de 375/390/430/820/1440 px. No
declarar UI «perfecta» ni plenamente accesible hasta completarlo.

## Scientific Atelier · refinamiento editorial de Fisiología (14/10/2026)

La revisión recibida de terceros examina la versión ARES v0.6 del
30/09/2026: resulta valiosa como visión, pero NO describe todas las
integraciones ni los colores de la rama actual. Conservamos la idea
de *instrumento de laboratorio + editorial nocturno* y evitamos
reintroducir cian o referencias a Loop/Polar como fuente principal.

Refactor realizado **in situ** en el módulo final de `app.css`:
se reemplazó el bloque previo de Fisiología, en vez de añadir otra capa
de sobrescrituras. Sin dependencias nuevas ni descargas extra de fuentes.

- **Titular editorial:** Archivo para numerales e interfaz, serif
  sobria con fallback local solo para el énfasis narrativo.
- **Cifras:** lectura y unidad separadas, Archivo variable con ancho
  condensado (eje `wdth`). La medida normal es marfil; no usa
  semáforos arbitrarios.
- **Fuentes:** WHOOP directo en un pie discreto; Recovery sigue
  siendo `MODELO · WHOOP`, nunca un cálculo atribuido a ARES.
- **Superficies:** resumen con aire y una sola línea de separación;
  VFC y FC dentro de un mismo panel con división mínima; señales
  secundarias como filas desplegables, no más tarjetas repetidas.
- **Curvas:** SVG original sin nueva dependencia, puntos trazados
  en fechas reales; huecos explícitos, cursor accesible con ratón
  y flechas; el color champán se reserva para los datos y la
  salvia para la posición activa/calidad.
- **Microtipografía:** Martian Mono queda para etiquetas técnicas,
  fecha/procedencia, sin dominar titulares.
- **Diseño móvil:** tamaños de numerales condensados y anchos máximos;
  sin supuestos de datos nuevos ni tratamientos clínicos.

**Verificaciones completadas:** JavaScript parsea, renderizado sintético
de las métricas y estados, versión cache-busting de HTML, tests de
regresión de UI ampliados. **No validado todavía** con `pytest` real
en Mac, screenshot real, Safari iPhone, VoiceOver ni presupuesto
de interacción táctil; no se declara terminado visualmente.

## Objetivos visuales y operativos

- Paleta: grafito `#0C0E0D`, champagne `#D9B782`,
  sage `#A6BDA3` con texto marfil, sin azul cian.
- Tipografía: Archivo y Martian Mono con fallbacks de sistema.
- Inputs móviles de al menos 16 px, para evitar el zoom automático
  de Safari iPhone; botones de al menos 44 px de altura.
- El diálogo mantiene `aria-modal`, botones y labels de formulario;
  las confirmaciones tienen `role=status`, `aria-live=polite`.
  La verificación completa con lector de pantalla sigue pendiente.
- Respeto a `prefers-reduced-motion`, sin animaciones imprescindibles.
- Las peticiones HTTP reciben un identificador de navegación:
  respuestas antiguas nunca pisan una pantalla abierta después.
- Errores de lectura con botón «Reintentar», sin prometer datos
  sincronizados cuando no lo están.

## Aceptación antes de decir «interfaz validada»

1. Ejecutar `uv run --frozen pytest -q` y
   `node --check src/ares/app/static/app.js &&
   node --check src/ares/app/static/lab_ui.js`.
2. Con `uv run ares serve` en Mac, ir a `#/inicio`;
   comprobar que los botones y la línea base se ven por encima
   de los diagnósticos de fuentes.
3. Pulsar Café 100 mg en Inicio; observar confirmación,
   comprobar una sola entrada en LAB y editar a 60 mg.
4. Registrar «Cena terminada» y «Me acuesto»;
   confirmar intervalo manual y cronología.
5. Ver `#/laboratorio?ver=analisis` sin valores inventados
   cuando todavía faltan muestras.
6. Inspeccionar en tamaños 375×812, 390×844, 430×932,
   iPad 820×1180 y escritorio 1440×900,
   sin botones ocultos/solapes ni zoom involuntario en inputs.
7. Desde iPhone por HTTPS privado de Tailscale Serve, no Funnel,
   comprobar guardado, errores con Mac apagado y vuelta a red.
8. Medir p50/p95 de registro y carga en dispositivo real;
   los objetivos de UX todavía NO se han contrastado.
9. Confirmar que Entrenos, Plan, Fisiología, Progreso y
   `#/lab` mantienen contenidos y rutas existentes.
10. Ninguna exportación de datos fisiológicos a servicios
    externos de IA; ningún despliegue ni merge sin autorización.

## Siguientes iteraciones, no implementadas

- Atajo Safari/iOS que abra directamente LAB y widgets/Shortcuts
  tras evaluar autenticación y privacidad.
- Favoritos editables de dosis de café (ej. 60/100/150 mg),
  sin fingir medición precisa.
- Gráficos interactivos día a día con tooltip y agrupación cronológica.
- Cola offline cifrada y reconciliación multi-dispositivo,
  solo tras diseño de conflictos y recuperación.
- Auditoría visual de contraste y WCAG con dispositivos y lector real.
